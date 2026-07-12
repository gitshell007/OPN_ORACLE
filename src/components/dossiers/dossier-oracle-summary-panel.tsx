"use client";

import {
  ApiError,
  api,
  type OracleSummaryCurrent,
  type OracleSummaryVersion,
} from "@oracle/api-client";
import { AlertCircle, CheckCircle2, History, RefreshCw, Send, Sparkles } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";

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
  const fallbackUsed = current?.audit?.provider === "openrouter";
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
      toast.success("Feedback registrado");
    } catch (reason) {
      toast.error(message(reason, "No se pudo registrar el feedback."));
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
        <button className="vector-secondary" onClick={() => void refresh()} disabled={busy || jobRunning}>
          <RefreshCw size={15} /> {jobRunning ? "Actualizando" : "Actualizar análisis"}
        </button>
      </header>
      {loading ? (
        <p role="status">Cargando análisis del expediente...</p>
      ) : error ? (
        <p className="form-error" role="alert"><AlertCircle size={15} /> {error}</p>
      ) : !current ? (
        <div className="oracle-empty">
          <Sparkles size={18} />
          <strong>Aún no hay análisis publicado</strong>
          <p>Se generará con la información autorizada de este expediente y conservará citas trazables.</p>
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
              <div><dt>Cobertura</dt><dd>{output.evidence_coverage?.cited_items ?? 0}/{output.evidence_coverage?.available_items ?? 0}</dd></div>
              <div><dt>Actualizado</dt><dd>{formatDate(current.updated_at)}</dd></div>
            </dl>
          </div>
          {fallbackUsed && (
            <p className="oracle-warning"><AlertCircle size={15} /> Se usó proveedor secundario por indisponibilidad técnica del primario.</p>
          )}
          <div className="oracle-summary-grid">
            <Block title="Hechos confirmados" citations={citations} items={(output.facts ?? []).map((item) => ({ title: item.text ?? "", evidenceIds: item.evidence_ids }))} />
            <Block title="Cambios materiales" citations={citations} items={(output.material_changes ?? []).map((item) => ({ title: item.change ?? "", meta: levelLabel(item.importance), evidenceIds: item.evidence_ids }))} />
            <Block title="Oportunidades" citations={citations} items={(output.opportunities ?? []).map((item) => ({ title: item.title ?? "", meta: item.rationale ?? "" }))} />
            <Block title="Riesgos" citations={citations} items={(output.risks ?? []).map((item) => ({ title: item.title ?? "", meta: item.rationale ?? "" }))} />
            <Block title="Decisiones pendientes" citations={citations} items={(output.decisions_required ?? []).map((item) => ({ title: item.decision ?? "", meta: item.reason ?? "" }))} />
            <Block title="Siguientes acciones" citations={citations} items={(output.recommended_actions ?? []).map((item) => ({ title: item.action ?? "", meta: item.rationale ?? "" }))} />
          </div>
          <details className="oracle-history">
            <summary><History size={15} /> Historial de versiones ({versions.length})</summary>
            <ul>
              {versions.map((version) => (
                <li key={version.id}>
                  <span>v{version.version} · {formatDate(version.created_at)}</span>
                  <span>{asOutput(version).confidence ?? 0}% confianza</span>
                </li>
              ))}
            </ul>
          </details>
          <div className="oracle-feedback">
            <textarea
              aria-label="Feedback sobre el análisis"
              placeholder="Añade una corrección o matiz sobre este análisis"
              value={feedback}
              onChange={(event) => setFeedback(event.target.value)}
            />
            <button className="vector-secondary" onClick={() => void sendFeedback()} disabled={busy || !feedback.trim()}>
              <Send size={15} /> Enviar feedback
            </button>
          </div>
        </>
      )}
      {state?.job?.status === "failed" && (
        <p className="oracle-warning"><AlertCircle size={15} /> La última actualización falló; se conserva la versión anterior.</p>
      )}
    </section>
  );
}

function Block({
  title,
  items,
  citations,
}: {
  title: string;
  items: Array<{ title: string; meta?: string; evidenceIds?: string[] }>;
  citations: Map<string, SummaryCitation>;
}) {
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
