"use client";

import {
  ApiError,
  api,
  type JobResponse,
  type OpportunityAnalysisArtifact,
  type OpportunityAnalysisOutput,
  type OpportunityOfferDraftResource,
  type OpportunityOfferDraftSection,
} from "@oracle/api-client";
import {
  CheckCircle2,
  Link2,
  RefreshCw,
  Sparkles,
  Target,
  XCircle,
} from "lucide-react";
import Link from "next/link";
import { FormEvent, useCallback, useEffect, useMemo, useRef, useState } from "react";
import { toast } from "sonner";
import { PermissionGate } from "@/components/auth/auth-boundary";
import { JobProgress } from "@/components/reporting/job-progress";
import { AsyncActionButton } from "@/components/ui/async-action-button";
import { PageHeader } from "@/components/ui/page-header";
import { renderInlineEmphasis } from "@/lib/inline-emphasis";

const terminal = new Set(["succeeded", "failed", "cancelled"]);

function idempotencyKey(dossierId: string): string {
  const suffix =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `dossier-opportunity-${dossierId}-${suffix}`.slice(0, 200);
}

function errorMessage(reason: unknown, fallback: string) {
  return reason instanceof ApiError ? reason.problem.detail : fallback;
}

/** Solo hechos con al menos una evidencia; sin fuente no se exponen. */
function groundedFacts(output: OpportunityAnalysisOutput | null | undefined) {
  if (!output?.facts?.length) return [];
  return output.facts.filter(
    (fact) =>
      typeof fact.statement === "string" &&
      fact.statement.trim() &&
      Array.isArray(fact.evidence_ids) &&
      fact.evidence_ids.length > 0,
  );
}

/** Inferencias solo si citan evidencia (misma regla que Competidor Sintético). */
function groundedInferences(output: OpportunityAnalysisOutput | null | undefined) {
  if (!output?.inferences?.length) return [];
  return output.inferences.filter(
    (item) =>
      typeof item.statement === "string" &&
      item.statement.trim() &&
      Array.isArray(item.evidence_ids) &&
      item.evidence_ids.length > 0,
  );
}

function groundedActors(output: OpportunityAnalysisOutput | null | undefined) {
  if (!output?.candidate_actors?.length) return [];
  return output.candidate_actors.filter(
    (actor) =>
      typeof actor.name === "string" &&
      actor.name.trim() &&
      Array.isArray(actor.evidence_ids) &&
      actor.evidence_ids.length > 0,
  );
}

function recommendationLabel(value: string | undefined) {
  switch (value) {
    case "go":
      return "Avanzar (go)";
    case "investigate":
      return "Investigar";
    case "hold":
      return "Mantener en espera";
    case "no_go":
      return "No avanzar (no-go)";
    default:
      return value || "—";
  }
}


type DraftSaveState = "idle" | "dirty" | "saving" | "saved" | "conflict" | "error";
type DraftExportState = "idle" | "preparing" | "downloaded" | "conflict" | "error" | "dirty_blocked";

function draftStatusLabel(state: DraftSaveState): string {
  switch (state) {
    case "dirty":
      return "Sin guardar";
    case "saving":
      return "Guardando…";
    case "saved":
      return "Guardado";
    case "conflict":
      return "Conflicto de versión";
    case "error":
      return "Error al guardar";
    default:
      return "Listo";
  }
}

function draftExportStatusLabel(state: DraftExportState): string {
  switch (state) {
    case "preparing":
      return "preparando";
    case "downloaded":
      return "descargado";
    case "conflict":
      return "conflicto";
    case "error":
      return "error";
    case "dirty_blocked":
      return "guarda antes de exportar";
    default:
      return "";
  }
}

function triggerBlobDownload(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  try {
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.rel = "noopener";
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
  } finally {
    // Revoke after the browser has a chance to start the download.
    window.setTimeout(() => URL.revokeObjectURL(url), 1_000);
  }
}

function buildOfferDraftPlainText(draft: OpportunityOfferDraftResource): string {
  const lines: string[] = [];
  if (draft.banner) {
    lines.push(draft.banner, "");
  }
  if (draft.statement) {
    lines.push(draft.statement, "");
  }
  const meta = [draft.tender_ref, draft.lot_hint].filter(Boolean);
  if (meta.length) {
    lines.push(meta.join(" · "), "");
  }
  lines.push("Secciones", "---------");
  for (const sec of draft.sections || []) {
    lines.push("", sec.title || sec.key);
    if (sec.points_hint) lines.push(`Puntos: ${sec.points_hint}`);
    if (sec.requirement) lines.push(`Requisito (oficial): ${sec.requirement}`);
    if (sec.our_response_draft) {
      lines.push(`Respuesta (borrador declarado): ${sec.our_response_draft}`);
    }
    for (const gap of sec.gaps || []) lines.push(`Gap: ${gap}`);
  }
  if ((draft.gaps_summary || []).length) {
    lines.push("", "Gaps de solvencia / condiciones", "-------------------------------");
    for (const g of draft.gaps_summary || []) lines.push(`- ${g}`);
  }
  if ((draft.administrative_checklist || []).length) {
    lines.push("", "Checklist administrativa", "------------------------");
    for (const item of draft.administrative_checklist || []) {
      const status =
        item.status === "blocked" ? "bloqueado" : item.status === "ready" ? "listo" : "pendiente";
      lines.push(`[${status}] ${item.label}`);
      if (item.description) lines.push(`  ${item.description}`);
    }
  }
  lines.push(
    "",
    "Nota: este texto es un borrador declarado — no es hecho oficial ni documento presentable.",
    "",
  );
  return lines.join("\n");
}

export function DossierOpportunityAnalysisSection({ dossierId }: { dossierId: string }) {
  const [artifact, setArtifact] = useState<OpportunityAnalysisArtifact | null>(null);
  const [job, setJob] = useState<JobResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [running, setRunning] = useState(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [title, setTitle] = useState("");
  const [summary, setSummary] = useState("");
  const [createdId, setCreatedId] = useState<string | null>(null);
  const [showDraftOffer, setShowDraftOffer] = useState(false);
  const [persistedDraft, setPersistedDraft] = useState<OpportunityOfferDraftResource | null>(
    null,
  );
  const [draftStatement, setDraftStatement] = useState("");
  const [draftSections, setDraftSections] = useState<OpportunityOfferDraftSection[]>([]);
  const [draftSaveState, setDraftSaveState] = useState<DraftSaveState>("idle");
  const [draftError, setDraftError] = useState<string | null>(null);
  const [draftBusy, setDraftBusy] = useState(false);
  const [copyStatus, setCopyStatus] = useState<"idle" | "ok" | "error">("idle");
  const [exportState, setExportState] = useState<DraftExportState>("idle");
  const [exportError, setExportError] = useState<string | null>(null);
  const draftVersionRef = useRef<number>(0);
  /** Local unsaved edits must not be clobbered by automatic refresh/rerun. */
  const draftDirtyRef = useRef(false);

  const output = artifact?.output ?? null;
  const facts = useMemo(() => groundedFacts(output), [output]);
  const inferences = useMemo(() => groundedInferences(output), [output]);
  const actors = useMemo(() => groundedActors(output), [output]);
  const hasGrounding = facts.length > 0;
  const canReview =
    Boolean(artifact) &&
    artifact?.status !== "valid" &&
    artifact?.status !== "rejected" &&
    !running &&
    hasGrounding;
  /** Durable surface is independent of fit/verdict; prepare seed only when no row yet. */
  const canPrepareFromSeed = Boolean(output?.draft_offer);
  const showDurableDraftSurface = Boolean(persistedDraft) || canPrepareFromSeed || showDraftOffer;

  const applyPersistedDraft = useCallback(
    (draft: OpportunityOfferDraftResource, opts?: { force?: boolean }) => {
      // Automatic reloads must not wipe dirty local edits.
      if (!opts?.force && draftDirtyRef.current) {
        return;
      }
      draftDirtyRef.current = false;
      setPersistedDraft(draft);
      setDraftStatement(draft.statement || "");
      setDraftSections(draft.sections || []);
      draftVersionRef.current = draft.version;
      setDraftSaveState("saved");
      setDraftError(null);
      setShowDraftOffer(true);
    },
    [],
  );

  const loadPersistedDraft = useCallback(async () => {
    try {
      const response = await api.dossierOpportunityAnalysis.getOfferDraft(dossierId);
      applyPersistedDraft(response.draft);
      return response.draft;
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 404) {
        // Keep local dirty edits even if server still has no row / transient 404.
        if (draftDirtyRef.current) {
          return null;
        }
        setPersistedDraft(null);
        setDraftStatement("");
        setDraftSections([]);
        draftVersionRef.current = 0;
        setDraftSaveState("idle");
        return null;
      }
      throw reason;
    }
  }, [applyPersistedDraft, dossierId]);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const latest = await api.dossierOpportunityAnalysis.latest(dossierId);
      setJob(latest.job);
      setArtifact(latest.artifact);
      const proposal = latest.artifact?.output;
      if (proposal) {
        setTitle(proposal.title || "");
        setSummary(proposal.summary || "");
      }
      const nonTerminal = latest.job && !terminal.has(latest.job.status);
      setRunning(Boolean(nonTerminal));
      try {
        await loadPersistedDraft();
      } catch {
        // Draft load is best-effort; analysis remains usable.
      }
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo cargar el análisis de oportunidad."));
    } finally {
      setLoading(false);
    }
  }, [dossierId, loadPersistedDraft]);

  async function prepareOfferDraft() {
    setDraftBusy(true);
    setDraftError(null);
    setCopyStatus("idle");
    try {
      const response = await api.dossierOpportunityAnalysis.prepareOfferDraft(dossierId);
      applyPersistedDraft(response.draft, { force: true });
      setShowDraftOffer(true);
      toast.success(
        response.created ? "Borrador de oferta creado" : "Borrador de oferta listo",
        {
          description: response.created
            ? "Copia editable materializada desde el esqueleto calculado."
            : "Se reabrió el borrador persistido (sin sobrescribir ediciones previas).",
        },
      );
    } catch (reason) {
      const message = errorMessage(
        reason,
        "No se pudo preparar el borrador de oferta.",
      );
      setDraftError(message);
      setDraftSaveState("error");
      toast.error("No se pudo preparar el borrador", { description: message });
    } finally {
      setDraftBusy(false);
    }
  }

  async function saveOfferDraft() {
    if (!persistedDraft) return;
    setDraftBusy(true);
    setDraftSaveState("saving");
    setDraftError(null);
    try {
      const response = await api.dossierOpportunityAnalysis.patchOfferDraft(
        dossierId,
        {
          version: draftVersionRef.current || persistedDraft.version,
          statement: draftStatement,
          sections: draftSections.map((sec) => ({
            key: sec.key,
            our_response_draft: sec.our_response_draft,
          })),
        },
        draftVersionRef.current || persistedDraft.version,
      );
      applyPersistedDraft(response.draft, { force: true });
      toast.success("Borrador guardado");
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) {
        draftDirtyRef.current = true;
        setDraftSaveState("conflict");
        setDraftError(
          reason.problem.detail ||
            "Conflicto de versión: otro guardado ha actualizado el borrador.",
        );
        toast.error("Conflicto al guardar", {
          description: "Recarga el borrador o resuelve el conflicto antes de continuar.",
        });
      } else {
        draftDirtyRef.current = true;
        const message = errorMessage(reason, "No se pudo guardar el borrador.");
        setDraftSaveState("error");
        setDraftError(message);
        toast.error("Error al guardar", { description: message });
      }
    } finally {
      setDraftBusy(false);
    }
  }

  async function copyOfferDraft() {
    const source = persistedDraft
      ? {
          ...persistedDraft,
          statement: draftStatement,
          sections: draftSections,
        }
      : null;
    if (!source) {
      setCopyStatus("error");
      toast.error("Nada que copiar", {
        description: "Prepara el borrador antes de copiarlo.",
      });
      return;
    }
    const plain = buildOfferDraftPlainText(source);
    try {
      if (!navigator.clipboard?.writeText) {
        throw new Error("Clipboard API no disponible");
      }
      await navigator.clipboard.writeText(plain);
      setCopyStatus("ok");
      toast.success("Borrador copiado al portapapeles");
    } catch {
      setCopyStatus("error");
      toast.error("No se pudo copiar", {
        description: "El navegador bloqueó el acceso al portapapeles.",
      });
    }
  }

  async function downloadOfferDraftDocx() {
    if (!persistedDraft) {
      setExportState("error");
      setExportError("No hay borrador persistido para descargar.");
      toast.error("Nada que descargar", {
        description: "Prepara y guarda el borrador antes de exportar a Word.",
      });
      return;
    }
    if (draftDirtyRef.current || draftSaveState === "dirty") {
      setExportState("dirty_blocked");
      setExportError("Guarda antes de exportar. Hay cambios locales sin guardar.");
      toast.error("Guarda antes de exportar", {
        description: "Los cambios locales no se incluyen hasta que guardes el borrador.",
      });
      return;
    }
    const version = draftVersionRef.current || persistedDraft.version;
    setExportState("preparing");
    setExportError(null);
    setDraftBusy(true);
    try {
      const download = await api.dossierOpportunityAnalysis.exportOfferDraftDocx(
        dossierId,
        version,
        { ifMatch: version },
      );
      const filename =
        download.filename && download.filename.toLowerCase().endsWith(".docx")
          ? download.filename
          : `Borrador-oferta-v${version}.docx`;
      triggerBlobDownload(download.blob, filename);
      setExportState("downloaded");
      toast.success("Word descargado", {
        description: filename,
      });
    } catch (reason) {
      if (reason instanceof ApiError && reason.status === 409) {
        setExportState("conflict");
        setExportError(
          reason.problem.detail ||
            "Conflicto de versión: el borrador en servidor no coincide con el de la pantalla.",
        );
        toast.error("Conflicto al exportar", {
          description: "Recarga el borrador y vuelve a intentar la descarga.",
        });
      } else {
        const message = errorMessage(reason, "No se pudo descargar el Word.");
        setExportState("error");
        setExportError(message);
        toast.error("Error al descargar Word", { description: message });
      }
    } finally {
      setDraftBusy(false);
    }
  }

  function markDraftDirty() {
    draftDirtyRef.current = true;
    setDraftSaveState((prev) => (prev === "saving" ? prev : "dirty"));
    setCopyStatus("idle");
    setExportState((prev) => (prev === "preparing" ? prev : "idle"));
    setExportError(null);
  }

  function renderDurableOfferDraftSurface() {
    if (!showDurableDraftSurface) {
      return null;
    }
    return (
      <div
        style={{ marginTop: "0.75rem" }}
        data-testid="dossier-opportunity-draft-durable-surface"
      >
        <h3>Borrador de oferta (persistente)</h3>
        <p className="muted" style={{ marginTop: 0 }}>
          Superficie durable independiente del último análisis. Las ediciones no se
          sobrescriben al regenerar la propuesta.
        </p>
        <div
          style={{ display: "flex", flexWrap: "wrap", gap: "0.5rem" }}
          data-testid="dossier-opportunity-draft-offer-actions"
        >
          <button
            type="button"
            data-testid="dossier-opportunity-prepare-draft-offer"
            className="btn-secondary"
            disabled={
              draftBusy ||
              (!persistedDraft && !canPrepareFromSeed)
            }
            onClick={() => {
              if (showDraftOffer && persistedDraft) {
                setShowDraftOffer(false);
                return;
              }
              if (persistedDraft) {
                setShowDraftOffer(true);
                return;
              }
              void prepareOfferDraft();
            }}
            style={{
              padding: "0.4rem 0.75rem",
              borderRadius: "6px",
              border: "1px solid var(--border, #ccc)",
              background: "var(--surface, #f7f7f7)",
              cursor: draftBusy ? "wait" : "pointer",
              fontWeight: 600,
            }}
          >
            {showDraftOffer && persistedDraft
              ? "Ocultar borrador de oferta"
              : persistedDraft
                ? "Mostrar borrador de oferta"
                : "Preparar borrador de oferta"}
          </button>
          {persistedDraft ? (
            <>
              <button
                type="button"
                data-testid="dossier-opportunity-save-draft-offer"
                className="btn-secondary"
                disabled={draftBusy || draftSaveState === "saving"}
                onClick={() => void saveOfferDraft()}
                style={{
                  padding: "0.4rem 0.75rem",
                  borderRadius: "6px",
                  border: "1px solid var(--border, #ccc)",
                  background: "var(--surface, #f7f7f7)",
                  cursor: draftBusy ? "wait" : "pointer",
                  fontWeight: 600,
                }}
              >
                Guardar borrador
              </button>
              <button
                type="button"
                data-testid="dossier-opportunity-copy-draft-offer"
                className="btn-secondary"
                disabled={draftBusy}
                onClick={() => void copyOfferDraft()}
                style={{
                  padding: "0.4rem 0.75rem",
                  borderRadius: "6px",
                  border: "1px solid var(--border, #ccc)",
                  background: "var(--surface, #f7f7f7)",
                  cursor: draftBusy ? "wait" : "pointer",
                  fontWeight: 600,
                }}
              >
                Copiar borrador
              </button>
              <button
                type="button"
                data-testid="dossier-opportunity-download-draft-docx"
                className="btn-secondary"
                disabled={draftBusy || exportState === "preparing"}
                aria-busy={exportState === "preparing"}
                onClick={() => void downloadOfferDraftDocx()}
                style={{
                  padding: "0.4rem 0.75rem",
                  borderRadius: "6px",
                  border: "1px solid var(--border, #ccc)",
                  background: "var(--surface, #f7f7f7)",
                  cursor: draftBusy || exportState === "preparing" ? "wait" : "pointer",
                  fontWeight: 600,
                }}
              >
                {exportState === "preparing"
                  ? "Preparando Word…"
                  : "Descargar Word (.docx)"}
              </button>
            </>
          ) : null}
        </div>
        {!canPrepareFromSeed && !persistedDraft ? (
          <small className="muted" style={{ display: "block", marginTop: "0.35rem" }}>
            El borrador se genera con el análisis cuando hay esqueleto calculado
            (draft_offer). Si no aparece, vuelve a ejecutar el análisis de oportunidad.
          </small>
        ) : (
          <small
            className="muted"
            style={{ display: "block", marginTop: "0.35rem" }}
            data-testid="dossier-opportunity-draft-save-status"
            aria-live="polite"
          >
            Estado: {draftStatusLabel(draftSaveState)}
            {persistedDraft ? ` · v${persistedDraft.version}` : ""}
            {copyStatus === "ok" ? " · Copiado" : ""}
            {copyStatus === "error" ? " · Error al copiar" : ""}
            {exportState !== "idle" && draftExportStatusLabel(exportState)
              ? ` · Export: ${draftExportStatusLabel(exportState)}`
              : ""}
          </small>
        )}
        {exportError ? (
          <p
            role="alert"
            data-testid="dossier-opportunity-draft-export-error"
            style={{
              margin: "0.4rem 0 0",
              color: "var(--danger-fg, #991b1b)",
              fontSize: "0.92em",
            }}
          >
            {exportError}
          </p>
        ) : null}
        {draftError ? (
          <p
            role="alert"
            data-testid="dossier-opportunity-draft-error"
            style={{
              margin: "0.4rem 0 0",
              color: "var(--danger-fg, #991b1b)",
              fontSize: "0.92em",
            }}
          >
            {draftError}
          </p>
        ) : null}

        {showDraftOffer && persistedDraft ? (
          <div
            className="opportunity-draft-offer"
            data-testid="dossier-opportunity-draft-offer"
            style={{
              marginTop: "0.85rem",
              padding: "0.75rem",
              border: "1px dashed var(--border, #c9a227)",
              borderRadius: "6px",
              background: "var(--surface-muted, #fffbeb)",
            }}
          >
            <p
              data-testid="dossier-opportunity-draft-banner"
              style={{
                margin: "0 0 0.5rem",
                fontWeight: 700,
                color: "var(--warning-fg, #92400e)",
              }}
            >
              {persistedDraft.banner}
            </p>
            <small
              className="muted"
              data-testid="dossier-opportunity-draft-human-gate"
            >
              Puerta humana:{" "}
              {persistedDraft.human_gate === "draft_requires_human_edit" ||
              !persistedDraft.human_gate
                ? "requiere edición humana (no es documento presentable)"
                : String(persistedDraft.human_gate)}
              {persistedDraft.tender_ref
                ? ` · ${persistedDraft.tender_ref}`
                : ""}
              {persistedDraft.lot_hint
                ? ` · ${persistedDraft.lot_hint}`
                : ""}
              {" · "}
              <span data-origin="declared_draft">origen: borrador declarado</span>
            </small>

            <label
              htmlFor="dossier-opportunity-draft-statement-input"
              style={{ display: "block", marginTop: "0.65rem", fontWeight: 600 }}
            >
              Introducción (editable)
            </label>
            <textarea
              id="dossier-opportunity-draft-statement-input"
              data-testid="dossier-opportunity-draft-statement"
              value={draftStatement}
              onChange={(event) => {
                markDraftDirty();
                setDraftStatement(event.target.value);
              }}
              onKeyDown={(event) => {
                if ((event.metaKey || event.ctrlKey) && event.key === "s") {
                  event.preventDefault();
                  void saveOfferDraft();
                }
              }}
              rows={3}
              style={{
                width: "100%",
                marginTop: "0.25rem",
                padding: "0.5rem",
                borderRadius: "6px",
                border: "1px solid var(--border, #ccc)",
                font: "inherit",
              }}
            />

            {draftSections.length > 0 ? (
              <div data-testid="dossier-opportunity-draft-sections">
                <h4 style={{ margin: "0.75rem 0 0.35rem" }}>
                  Secciones (criterios del pliego)
                </h4>
                <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
                  {draftSections.map((sec) => (
                    <li
                      key={sec.key}
                      data-testid={`dossier-opportunity-draft-section-${sec.key}`}
                      style={{
                        marginBottom: "0.65rem",
                        paddingBottom: "0.55rem",
                        borderBottom: "1px solid var(--border, #eee)",
                      }}
                    >
                      <strong
                        data-testid={`dossier-opportunity-draft-section-title-${sec.key}`}
                      >
                        {sec.title}
                      </strong>
                      {sec.points_hint ? (
                        <span className="muted"> · {sec.points_hint}</span>
                      ) : null}
                      <p
                        style={{ margin: "0.25rem 0 0", fontSize: "0.92em" }}
                        data-testid={`dossier-opportunity-draft-section-req-${sec.key}`}
                      >
                        <span className="muted" data-origin="official">
                          Requisito (oficial):{" "}
                        </span>
                        {sec.requirement}
                      </p>
                      <label
                        htmlFor={`dossier-opportunity-draft-section-input-${sec.key}`}
                        className="muted"
                        data-origin="declared_draft"
                        style={{
                          display: "block",
                          marginTop: "0.35rem",
                          fontSize: "0.92em",
                        }}
                      >
                        Respuesta (borrador declarado — no es hecho):
                      </label>
                      <textarea
                        id={`dossier-opportunity-draft-section-input-${sec.key}`}
                        data-testid={`dossier-opportunity-draft-section-seed-${sec.key}`}
                        value={sec.our_response_draft}
                        onChange={(event) =>
                          updateSectionResponse(sec.key, event.target.value)
                        }
                        onKeyDown={(event) => {
                          if ((event.metaKey || event.ctrlKey) && event.key === "s") {
                            event.preventDefault();
                            void saveOfferDraft();
                          }
                        }}
                        rows={3}
                        style={{
                          width: "100%",
                          marginTop: "0.2rem",
                          padding: "0.5rem",
                          borderRadius: "6px",
                          border: "1px solid var(--border, #ccc)",
                          font: "inherit",
                        }}
                      />
                      {(sec.gaps || []).length > 0 ? (
                        <ul
                          data-testid={`dossier-opportunity-draft-section-gaps-${sec.key}`}
                          style={{ margin: "0.25rem 0 0", paddingLeft: "1.1rem" }}
                        >
                          {(sec.gaps || []).map((g, idx) => (
                            <li key={`${sec.key}-gap-${idx}`}>
                              <small>Gap: {g}</small>
                            </li>
                          ))}
                        </ul>
                      ) : null}
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}

            {(persistedDraft.gaps_summary || []).length > 0 ? (
              <div data-testid="dossier-opportunity-draft-gaps">
                <h4 style={{ margin: "0.5rem 0 0.35rem" }}>
                  Gaps de solvencia / condiciones
                </h4>
                <ul>
                  {(persistedDraft.gaps_summary || []).map((g, idx) => (
                    <li key={`draft-gap-${idx}`}>{g}</li>
                  ))}
                </ul>
              </div>
            ) : null}

            {(persistedDraft.administrative_checklist || []).length > 0 ? (
              <div data-testid="dossier-opportunity-draft-checklist">
                <h4 style={{ margin: "0.5rem 0 0.35rem" }}>
                  Checklist administrativa
                </h4>
                <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
                  {(persistedDraft.administrative_checklist || []).map((item) => (
                    <li
                      key={item.key}
                      data-testid={`dossier-opportunity-draft-check-${item.key}`}
                      style={{ marginBottom: "0.35rem" }}
                    >
                      <strong>
                        [
                        {item.status === "blocked"
                          ? "bloqueado"
                          : item.status === "ready"
                            ? "listo"
                            : "pendiente"}
                        ]{" "}
                        {item.label}
                      </strong>
                      <div>
                        <small className="muted">{item.description}</small>
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            ) : null}
          </div>
        ) : null}
      </div>
    );
  }

  function updateSectionResponse(key: string, value: string) {
    markDraftDirty();
    setDraftSections((prev) =>
      prev.map((sec) => (sec.key === key ? { ...sec, our_response_draft: value } : sec)),
    );
  }

  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  async function runAnalysis() {
    setBusy(true);
    setError(null);
    setCreatedId(null);
    try {
      const response = await api.dossierOpportunityAnalysis.run(
        dossierId,
        idempotencyKey(dossierId),
      );
      setJob(response.job);
      if (response.artifact) {
        setArtifact(response.artifact);
        const proposal = response.artifact.output;
        setTitle(proposal.title || title);
        setSummary(proposal.summary || summary);
      }
      const nonTerminal = response.job && !terminal.has(response.job.status);
      setRunning(Boolean(nonTerminal));
      if (!nonTerminal && response.job?.status === "succeeded") {
        toast.success("Propuesta lista", {
          description: "Revísala y confirma antes de crear la oportunidad en el expediente.",
        });
        await load();
      } else if (nonTerminal) {
        toast.message("Análisis en curso", {
          description: "Oracle está evaluando la evidencia del expediente.",
        });
      }
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo lanzar el análisis de oportunidad."));
    } finally {
      setBusy(false);
    }
  }

  async function onJobTerminal(next: JobResponse) {
    setJob(next);
    setRunning(false);
    if (next.status === "succeeded") {
      try {
        const latest = await api.dossierOpportunityAnalysis.latest(dossierId);
        setArtifact(latest.artifact);
        setJob(latest.job);
        if (latest.artifact?.output) {
          setTitle(latest.artifact.output.title || title);
          setSummary(latest.artifact.output.summary || summary);
        }
      } catch (reason) {
        setError(errorMessage(reason, "No se pudo recuperar la propuesta."));
      }
    }
  }

  async function applyProposal(event: FormEvent) {
    event.preventDefault();
    if (!artifact || !output) return;
    const nextTitle = title.trim();
    if (!nextTitle) {
      setError("El título no puede estar vacío.");
      return;
    }
    if (!hasGrounding) {
      setError("Sin hechos con evidencia citada no se puede crear la oportunidad.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      const scores = output.scores;
      const nextAction =
        output.next_best_action?.action?.trim() ||
        "Validar la propuesta del análisis de oportunidad y vincular seguimiento.";
      // 1) Mutación de negocio solo por acción humana explícita.
      const created = await api.opportunities.create(dossierId, {
        title: nextTitle,
        description: summary.trim(),
        opportunity_type: output.opportunity_type || "other",
        status: "identified",
        next_action: nextAction,
        strategic_fit: scores?.strategic_fit ?? 50,
        urgency: scores?.urgency ?? 50,
        expected_value: scores?.expected_value ?? 50,
        actionability: scores?.actionability ?? 50,
        relationship_leverage: scores?.relationship_leverage ?? 50,
        timing: scores?.timing ?? 50,
        confidence: scores?.confidence ?? output.confidence ?? 50,
        execution_effort: scores?.execution_effort ?? 50,
        blocking_risk: scores?.blocking_risk ?? 50,
        due_date: output.deadline ?? null,
      });
      setCreatedId(created.id);
      // 2) Marca la revisión humana sobre el artefacto (auditoría).
      await api.dossierOpportunityAnalysis.review(artifact.id, {
        decision: "accepted",
        reason: "Propuesta de oportunidad creada en el expediente por el usuario.",
        override: {
          created_opportunity_id: created.id,
          applied_title: nextTitle,
          recommendation: output.recommendation,
          evidence_ids: facts.flatMap((fact) => fact.evidence_ids),
        },
      });
      toast.success("Oportunidad creada", {
        description: "Aparece en el panel de oportunidades de la portada del expediente.",
      });
      await load();
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo crear la oportunidad."));
    } finally {
      setBusy(false);
    }
  }

  async function rejectProposal() {
    if (!artifact) return;
    setBusy(true);
    setError(null);
    try {
      await api.dossierOpportunityAnalysis.review(artifact.id, {
        decision: "rejected",
        reason: "Propuesta de oportunidad descartada por el usuario.",
      });
      toast.message("Propuesta descartada", {
        description: "No se ha creado ninguna oportunidad.",
      });
      await load();
    } catch (reason) {
      setError(errorMessage(reason, "No se pudo descartar la propuesta."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <div
      className="dossier-page dossier-section-page"
      data-testid="dossier-opportunity-analysis-section"
    >
      <PageHeader
        eyebrow="Análisis"
        title="Análisis de oportunidad"
        description="Oracle propone una oportunidad a partir de la evidencia del expediente. Tú confirmas: sin tu acción no se crea ninguna fila de negocio. La propuesta solo se muestra si cita evidencia."
        actions={
          <div className="page-header-actions">
            <Link className="vector-secondary" href={`/app/dossiers/${dossierId}/opportunities`}>
              Oportunidades
            </Link>
            <PermissionGate permission="ai.execute">
              <AsyncActionButton
                className="vector-primary"
                loading={busy || running}
                disabled={running}
                onClick={() => void runAnalysis()}
                data-testid="dossier-opportunity-run"
              >
                <Sparkles size={15} aria-hidden="true" />
                {artifact ? "Regenerar propuesta" : "Analizar oportunidad"}
              </AsyncActionButton>
            </PermissionGate>
            <AsyncActionButton
              className="vector-secondary"
              loading={loading}
              onClick={() => void load()}
              data-testid="dossier-opportunity-refresh"
            >
              <RefreshCw size={15} aria-hidden="true" />
              Actualizar
            </AsyncActionButton>
          </div>
        }
      />

      {error ? (
        <p className="form-error" role="alert" data-testid="dossier-opportunity-error">
          {error}
        </p>
      ) : null}

      {createdId ? (
        <p role="status" data-testid="dossier-opportunity-created">
          Oportunidad creada:{" "}
          <Link href={`/app/dossiers/${dossierId}`}>{createdId}</Link> · visible en el panel de
          la portada.
        </p>
      ) : null}

      {job && running ? (
        <JobProgress
          jobId={job.id}
          label="Analizando oportunidad con evidencia del expediente"
          onTerminal={(next) => void onJobTerminal(next)}
        />
      ) : null}

      {loading && !artifact && !persistedDraft ? (
        <p role="status">Cargando…</p>
      ) : !artifact ? (
        <>
          <section className="vector-panel" data-testid="dossier-opportunity-empty">
            <header className="panel-heading">
              <Target size={18} aria-hidden="true" />
              <div>
                <h2>Sin propuesta todavía</h2>
                <p>
                  Lanza el análisis cuando haya documentos o evidencias en el expediente. La
                  ejecución quedará en la auditoría de IA. Confirmar creará la oportunidad en el
                  panel de la portada.
                </p>
              </div>
            </header>
            {/* Persisted draft remains editable even without a current analysis artifact. */}
            {renderDurableOfferDraftSurface()}
          </section>
        </>
      ) : (
        <div className="dossier-summary-grid" data-testid="dossier-opportunity-proposal">
          <section className="vector-panel">
            <header className="panel-heading">
              <Sparkles size={18} aria-hidden="true" />
              <div>
                <span className="section-kicker">Propuesta del agente</span>
                <h2>Revisión humana obligatoria</h2>
                <p>
                  Estado del artefacto: <strong>{artifact.status}</strong>
                  {artifact.audit_log_id ? (
                    <>
                      {" "}
                      ·{" "}
                      <Link href="/app/admin/ai-audit" data-testid="dossier-opportunity-audit-link">
                        Ver en auditoría de IA
                      </Link>
                    </>
                  ) : null}
                </p>
              </div>
            </header>

            <dl className="detail-grid" data-testid="dossier-opportunity-meta">
              <div>
                <dt>Recomendación</dt>
                <dd data-testid="dossier-opportunity-recommendation">
                  {recommendationLabel(String(output?.recommendation ?? ""))}
                </dd>
              </div>
              <div>
                <dt>Tipo</dt>
                <dd>{output?.opportunity_type || "—"}</dd>
              </div>
              <div>
                <dt>Score global</dt>
                <dd>{output?.scores?.overall ?? "—"}</dd>
              </div>
              <div>
                <dt>Hechos con fuente</dt>
                <dd>{facts.length}</dd>
              </div>
            </dl>

            {!hasGrounding ? (
              <p className="form-error" role="status" data-testid="dossier-opportunity-no-grounding">
                La propuesta no cita hechos con evidencia. No se puede crear la oportunidad (misma
                regla que el Competidor Sintético).
              </p>
            ) : null}

            {Array.isArray(output?.warnings) && output.warnings.length > 0 ? (
              <ul className="warning-list" data-testid="dossier-opportunity-warnings">
                {output.warnings.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            ) : null}

            <PermissionGate permission="opportunity.write">
              <form
                className="dossier-settings-form"
                onSubmit={(event) => void applyProposal(event)}
                data-testid="dossier-opportunity-apply-form"
              >
                <label>
                  Título de la oportunidad
                  <input
                    value={title}
                    onChange={(event) => setTitle(event.target.value)}
                    maxLength={300}
                    required
                    data-testid="dossier-opportunity-title"
                  />
                </label>
                <label>
                  Resumen / descripción
                  <textarea
                    value={summary}
                    onChange={(event) => setSummary(event.target.value)}
                    rows={5}
                    maxLength={10000}
                    data-testid="dossier-opportunity-summary"
                  />
                </label>
                <div className="form-actions">
                  <AsyncActionButton
                    type="submit"
                    className="vector-primary"
                    loading={busy}
                    disabled={!canReview}
                    data-testid="dossier-opportunity-apply"
                  >
                    <CheckCircle2 size={15} aria-hidden="true" />
                    Confirmar y crear oportunidad
                  </AsyncActionButton>
                  <PermissionGate permission="ai.review">
                    <AsyncActionButton
                      type="button"
                      className="vector-secondary"
                      loading={busy}
                      disabled={
                        !artifact ||
                        artifact.status === "valid" ||
                        artifact.status === "rejected" ||
                        running
                      }
                      onClick={() => void rejectProposal()}
                      data-testid="dossier-opportunity-reject"
                    >
                      <XCircle size={15} aria-hidden="true" />
                      Descartar propuesta
                    </AsyncActionButton>
                  </PermissionGate>
                </div>
                <p className="muted">
                  Confirmar crea una oportunidad en el expediente (panel de la portada) y registra
                  la revisión humana. Descartar no crea filas de negocio.
                </p>
              </form>
            </PermissionGate>
          </section>

          <section className="vector-panel">
            <header className="panel-heading">
              <Link2 size={18} aria-hidden="true" />
              <div>
                <span className="section-kicker">Evidencias</span>
                <h2>Hechos e inferencias con fuente</h2>
                <p>
                  Sin evidencia citada no se muestra el hallazgo (misma regla que el Competidor
                  Sintético).
                </p>
              </div>
            </header>

            <h3>Hechos (fuente oficial / externa)</h3>
            {facts.length === 0 ? (
              <p data-testid="dossier-opportunity-no-facts">No hay hechos con evidencia citada.</p>
            ) : (
              <ul data-testid="dossier-opportunity-facts">
                {facts.map((fact) => (
                  <li key={`${fact.statement}-${fact.evidence_ids.join(",")}`}>
                    <p>{fact.statement}</p>
                    <small className="muted">
                      Evidencias oficiales: {fact.evidence_ids.length} ·{" "}
                      {fact.evidence_ids.slice(0, 3).join(", ")}
                      {fact.evidence_ids.length > 3 ? "…" : ""}
                    </small>
                  </li>
                ))}
              </ul>
            )}

            {output?.fit_assessment?.statement ? (
              <>
                <h3>Encaje perfil ↔ pliego (¿pujamos?)</h3>
                <div
                  className="opportunity-fit-assessment"
                  data-testid="dossier-opportunity-fit-assessment"
                >
                  {output.fit_assessment.verdict ? (
                    <div
                      className="opportunity-fit-verdict"
                      data-testid="dossier-opportunity-fit-verdict"
                      style={{
                        marginBottom: "0.75rem",
                        padding: "0.65rem 0.75rem",
                        border: "1px solid var(--border, #ccc)",
                        borderRadius: "6px",
                      }}
                    >
                      <p style={{ margin: 0, fontWeight: 600 }}>
                        Propuesta:{" "}
                        <span
                          className="badge opportunity-fit-verdict-badge"
                          data-testid="dossier-opportunity-fit-verdict-rec"
                          data-verdict={output.fit_assessment.verdict.recommendation}
                          style={{
                            display: "inline-block",
                            padding: "0.1rem 0.45rem",
                            borderRadius: "999px",
                            border: "1px solid var(--border, #ccc)",
                            fontSize: "0.85em",
                            letterSpacing: "0.02em",
                          }}
                        >
                          {output.fit_assessment.verdict.recommendation === "go"
                            ? "GO"
                            : output.fit_assessment.verdict.recommendation === "no_go"
                              ? "NO-GO"
                              : output.fit_assessment.verdict.recommendation ===
                                  "go_conditioned"
                                ? "GO CONDICIONADO"
                                : String(output.fit_assessment.verdict.recommendation)}
                        </span>
                      </p>
                      <small className="muted" data-testid="dossier-opportunity-fit-human-gate">
                        Puerta humana:{" "}
                        {output.fit_assessment.verdict.human_gate ===
                          "awaiting_user_confirmation" ||
                        !output.fit_assessment.verdict.human_gate
                          ? "pendiente de confirmación del usuario (no es decisión automática)"
                          : String(output.fit_assessment.verdict.human_gate)}
                      </small>
                      {output.fit_assessment.verdict.rationale ? (
                        <p
                          data-testid="dossier-opportunity-fit-verdict-rationale"
                          style={{ margin: "0.4rem 0 0" }}
                        >
                          {output.fit_assessment.verdict.rationale}
                        </p>
                      ) : null}
                      {(output.fit_assessment.verdict.conditions || []).length > 0 ? (
                        <ul data-testid="dossier-opportunity-fit-conditions">
                          {(output.fit_assessment.verdict.conditions || []).map((cond) => (
                            <li key={cond}>{cond}</li>
                          ))}
                        </ul>
                      ) : null}
                    </div>
                  ) : null}

                  {(output.fit_assessment.dimensions || []).length > 0 ? (
                    <div
                      className="opportunity-fit-dimensions"
                      data-testid="dossier-opportunity-fit-dimensions"
                      style={{ marginBottom: "0.75rem" }}
                    >
                      <p className="muted" style={{ marginBottom: "0.35rem" }}>
                        Dimensiones (requisito oficial vs capacidad declarada)
                        {output.fit_assessment.tender_ref
                          ? ` · ${output.fit_assessment.tender_ref}`
                          : ""}
                      </p>
                      <ul style={{ listStyle: "none", padding: 0, margin: 0 }}>
                        {(output.fit_assessment.dimensions || []).map((dim) => (
                          <li
                            key={`${dim.key}-${dim.label}`}
                            data-testid={`dossier-opportunity-fit-dim-${dim.key}`}
                            style={{
                              marginBottom: "0.55rem",
                              paddingBottom: "0.55rem",
                              borderBottom: "1px solid var(--border, #eee)",
                            }}
                          >
                            <strong>
                              {dim.label}{" "}
                              <span
                                className="muted"
                                data-testid={`dossier-opportunity-fit-dim-status-${dim.key}`}
                                data-status={dim.status}
                              >
                                [
                                {dim.status === "not_evaluable"
                                  ? "no evaluable con lo declarado"
                                  : dim.status === "no_fit"
                                    ? "no encaja"
                                    : dim.status === "partial"
                                      ? "parcial"
                                      : dim.status === "fit"
                                        ? "encaja"
                                        : dim.status}
                                ]
                              </span>
                            </strong>
                            <p
                              style={{ margin: "0.25rem 0 0", fontSize: "0.92em" }}
                              data-testid={`dossier-opportunity-fit-dim-req-${dim.key}`}
                            >
                              <span className="muted" data-origin="official">
                                Requisito (oficial):{" "}
                              </span>
                              {dim.requirement}
                            </p>
                            <p
                              style={{ margin: "0.15rem 0 0", fontSize: "0.92em" }}
                              data-testid={`dossier-opportunity-fit-dim-cap-${dim.key}`}
                            >
                              <span className="muted" data-origin="declared">
                                Capacidad (declarado):{" "}
                              </span>
                              {dim.capability}
                            </p>
                            <small
                              className="muted"
                              data-testid={`dossier-opportunity-fit-dim-reason-${dim.key}`}
                            >
                              {dim.status_reason}
                            </small>
                          </li>
                        ))}
                      </ul>
                    </div>
                  ) : null}

                  <p data-testid="dossier-opportunity-fit-statement">
                    {renderInlineEmphasis(output.fit_assessment.statement)}
                  </p>
                  <small className="muted" data-testid="dossier-opportunity-fit-origin">
                    Origen:{" "}
                    {output.fit_assessment.origin === "declared_by_client" ||
                    !output.fit_assessment.origin
                      ? "Declarado por el cliente (perfil del expediente)"
                      : String(output.fit_assessment.origin)}
                    {" · "}
                    IDs declarados:{" "}
                    {(output.fit_assessment.declared_evidence_ids || []).length}
                    {(output.fit_assessment.official_evidence_ids || []).length > 0
                      ? ` · IDs oficiales enlazados: ${
                          output.fit_assessment.official_evidence_ids?.length ?? 0
                        }`
                      : ""}
                    {" · "}
                    Confianza {output.fit_assessment.confidence ?? "—"}%
                  </small>
                </div>
              </>
            ) : null}

            {/* Durable draft is independent of fit/verdict presence. */}
            {renderDurableOfferDraftSurface()}

            <h3>Inferencias con fuente</h3>
            {inferences.length === 0 ? (
              <p data-testid="dossier-opportunity-no-inferences">
                No hay inferencias con evidencia citada.
              </p>
            ) : (
              <ul data-testid="dossier-opportunity-inferences">
                {inferences.map((item) => (
                  <li key={`${item.statement}-${item.confidence}`}>
                    <p>{item.statement}</p>
                    <small className="muted">
                      Confianza {item.confidence}% · {item.reasoning_summary}
                    </small>
                  </li>
                ))}
              </ul>
            )}

            {actors.length > 0 ? (
              <>
                <h3>Actores candidatos con fuente</h3>
                <ul data-testid="dossier-opportunity-actors">
                  {actors.map((actor) => (
                    <li key={`${actor.name}-${actor.role}`}>
                      <strong>{actor.name}</strong>
                      <span className="muted"> · {actor.role}</span>
                    </li>
                  ))}
                </ul>
              </>
            ) : null}

            {output?.next_best_action?.action ? (
              <>
                <h3>Siguiente mejor acción</h3>
                <p data-testid="dossier-opportunity-nba">
                  <strong>{output.next_best_action.action}</strong>
                  <span className="muted"> · {output.next_best_action.owner_role}</span>
                </p>
                <p className="muted">{output.next_best_action.rationale}</p>
              </>
            ) : null}

            {Array.isArray(output?.open_questions) && output.open_questions.length > 0 ? (
              <>
                <h3>Preguntas abiertas</h3>
                <ul data-testid="dossier-opportunity-questions">
                  {output.open_questions.map((question) => (
                    <li key={question}>{question}</li>
                  ))}
                </ul>
              </>
            ) : null}
          </section>
        </div>
      )}
    </div>
  );
}
