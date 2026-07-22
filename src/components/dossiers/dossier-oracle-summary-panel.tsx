"use client";

import {
  ApiError,
  api,
  type OracleSummaryCurrent,
  type OracleSummaryVersion,
} from "@oracle/api-client";
import { AlertCircle, CheckCircle2, FilePlus2, History, RefreshCw, Send, Sparkles } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { PermissionGate } from "@/components/auth/auth-boundary";
import { AsyncActionButton } from "@/components/ui/async-action-button";

type SummaryOutput = {
  headline?: string;
  executive_summary?: string;
  situation_status?: string;
  facts?: Array<{ text?: string; evidence_ids?: string[] }>;
  material_changes?: Array<{ change?: string; importance?: string; evidence_ids?: string[] }>;
  opportunities?: Array<{ title?: string; rationale?: string; urgency?: string }>;
  risks?: Array<{ title?: string; rationale?: string; severity?: string }>;
  decisions_required?: Array<{ decision?: string; reason?: string; urgency?: string }>;
  recommended_actions?: Array<{ action?: string; rationale?: string; priority?: string }>;
  confidence?: number;
  evidence_coverage?: { cited_items?: number; available_items?: number; limitations?: string[] };
  warnings?: string[];
};

type DraftKind = "task" | "opportunity" | "risk" | "actor" | "hypothesis" | "decision";

const DRAFT_LABELS: Record<DraftKind, string> = {
  task: "tarea",
  opportunity: "oportunidad",
  risk: "riesgo",
  actor: "actor",
  hypothesis: "hipótesis",
  decision: "decisión",
};

function message(reason: unknown, fallback: string): string {
  return reason instanceof ApiError ? reason.problem.detail : fallback;
}

function formatDate(value?: string | null): string {
  if (!value) return "Sin actualizar";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Sin actualizar";
  return new Intl.DateTimeFormat("es-ES", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

const LEVEL_LABELS: Record<string, string> = {
  low: "Baja",
  medium: "Media",
  high: "Alta",
  critical: "Crítica",
};

function levelLabel(value?: string): string {
  if (!value) return "Media";
  return LEVEL_LABELS[value.toLowerCase()] ?? value;
}

function asOutput(version?: OracleSummaryVersion | null): SummaryOutput {
  return (version?.output ?? {}) as SummaryOutput;
}

type SummaryCitation = NonNullable<OracleSummaryVersion["citations"]>[number];

function safeSourceUrl(value?: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    return url.protocol === "https:" || url.protocol === "http:" ? url.toString() : null;
  } catch {
    return null;
  }
}

export function DossierOracleSummaryPanel({ dossierId }: { dossierId: string }) {
  const [state, setState] = useState<OracleSummaryCurrent | null>(null);
  const [versions, setVersions] = useState<OracleSummaryVersion[]>([]);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [feedback, setFeedback] = useState("");
  const [pendingDraft, setPendingDraft] = useState<{
    kind: DraftKind;
    title: string;
    rationale: string;
  } | null>(null);

  const load = useCallback(async (silent = false) => {
    if (!silent) setLoading(true);
    setError(null);
    try {
      const [current, history] = await Promise.all([
        api.oracleSummary.get(dossierId),
        api.oracleSummary.versions(dossierId).catch(() => ({ data: [] })),
      ]);
      setState(current);
      setVersions(history.data ?? []);
    } catch (reason) {
      setError(message(reason, "No se pudo cargar el Oráculo del expediente."));
    } finally {
      if (!silent) setLoading(false);
    }
  }, [dossierId]);

  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  const current = state?.summary ?? null;
  const output = useMemo(() => asOutput(current), [current]);
  const citations = useMemo(
    () => new Map((current?.citations ?? []).map((citation) => [citation.id, citation])),
    [current],
  );
  const fallbackUsed =
    current?.audit?.provider === "ollama_titan" ||
    current?.audit?.model === "qwen3.6:27b" ||
    current?.audit?.provider === "openrouter";
  const jobRunning = Boolean(state?.job && ["queued", "running", "retrying"].includes(state.job.status));

  useEffect(() => {
    if (!jobRunning) return;
    const interval = window.setInterval(() => void load(true), 5000);
    return () => window.clearInterval(interval);
  }, [jobRunning, load]);

  async function refresh() {
    setBusy(true);
    try {
      await api.oracleSummary.refresh(dossierId, `oracle-summary-${dossierId}-${Date.now()}`);
      toast.success("Análisis en cola", {
        description: "El Oráculo se actualizará en segundo plano.",
      });
      await load();
    } catch (reason) {
      toast.error(message(reason, "No se pudo solicitar la actualización."));
    } finally {
      setBusy(false);
    }
  }

  async function sendFeedback() {
    if (!current || !feedback.trim()) return;
    setBusy(true);
    try {
      await api.oracleSummary.feedback(dossierId, current.id, {
        rating: 1,
        correction: {},
        comment: feedback.trim(),
      });
      setFeedback("");
      toast.success("Comentario registrado");
    } catch (reason) {
      toast.error(message(reason, "No se pudo registrar el comentario."));
    } finally {
      setBusy(false);
    }
  }

  async function createDraft() {
    if (!pendingDraft || !current) return;
    setBusy(true);
    const { kind, title, rationale } = pendingDraft;
    const provenance = {
      source: "oracle_recommendation",
      oracle_summary_id: current.id,
      oracle_summary_version: current.version ?? 1,
      requires_human_review: true,
    };
    const sourceNote = `Origen: recomendación del Oráculo, análisis v${provenance.oracle_summary_version} (${provenance.oracle_summary_id}).`;
    try {
      if (kind === "task") {
        await api.tasks.create(dossierId, {
          title,
          priority: "medium",
          status: "open",
          content: { rationale, ...provenance },
        });
      } else if (kind === "opportunity") {
        await api.opportunities.create(dossierId, {
          title,
          description: `${rationale}\n\n${sourceNote}`.trim(),
          status: "identified",
          confidence: 0,
          next_action: "Validar la recomendación del Oráculo y vincular evidencia.",
        });
      } else if (kind === "risk") {
        await api.risks.create(dossierId, {
          title,
          description: `${rationale}\n\n${sourceNote}`.trim(),
          status: "open",
          confidence: 0,
          mitigation: "Validar la recomendación del Oráculo y vincular evidencia.",
        });
      } else if (kind === "actor") {
        await api.actors.attach(dossierId, {
          canonical_name: title,
          actor_type: "organization",
          roles: ["Recomendación del Oráculo"],
          influence: 0,
          relevance_to_dossier: 50,
          provenance: { rationale, ...provenance },
        });
      } else if (kind === "hypothesis") {
        await api.hypotheses.create(dossierId, {
          statement: title,
          rationale: `${rationale}\n\n${sourceNote}`.trim(),
          status: "open",
          confidence: 0,
        });
      } else {
        await api.decisions.create(dossierId, {
          title,
          rationale,
          status: "proposed",
          content: provenance,
        });
      }
      toast.success(`Borrador de ${DRAFT_LABELS[kind]} creado`, {
        description: "Revísalo en el expediente antes de darlo por válido.",
      });
      setPendingDraft(null);
    } catch (reason) {
      toast.error(message(reason, `No se pudo crear el borrador de ${DRAFT_LABELS[kind]}.`));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="vector-panel oracle-summary-panel" aria-labelledby="oracle-summary-title">
      <header>
        <div>
          <span className="section-kicker">Análisis asistido</span>
          <h2 id="oracle-summary-title">Oráculo del expediente</h2>
        </div>
        <PermissionGate permission="ai.execute">
          <AsyncActionButton className="vector-secondary" onClick={() => void refresh()} disabled={jobRunning} loading={busy}>
            <RefreshCw size={15} /> {jobRunning ? "Actualizando" : "Actualizar análisis"}
          </AsyncActionButton>
        </PermissionGate>
      </header>
      {loading ? (
        <p role="status">Cargando análisis del expediente...</p>
      ) : error ? (
        <p className="form-error" role="alert"><AlertCircle size={15} /> {error}</p>
      ) : !current ? (
        <div className="oracle-empty">
          <Sparkles size={18} />
          <strong>{jobRunning ? "Preparando el primer análisis…" : "Aún no hay análisis publicado"}</strong>
          <p>El análisis se prepara automáticamente cada noche con la información autorizada. Si tienes permiso, también puedes solicitarlo ahora.</p>
        </div>
      ) : (
        <>
          <div className="oracle-summary-head">
            <div>
              <h3>{output.headline ?? "Situación del expediente"}</h3>
              <p>{output.executive_summary ?? "Resumen pendiente de completar."}</p>
            </div>
            <dl>
              <div><dt>Confianza</dt><dd>{output.confidence ?? 0}%</dd></div>
              <div><dt>Fuentes utilizadas</dt><dd>{output.evidence_coverage?.cited_items ?? 0}/{output.evidence_coverage?.available_items ?? 0}</dd></div>
              <div><dt>Generado</dt><dd>{formatDate(state?.last_refreshed_at ?? current.updated_at)}</dd></div>
            </dl>
          </div>
          <p className="reporting-hint">
            {state?.generation_trigger === "nightly"
              ? "Generación nocturna"
              : state?.generation_trigger === "manual"
                ? "Actualización manual"
                : "Origen de la versión anterior no registrado"}
          </p>
          {jobRunning && (
            <p className="oracle-warning"><RefreshCw size={15} /> Actualización en curso; la última versión seguirá visible hasta publicar la nueva.</p>
          )}
          {fallbackUsed && (
            <p className="oracle-warning"><AlertCircle size={15} /> Se usó proveedor secundario por indisponibilidad técnica del primario.</p>
          )}
          {(output.warnings ?? []).map((warning, index) => (
            <p className="oracle-warning oracle-output-warning" key={`${index}-${warning}`}>
              <AlertCircle size={15} /> {warning}
            </p>
          ))}
          <div className="oracle-summary-grid">
            <Block title="Hechos confirmados" citations={citations} items={(output.facts ?? []).map((item) => ({ title: item.text ?? "", evidenceIds: item.evidence_ids }))} />
            <Block title="Cambios materiales" citations={citations} items={(output.material_changes ?? []).map((item) => ({ title: item.change ?? "", meta: levelLabel(item.importance), evidenceIds: item.evidence_ids }))} />
            <Block title="Oportunidades" citations={citations} items={(output.opportunities ?? []).map((item) => ({ title: item.title ?? "", meta: item.rationale ?? "" }))} />
            <Block title="Riesgos" citations={citations} items={(output.risks ?? []).map((item) => ({ title: item.title ?? "", meta: item.rationale ?? "" }))} />
            <Block
              title="Decisiones pendientes"
              citations={citations}
              items={(output.decisions_required ?? []).map((item) => ({ title: item.decision ?? "", meta: item.reason ?? "" }))}
              allowedDraftKinds={["decision"]}
              onDraft={(item) => setPendingDraft({ kind: "decision", title: item.title, rationale: item.meta ?? "" })}
            />
            <Block
              title="Siguientes acciones"
              citations={citations}
              items={(output.recommended_actions ?? []).map((item) => ({ title: item.action ?? "", meta: item.rationale ?? "" }))}
              allowedDraftKinds={["task", "opportunity", "risk", "actor", "hypothesis", "decision"]}
              onDraft={(item, kind) => setPendingDraft({ kind, title: item.title, rationale: item.meta ?? "" })}
            />
          </div>
          <details className="oracle-history">
            <summary><History size={15} /> Historial de análisis ({versions.length})</summary>
            <ul>
              {versions.map((version) => (
                <li key={version.id}>
                  <span>Análisis {version.version} · {formatDate(version.created_at)}</span>
                  <span>{asOutput(version).confidence ?? 0}% confianza</span>
                </li>
              ))}
            </ul>
          </details>
          <div className="oracle-feedback">
            <textarea
              aria-label="Comentario sobre el análisis"
              placeholder="Añade una corrección o un matiz sobre este análisis"
              value={feedback}
              onChange={(event) => setFeedback(event.target.value)}
            />
            <AsyncActionButton className="vector-secondary" onClick={() => void sendFeedback()} disabled={!feedback.trim()} loading={busy}>
              <Send size={15} /> Enviar comentario
            </AsyncActionButton>
          </div>
        </>
      )}
      {state?.job?.status === "failed" && (
        <p className="oracle-warning"><AlertCircle size={15} /> La última actualización falló; se conserva la versión anterior.</p>
      )}
      {pendingDraft && (
        <div className="vector-dialog-backdrop" role="presentation">
          <div className="vector-dialog oracle-draft-confirm" role="dialog" aria-modal="true" aria-labelledby="oracle-draft-title">
            <span className="section-kicker">Confirmación humana</span>
            <h2 id="oracle-draft-title">Crear borrador de {DRAFT_LABELS[pendingDraft.kind]}</h2>
            <p><strong>{pendingDraft.title}</strong></p>
            {pendingDraft.rationale && <p>{pendingDraft.rationale}</p>}
            <p className="reporting-hint">Se guardará como propuesta pendiente de revisión; no se considerará un hecho ni una decisión aprobada.</p>
            <div className="vector-dialog-actions">
              <button className="vector-secondary" type="button" disabled={busy} onClick={() => setPendingDraft(null)}>Cancelar</button>
              <AsyncActionButton className="vector-primary" type="button" loading={busy} onClick={() => void createDraft()}>
                <FilePlus2 size={15} /> {busy ? "Creando…" : "Confirmar borrador"}
              </AsyncActionButton>
            </div>
          </div>
        </div>
      )}
    </section>
  );
}

function Block({
  title,
  items,
  citations,
  allowedDraftKinds,
  onDraft,
}: {
  title: string;
  items: Array<{ title: string; meta?: string; evidenceIds?: string[] }>;
  citations: Map<string, SummaryCitation>;
  allowedDraftKinds?: DraftKind[];
  onDraft?: (item: { title: string; meta?: string }, kind: DraftKind) => void;
}) {
  const [draftKinds, setDraftKinds] = useState<Record<number, DraftKind>>({});
  return (
    <article>
      <h3>{title}</h3>
      {items.length ? (
        <ul>
          {items.slice(0, 4).map((item, index) => (
            <li key={`${title}-${index}`}>
              <CheckCircle2 size={14} />
              <span>
                <strong>{item.title}</strong>
                {item.meta && <small>{item.meta}</small>}
                {item.evidenceIds && (
                  <small className="oracle-citations">
                    {item.evidenceIds.length ? item.evidenceIds.map((id, citationIndex) => {
                      const source = citations.get(id);
                      const href = safeSourceUrl(source?.source_url);
                      const label = `Fuente #${id.slice(0, 8)}`;
                      return href ? (
                        <a key={id} href={href} target="_blank" rel="noreferrer">
                          {label}{citationIndex < item.evidenceIds!.length - 1 ? ", " : ""}
                        </a>
                      ) : (
                        <span key={id}>{label}{citationIndex < item.evidenceIds!.length - 1 ? ", " : ""}</span>
                      );
                    }) : "Sin cita"}
                  </small>
                )}
                {onDraft && allowedDraftKinds?.length && (
                  <span className="oracle-draft-action">
                    {allowedDraftKinds.length > 1 && (
                      <select
                        aria-label={`Tipo de borrador para ${item.title}`}
                        value={draftKinds[index] ?? allowedDraftKinds[0]}
                        onChange={(event) => setDraftKinds((current) => ({
                          ...current,
                          [index]: event.target.value as DraftKind,
                        }))}
                      >
                        {allowedDraftKinds.map((kind) => <option value={kind} key={kind}>{DRAFT_LABELS[kind]}</option>)}
                      </select>
                    )}
                    <button
                      className="vector-tertiary"
                      type="button"
                      onClick={() => onDraft(item, draftKinds[index] ?? allowedDraftKinds[0])}
                    >
                      <FilePlus2 size={13} /> Crear borrador{allowedDraftKinds.length === 1 ? ` de ${DRAFT_LABELS[allowedDraftKinds[0]]}` : ""}
                    </button>
                  </span>
                )}
              </span>
            </li>
          ))}
        </ul>
      ) : (
        <p>No hay elementos citables suficientes.</p>
      )}
    </article>
  );
}
