"use client";

import * as Dialog from "@radix-ui/react-dialog";
import {
  ApiError,
  api,
  type DossierResourcePage,
  type DossierSignalEnvelope,
  type OracleEvidence,
  type OracleOpportunity,
  type OracleRisk,
} from "@oracle/api-client";
import {
  ArrowRight,
  CheckCircle2,
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Filter,
  Plus,
  RefreshCw,
  Search,
  ShieldAlert,
  Sparkles,
  X,
  XCircle,
} from "lucide-react";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { PermissionGate } from "@/components/auth/auth-boundary";
import { usePathname, useRouter, useSearchParams } from "next/navigation";
import { productScoreDetailLabel, productSignalTypeLabel } from "@/lib/product-copy";

export type IntelligenceSectionKind = "signals" | "opportunities" | "risks";
type ScoredResource = OracleOpportunity | OracleRisk;
type SelectedItem = DossierSignalEnvelope | ScoredResource;

const STATUS_LABELS: Record<string, string> = {
  new: "Nueva",
  reviewed: "Revisada",
  dismissed: "Descartada",
  promoted: "Promovida",
  identified: "Identificada",
  qualified: "Cualificada",
  pursuing: "En curso",
  won: "Ganada",
  lost: "Perdida",
  open: "Abierto",
  monitoring: "En vigilancia",
  mitigated: "Mitigado",
  accepted: "Aceptado",
  closed: "Cerrado",
};

const OPPORTUNITY_TRANSITIONS: Record<string, string[]> = {
  identified: ["qualified", "dismissed"],
  qualified: ["pursuing", "dismissed"],
  pursuing: ["won", "lost", "dismissed"],
};

const RISK_TRANSITIONS: Record<string, string[]> = {
  open: ["monitoring", "mitigated", "accepted", "closed"],
  monitoring: ["mitigated", "accepted", "closed"],
  mitigated: ["monitoring", "closed"],
  accepted: ["monitoring", "closed"],
};

const SECTION_COPY = {
  signals: {
    eyebrow: "Radar del expediente",
    title: "Señales",
    description:
      "Prioriza, revisa y convierte señales trazables en trabajo estratégico.",
    permission: "signal.review",
  },
  opportunities: {
    eyebrow: "Avance ofensivo",
    title: "Oportunidades",
    description:
      "Valora oportunidades con una puntuación explicada y fuentes verificables.",
    permission: "opportunity.write",
  },
  risks: {
    eyebrow: "Protección del avance",
    title: "Riesgos",
    description:
      "Sigue los problemas que pueden frenar el avance y cómo se están gestionando.",
    permission: "risk.write",
  },
} as const;

const STATUS_OPTIONS: Record<IntelligenceSectionKind, string[]> = {
  signals: ["new", "reviewed", "promoted", "dismissed"],
  opportunities: [
    "identified",
    "qualified",
    "pursuing",
    "won",
    "lost",
    "dismissed",
  ],
  risks: ["open", "monitoring", "mitigated", "accepted", "closed"],
};

function isSignal(item: SelectedItem): item is DossierSignalEnvelope {
  return "link" in item && "signal" in item;
}

function score(item: SelectedItem): number {
  return Number(isSignal(item) ? item.link.overall_score : item.overall_score) || 0;
}

function title(item: SelectedItem): string {
  return (isSignal(item) ? item.signal.title : item.title) || "Sin título";
}

function status(item: SelectedItem): string {
  return (isSignal(item) ? item.link.status : item.status) || "sin_estado";
}

function confidence(item: SelectedItem): number | null {
  if (isSignal(item)) return Number(item.link.confidence) || 0;
  const value = item.score_details?.confidence;
  return typeof value === "number" ? value : null;
}

function apiErrorMessage(reason: unknown, fallback: string): string {
  return reason instanceof ApiError ? reason.problem.detail : fallback;
}

function formatDate(value?: string | null): string {
  if (!value) return "Sin fecha registrada";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "Sin fecha registrada";
  return new Intl.DateTimeFormat("es-ES", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function safeSourceUrl(value?: string | null): string | null {
  if (!value) return null;
  try {
    const parsed = new URL(value);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : null;
  } catch {
    return null;
  }
}

function pageTotal(page?: DossierResourcePage<SelectedItem>["meta"]): number {
  return Number(page?.total) || 0;
}

export function DossierIntelligenceSection({
  dossierId,
  kind,
}: {
  dossierId: string;
  kind: IntelligenceSectionKind;
}) {
  const copy = SECTION_COPY[kind];
  const pathname = usePathname();
  const router = useRouter();
  const searchParams = useSearchParams();
  const selectedId = searchParams?.get("selected") ?? null;
  const [items, setItems] = useState<SelectedItem[]>([]);
  const [meta, setMeta] = useState<DossierResourcePage<SelectedItem>["meta"]>();
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [appliedQuery, setAppliedQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("");
  const [minimumScore, setMinimumScore] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<SelectedItem | null>(null);
  const [evidence, setEvidence] = useState<OracleEvidence[]>([]);
  const [evidenceLoading, setEvidenceLoading] = useState(false);
  const [busy, setBusy] = useState(false);
  const [mutationError, setMutationError] = useState<string | null>(null);
  const [confirmAction, setConfirmAction] = useState<
    "review" | "dismiss" | "transition" | null
  >(null);
  const [nextStatus, setNextStatus] = useState("");
  const [promotionOpen, setPromotionOpen] = useState(false);
  const [promotionKind, setPromotionKind] = useState<"opportunity" | "risk">(
    "opportunity",
  );
  const [promotionTitle, setPromotionTitle] = useState("");
  const [manualOpen, setManualOpen] = useState(false);
  const [manualTitle, setManualTitle] = useState("");
  const [manualDescription, setManualDescription] = useState("");
  const [manualResponse, setManualResponse] = useState("");
  const [manualPrimary, setManualPrimary] = useState(50);
  const [manualSecondary, setManualSecondary] = useState(50);
  const [manualConfidence, setManualConfidence] = useState(50);
  const [manualError, setManualError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const input = {
        page,
        size: 25 as const,
        status: statusFilter || undefined,
        search: appliedQuery || undefined,
        scoreMin: minimumScore ? Number(minimumScore) : undefined,
        selectedIds: selectedId ? [selectedId] : undefined,
      };
      const result =
        kind === "signals"
          ? await api.dossierSignals.list(dossierId, input)
          : kind === "opportunities"
            ? await api.opportunities.list(dossierId, input)
            : await api.risks.list(dossierId, input);
      setItems(result.data);
      setMeta(result.meta);
    } catch (reason) {
      setItems([]);
      setMeta(undefined);
      setError(
        apiErrorMessage(reason, `No se pudieron cargar ${copy.title.toLowerCase()}.`),
      );
    } finally {
      setLoading(false);
    }
  }, [appliedQuery, copy.title, dossierId, kind, minimumScore, page, selectedId, statusFilter]);

  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  const pageCount = Math.max(
    1,
    Math.ceil(pageTotal(meta as DossierResourcePage<SelectedItem>["meta"]) / 25),
  );
  const transitions = useMemo(() => {
    if (!selected || isSignal(selected)) return [];
    const map = kind === "opportunities" ? OPPORTUNITY_TRANSITIONS : RISK_TRANSITIONS;
    return map[status(selected)] ?? [];
  }, [kind, selected]);

  function closeDetail() {
    setSelected(null);
    if (selectedId) router.replace(pathname, { scroll: false });
  }

  const openDetail = useCallback(async (item: SelectedItem) => {
    setSelected(item);
    setEvidence([]);
    setMutationError(null);
    setNextStatus("");
    if (isSignal(item)) return;
    setEvidenceLoading(true);
    try {
      const result =
        kind === "opportunities"
          ? await api.opportunities.evidence(item.id)
          : await api.risks.evidence(item.id);
      setEvidence(result.data);
    } catch (reason) {
      setMutationError(
        apiErrorMessage(reason, "No se pudieron cargar las evidencias enlazadas."),
      );
    } finally {
      setEvidenceLoading(false);
    }
  }, [kind]);

  useEffect(() => {
    const currentSelectedId = selected
      ? isSignal(selected)
        ? selected.link.id
        : selected.id
      : null;
    if (!selectedId || currentSelectedId === selectedId) return;
    const match = items.find((item) => isSignal(item) ? item.link.id === selectedId : item.id === selectedId);
    if (!match) return;
    const kickoff = window.setTimeout(() => void openDetail(match), 0);
    return () => window.clearTimeout(kickoff);
  }, [items, openDetail, selected, selectedId]);

  function applyFilters(event: FormEvent) {
    event.preventDefault();
    setPage(1);
    setAppliedQuery(query.trim());
  }

  function resetFilters() {
    setQuery("");
    setAppliedQuery("");
    setStatusFilter("");
    setMinimumScore("");
    setPage(1);
  }

  async function performConfirmedAction() {
    if (!selected || !confirmAction) return;
    setBusy(true);
    setMutationError(null);
    try {
      if (isSignal(selected)) {
        const link = selected.link;
        await api.dossierSignals.review(link.id, {
          confidence: Number(link.confidence) || 0,
          novelty: Number(link.novelty) || 0,
          relevance: Number(link.relevance) || 0,
          strategic_impact: Number(link.strategic_impact) || 0,
          recommended_action: link.recommended_action,
          why_it_matters: link.why_it_matters,
          version: Number(link.triage_version) || 0,
          status: confirmAction === "dismiss" ? "dismissed" : "reviewed",
        });
        toast.success(
          confirmAction === "dismiss" ? "Señal descartada" : "Señal revisada",
        );
      } else {
        const version = Number(selected.version) || 0;
        if (!nextStatus) throw new Error("Selecciona un estado de destino.");
        if (kind === "opportunities") {
          await api.opportunities.update(
            selected.id,
            { status: nextStatus, version },
            version,
          );
        } else {
          await api.risks.update(
            selected.id,
            { status: nextStatus, version },
            version,
          );
        }
        toast.success("Estado actualizado", {
          description: `El recurso pasa a ${STATUS_LABELS[nextStatus] ?? nextStatus}.`,
        });
      }
      setConfirmAction(null);
      closeDetail();
      await load();
    } catch (reason) {
      setMutationError(apiErrorMessage(reason, "No se pudo completar la acción."));
    } finally {
      setBusy(false);
    }
  }

  async function promote(event: FormEvent) {
    event.preventDefault();
    if (!selected || !isSignal(selected)) return;
    setBusy(true);
    setMutationError(null);
    try {
      await api.dossierSignals.promote(
        selected.link.id,
        { kind: promotionKind, title: promotionTitle.trim() },
        typeof crypto !== "undefined" && "randomUUID" in crypto
          ? crypto.randomUUID()
          : `promotion-${selected.link.id}-${Date.now()}`,
      );
      toast.success(
        promotionKind === "opportunity"
          ? "Oportunidad creada"
          : "Riesgo creado",
        { description: "La señal conserva el vínculo y la trazabilidad." },
      );
      setPromotionOpen(false);
      closeDetail();
      setPromotionTitle("");
      await load();
    } catch (reason) {
      setMutationError(apiErrorMessage(reason, "No se pudo promover la señal."));
    } finally {
      setBusy(false);
    }
  }

  function resetManual() {
    setManualTitle("");
    setManualDescription("");
    setManualResponse("");
    setManualPrimary(50);
    setManualSecondary(50);
    setManualConfidence(50);
    setManualError(null);
  }

  async function createManual(event: FormEvent) {
    event.preventDefault();
    if (kind === "signals") return;
    setBusy(true);
    setManualError(null);
    try {
      if (kind === "opportunities") {
        await api.opportunities.create(dossierId, {
          title: manualTitle.trim(),
          description: manualDescription.trim(),
          opportunity_type: "custom",
          next_action: manualResponse.trim(),
          strategic_fit: manualPrimary,
          urgency: manualSecondary,
          expected_value: 50,
          actionability: 50,
          relationship_leverage: 50,
          timing: 50,
          confidence: manualConfidence,
          execution_effort: 50,
          blocking_risk: 50,
        });
        toast.success("Oportunidad creada");
      } else {
        await api.risks.create(dossierId, {
          title: manualTitle.trim(),
          description: manualDescription.trim(),
          category: "strategic",
          mitigation: manualResponse.trim(),
          impact: manualPrimary,
          likelihood: manualSecondary,
          velocity: 50,
          exposure: 50,
          uncertainty: 50,
          controllability: 50,
          confidence: manualConfidence,
        });
        toast.success("Riesgo creado");
      }
      setManualOpen(false);
      resetManual();
      await load();
    } catch (reason) {
      setManualError(apiErrorMessage(reason, "No se pudo crear el registro."));
    } finally {
      setBusy(false);
    }
  }

  return (
    <section className="intelligence-section" aria-labelledby={`${kind}-title`}>
      <header className="intelligence-heading">
        <div>
          <span className="section-kicker">{copy.eyebrow}</span>
          <h1 id={`${kind}-title`}>{copy.title}</h1>
          <p>{copy.description}</p>
        </div>
        <div className="intelligence-heading-actions">
          {kind !== "signals" && <PermissionGate permission={copy.permission}><button className="vector-primary" onClick={() => { resetManual(); setManualOpen(true); }}><Plus size={15} /> {kind === "opportunities" ? "Nueva oportunidad" : "Nuevo riesgo"}</button></PermissionGate>}
          <button className="vector-secondary" onClick={() => void load()} disabled={loading}>
            <RefreshCw size={15} aria-hidden="true" /> Actualizar
          </button>
        </div>
      </header>

      <div className="vector-panel intelligence-panel">
        <form className="intelligence-filters" onSubmit={applyFilters}>
          <label className="intelligence-search">
            <span className="sr-only">Buscar en {copy.title.toLowerCase()}</span>
            <Search size={15} aria-hidden="true" />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={`Buscar ${copy.title.toLowerCase()}…`}
            />
          </label>
          <label>
            <span>Estado</span>
            <select
              value={statusFilter}
              onChange={(event) => {
                setStatusFilter(event.target.value);
                setPage(1);
              }}
            >
              <option value="">Todos</option>
              {STATUS_OPTIONS[kind].map((value) => (
                <option key={value} value={value}>
                  {STATUS_LABELS[value] ?? value}
                </option>
              ))}
            </select>
          </label>
          <label>
            <span>Puntuación mínima</span>
            <select
              value={minimumScore}
              onChange={(event) => {
                setMinimumScore(event.target.value);
                setPage(1);
              }}
            >
              <option value="">Cualquiera</option>
              <option value="50">50</option>
              <option value="70">70</option>
              <option value="85">85</option>
            </select>
          </label>
          <button className="vector-primary" type="submit">
            <Filter size={15} aria-hidden="true" /> Aplicar
          </button>
          {(appliedQuery || statusFilter || minimumScore) && (
            <button className="text-button" type="button" onClick={resetFilters}>
              Limpiar
            </button>
          )}
        </form>

        {loading ? (
          <div className="intelligence-loading" role="status">
            <span className="auth-spinner" /> Cargando información…
          </div>
        ) : error ? (
          <div className="intelligence-state" role="alert">
            <ShieldAlert size={24} aria-hidden="true" />
            <h2>No se puede mostrar esta sección</h2>
            <p>{error}</p>
            <button className="vector-secondary" onClick={() => void load()}>
              Reintentar
            </button>
          </div>
        ) : items.length === 0 ? (
          <div className="intelligence-state">
            <CheckCircle2 size={24} aria-hidden="true" />
            <h2>No hay resultados</h2>
            <p>
              {appliedQuery || statusFilter || minimumScore
                ? "Prueba a retirar algún filtro."
                : `El expediente todavía no contiene ${copy.title.toLowerCase()}.`}
            </p>
          </div>
        ) : (
          <>
            <div className="intelligence-table-wrap">
              <table className="intelligence-table">
                <thead>
                  <tr>
                    <th scope="col">{kind === "signals" ? "Señal y fuente" : "Recurso"}</th>
                    <th scope="col">Estado</th>
                    <th scope="col">Puntuación</th>
                    <th scope="col">Confianza</th>
                    <th scope="col">Actualización</th>
                    <th scope="col"><span className="sr-only">Acciones</span></th>
                  </tr>
                </thead>
                <tbody>
                  {items.map((item) => (
                    <tr key={isSignal(item) ? item.link.id : item.id}>
                      <td>
                        <strong>{title(item)}</strong>
                        <small>
                          {isSignal(item)
                            ? item.signal.source_name || item.signal.provider || "Fuente sin identificar"
                            : "Valor orientativo según la información disponible"}
                        </small>
                      </td>
                      <td><span className={`intelligence-status status-${status(item)}`}>{STATUS_LABELS[status(item)] ?? status(item)}</span></td>
                      <td><strong className="intelligence-score">{Math.round(score(item))}</strong></td>
                      <td>{confidence(item) === null ? "—" : `${Math.round(confidence(item) ?? 0)} %`}</td>
                      <td>{formatDate(isSignal(item) ? item.link.updated_at : item.updated_at)}</td>
                      <td>
                        <button className="text-button" onClick={() => void openDetail(item)} aria-label={`Inspeccionar ${title(item)}`}>
                          Inspeccionar <ArrowRight size={14} aria-hidden="true" />
                        </button>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
            <div className="intelligence-mobile-list">
              {items.map((item) => (
                <article key={isSignal(item) ? item.link.id : item.id}>
                  <header>
                    <span className={`intelligence-status status-${status(item)}`}>{STATUS_LABELS[status(item)] ?? status(item)}</span>
                    <strong className="intelligence-score">{Math.round(score(item))}</strong>
                  </header>
                  <h2>{title(item)}</h2>
                  <p>Confianza {confidence(item) === null ? "no disponible" : `${Math.round(confidence(item) ?? 0)} %`}</p>
                  <button className="vector-secondary" onClick={() => void openDetail(item)}>
                    Inspeccionar
                  </button>
                </article>
              ))}
            </div>
          </>
        )}

        {!loading && !error && pageTotal(meta as DossierResourcePage<SelectedItem>["meta"]) > 0 && (
          <footer className="intelligence-pagination">
            <p>{pageTotal(meta as DossierResourcePage<SelectedItem>["meta"])} resultados · página {page} de {pageCount}</p>
            <div>
              <button className="icon-button bordered" aria-label="Página anterior" disabled={page <= 1} onClick={() => setPage((value) => Math.max(1, value - 1))}>
                <ChevronLeft size={16} />
              </button>
              <button className="icon-button bordered" aria-label="Página siguiente" disabled={page >= pageCount} onClick={() => setPage((value) => value + 1)}>
                <ChevronRight size={16} />
              </button>
            </div>
          </footer>
        )}
      </div>

      <Dialog.Root open={manualOpen} onOpenChange={(open) => { setManualOpen(open); if (!open) resetManual(); }}>
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content className="dialog-content work-dialog intelligence-manual-dialog">
            <div className="dialog-header"><div><span className="section-kicker">Registro manual</span><Dialog.Title>{kind === "opportunities" ? "Nueva oportunidad" : "Nuevo riesgo"}</Dialog.Title><Dialog.Description>Registra una valoración humana inicial. Podrás enlazar evidencias y actores después.</Dialog.Description></div><Dialog.Close className="icon-button" aria-label="Cerrar"><X /></Dialog.Close></div>
            <form onSubmit={createManual}>
              <label>Título<input required minLength={3} maxLength={300} value={manualTitle} onChange={(event) => setManualTitle(event.target.value)} autoFocus /></label>
              <label>Descripción<textarea value={manualDescription} onChange={(event) => setManualDescription(event.target.value)} /></label>
              <div className="manual-score-grid">
                <label>{kind === "opportunities" ? "Encaje estratégico" : "Impacto"}<output>{manualPrimary}</output><input type="range" min="0" max="100" value={manualPrimary} onChange={(event) => setManualPrimary(Number(event.target.value))} /></label>
                <label>{kind === "opportunities" ? "Urgencia" : "Probabilidad"}<output>{manualSecondary}</output><input type="range" min="0" max="100" value={manualSecondary} onChange={(event) => setManualSecondary(Number(event.target.value))} /></label>
                <label>Confianza inicial<output>{manualConfidence}</output><input type="range" min="0" max="100" value={manualConfidence} onChange={(event) => setManualConfidence(Number(event.target.value))} /></label>
              </div>
              <label>{kind === "opportunities" ? "Siguiente acción" : "Mitigación inicial"}<textarea value={manualResponse} onChange={(event) => setManualResponse(event.target.value)} /></label>
              {manualError && <p className="form-error" role="alert">{manualError}</p>}
              <div className="dialog-actions"><Dialog.Close className="vector-secondary" type="button">Cancelar</Dialog.Close><button className="vector-primary" disabled={busy || manualTitle.trim().length < 3}>{busy ? "Guardando…" : "Crear"}</button></div>
            </form>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      <Dialog.Root open={Boolean(selected)} onOpenChange={(open) => !open && closeDetail()}>
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content className="dialog-content intelligence-drawer">
            {selected && (
              <>
                <header>
                  <div>
                    <span className="section-kicker">Detalle del elemento</span>
                    <Dialog.Title>{title(selected)}</Dialog.Title>
                    <Dialog.Description>
                      Resumen de lo observado, su valoración y las fuentes utilizadas.
                    </Dialog.Description>
                  </div>
                  <Dialog.Close className="dialog-close" aria-label="Cerrar detalle"><X size={18} /></Dialog.Close>
                </header>

                <div className="intelligence-drawer-body">
                  <dl className="intelligence-facts">
                    <div><dt>Estado</dt><dd>{STATUS_LABELS[status(selected)] ?? status(selected)}</dd></div>
                    <div><dt>Puntuación</dt><dd>{Math.round(score(selected))} / 100</dd></div>
                    <div><dt>Confianza</dt><dd>{confidence(selected) === null ? "No disponible" : `${Math.round(confidence(selected) ?? 0)} %`}</dd></div>
                    <div><dt>Actualización</dt><dd>{formatDate(isSignal(selected) ? selected.link.updated_at : selected.updated_at)}</dd></div>
                  </dl>

                  {isSignal(selected) ? (
                    <>
                      <section className="intelligence-detail-block">
                        <h2>Hecho observado</h2>
                        <p>{selected.signal.summary || "La fuente no aporta resumen normalizado."}</p>
                      </section>
                      <section className="intelligence-detail-block">
                        <h2>Por qué importa</h2>
                        <p>{selected.link.why_it_matters || "Pendiente de revisión humana."}</p>
                        {selected.link.recommended_action && <p><strong>Acción recomendada:</strong> {selected.link.recommended_action}</p>}
                      </section>
                      <section className="intelligence-detail-block evidence-block">
                        <h2>Fuente y evidencia</h2>
                        <p>{selected.signal.source_name || selected.signal.provider || "Fuente no identificada"}</p>
                        <p>{productSignalTypeLabel(selected.signal.source_type)} · {formatDate(selected.signal.published_at)}</p>
                        {safeSourceUrl(selected.signal.source_url) ? (
                          <a href={safeSourceUrl(selected.signal.source_url) ?? undefined} target="_blank" rel="noreferrer">
                            Abrir fuente original <ExternalLink size={13} aria-hidden="true" />
                          </a>
                        ) : <p>La señal no incluye una URL de origen.</p>}
                      </section>
                    </>
                  ) : (
                    <>
                      <ScoreExplanation resource={selected} kind={kind} />
                      <section className="intelligence-detail-block evidence-block">
                        <h2>Evidencias enlazadas</h2>
                        {evidenceLoading ? (
                          <p role="status">Cargando evidencias…</p>
                        ) : evidence.length === 0 ? (
                          <p>No hay evidencias enlazadas a este recurso.</p>
                        ) : (
                          <ul>
                            {evidence.map((item) => (
                              <li key={item.id}>
                                <p>{item.extract || "Evidencia sin extracto visible."}</p>
                                <small>{item.classification || "Sin clasificación"}</small>
                                {safeSourceUrl(item.source_url) && <a href={safeSourceUrl(item.source_url) ?? undefined} target="_blank" rel="noreferrer">Abrir fuente <ExternalLink size={12} /></a>}
                              </li>
                            ))}
                          </ul>
                        )}
                      </section>
                    </>
                  )}

                  {mutationError && <p className="form-error" role="alert">{mutationError}</p>}

                  <div className="intelligence-actions">
                    {isSignal(selected) ? (
                      <>
                        <PermissionGate permission="signal.review">
                          {status(selected) !== "promoted" && status(selected) !== "dismissed" && (
                            <button className="vector-secondary" onClick={() => setConfirmAction("review")} disabled={busy}>
                              <CheckCircle2 size={15} /> Marcar revisada
                            </button>
                          )}
                        </PermissionGate>
                        <PermissionGate permission="signal.promote">
                          {status(selected) === "reviewed" && (
                            <button className="vector-primary" onClick={() => { setPromotionTitle(selected.signal.title || ""); setPromotionOpen(true); }} disabled={busy}>
                              <Sparkles size={15} /> Promover
                            </button>
                          )}
                        </PermissionGate>
                        <PermissionGate permission="signal.review">
                          {status(selected) !== "promoted" && status(selected) !== "dismissed" && (
                            <button className="vector-danger" onClick={() => setConfirmAction("dismiss")} disabled={busy}>
                              <XCircle size={15} /> Descartar
                            </button>
                          )}
                        </PermissionGate>
                      </>
                    ) : (
                      <PermissionGate permission={copy.permission}>
                        {transitions.length > 0 ? (
                        <>
                          <label>
                            <span>Siguiente estado permitido</span>
                            <select value={nextStatus} onChange={(event) => setNextStatus(event.target.value)}>
                              <option value="">Seleccionar…</option>
                              {transitions.map((value) => <option key={value} value={value}>{STATUS_LABELS[value] ?? value}</option>)}
                            </select>
                          </label>
                          <button className="vector-primary" disabled={!nextStatus || busy} onClick={() => setConfirmAction("transition")}>
                            Actualizar estado
                          </button>
                        </>
                        ) : <p>Este recurso está en un estado terminal.</p>}
                      </PermissionGate>
                    )}
                  </div>
                </div>
              </>
            )}
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>

      <ConfirmationDialog
        open={Boolean(confirmAction)}
        busy={busy}
        title={confirmAction === "dismiss" ? "Descartar señal" : confirmAction === "transition" ? "Confirmar cambio de estado" : "Confirmar revisión"}
        description={
          confirmAction === "dismiss"
            ? "La señal dejará la bandeja activa, pero conservará su trazabilidad."
            : confirmAction === "transition"
              ? `El estado cambiará a ${STATUS_LABELS[nextStatus] ?? nextStatus}. La operación quedará auditada.`
              : "La señal quedará registrada como revisada por una persona."
        }
        destructive={confirmAction === "dismiss"}
        onCancel={() => setConfirmAction(null)}
        onConfirm={() => void performConfirmedAction()}
      />

      <Dialog.Root open={promotionOpen} onOpenChange={setPromotionOpen}>
        <Dialog.Portal>
          <Dialog.Overlay className="dialog-overlay" />
          <Dialog.Content className="dialog-content intelligence-action-dialog">
            <Dialog.Title>Promover señal</Dialog.Title>
            <Dialog.Description>
              Crea un recurso vinculado a la señal revisada. Oracle calculará su puntuación inicial.
            </Dialog.Description>
            <Dialog.Close className="dialog-close" aria-label="Cerrar"><X size={18} /></Dialog.Close>
            <form onSubmit={promote}>
              <label className="field">
                <span>Tipo de recurso</span>
                <select value={promotionKind} onChange={(event) => setPromotionKind(event.target.value as "opportunity" | "risk")}>
                  <option value="opportunity">Oportunidad</option>
                  <option value="risk">Riesgo</option>
                </select>
              </label>
              <label className="field">
                <span>Título</span>
                <input required minLength={2} maxLength={300} value={promotionTitle} onChange={(event) => setPromotionTitle(event.target.value)} autoFocus />
              </label>
              {mutationError && <p className="form-error" role="alert">{mutationError}</p>}
              <div className="dialog-actions">
                <Dialog.Close className="vector-secondary" type="button">Cancelar</Dialog.Close>
                <button className="vector-primary" disabled={busy || promotionTitle.trim().length < 2}>
                  {busy ? "Promoviendo…" : "Crear recurso"}
                </button>
              </div>
            </form>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </section>
  );
}

function ScoreExplanation({
  resource,
  kind,
}: {
  resource: ScoredResource;
  kind: IntelligenceSectionKind;
}) {
  const entries = Object.entries(resource.score_details ?? {}).filter(
    ([key, value]) => productScoreDetailLabel(key) && typeof value === "number",
  );
  return (
    <section className="intelligence-detail-block score-explanation">
      <h2>Explicación de la puntuación</h2>
      {entries.length === 0 ? (
        <p>Oracle todavía no dispone de un desglose explicativo para esta puntuación.</p>
      ) : (
        <dl>
          {entries.map(([key, value]) => (
            <div key={key}>
              <dt>{productScoreDetailLabel(key)}</dt>
              <dd>
                {typeof value === "number"
                  ? Math.round(value * 100) / 100
                  : typeof value === "string"
                    ? value
                    : ""}
              </dd>
            </div>
          ))}
        </dl>
      )}
      <p>
        {kind === "opportunities"
          ? "La puntuación orienta la cualificación; la decisión final sigue siendo humana."
          : "La puntuación ayuda a priorizar vigilancia y mitigación; no sustituye la evaluación humana."}
      </p>
    </section>
  );
}

function ConfirmationDialog({
  open,
  busy,
  title,
  description,
  destructive,
  onCancel,
  onConfirm,
}: {
  open: boolean;
  busy: boolean;
  title: string;
  description: string;
  destructive: boolean;
  onCancel(): void;
  onConfirm(): void;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={(next) => !next && onCancel()}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content intelligence-confirm-dialog">
          <Dialog.Title>{title}</Dialog.Title>
          <Dialog.Description>{description}</Dialog.Description>
          <div className="dialog-actions">
            <button className="vector-secondary" type="button" onClick={onCancel} disabled={busy}>Cancelar</button>
            <button className={destructive ? "vector-danger" : "vector-primary"} type="button" onClick={onConfirm} disabled={busy}>
              {busy ? "Guardando…" : "Confirmar"}
            </button>
          </div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
