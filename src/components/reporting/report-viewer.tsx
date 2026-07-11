"use client";

import * as Dialog from "@radix-ui/react-dialog";
import { ApiError, api, type OracleReport } from "@oracle/api-client";
import {
  AlertTriangle,
  CheckCircle2,
  Download,
  FileCheck2,
  FileClock,
  RefreshCw,
  Send,
  X,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { PermissionGate } from "@/components/auth/auth-boundary";
import { JobProgress } from "./job-progress";
import {
  formatBytes,
  formatDateTime,
  idempotencyKey,
  reportContent,
  reportEvidence,
  reportRevisionId,
  reportStatusLabel,
  triggerDownload,
  type ReportEvidenceView,
} from "./reporting-utils";

function record(value: unknown): Record<string, unknown> | null {
  return value !== null && typeof value === "object" && !Array.isArray(value)
    ? (value as Record<string, unknown>)
    : null;
}

function claimLabel(kind: string): string {
  return {
    fact: "Hecho",
    inference: "Inferencia",
    recommendation: "Recomendación",
    decision: "Decisión",
  }[kind] ?? kind;
}

export function ReportViewer({
  reportId,
  routeBase = "/app",
  embedded = false,
}: {
  reportId: string;
  routeBase?: "/app" | "/concept-a";
  embedded?: boolean;
}) {
  const [report, setReport] = useState<OracleReport | null>(null);
  const [selectedEvidence, setSelectedEvidence] =
    useState<ReportEvidenceView | null>(null);
  const [decision, setDecision] = useState<
    "approved" | "changes_requested" | "comment"
  >("approved");
  const [comment, setComment] = useState("");
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setError(null);
    try {
      setReport(await api.reports.get(reportId));
    } catch (reason) {
      setError(
        reason instanceof ApiError && reason.status === 404
          ? "El informe no existe o no está disponible en tu ámbito."
          : "No se pudo cargar el informe.",
      );
    } finally {
      setLoading(false);
    }
  }, [reportId]);

  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  const content = useMemo(() => (report ? reportContent(report) : null), [report]);
  const evidence = useMemo(() => (report ? reportEvidence(report) : []), [report]);
  const evidenceById = useMemo(
    () => new Map(evidence.map((item) => [item.id, item])),
    [evidence],
  );
  const revisionId = report ? reportRevisionId(report) : null;

  async function retry() {
    if (!report) return;
    setBusy(true);
    try {
      const result = await api.reports.retry(
        report.id,
        idempotencyKey(`report-retry-${report.id}`),
      );
      setReport(result.report);
      toast.success("Nueva generación en cola");
    } catch (reason) {
      toast.error("No se pudo reintentar", {
        description:
          reason instanceof ApiError
            ? reason.problem.detail
            : "Actualiza el informe y vuelve a intentarlo.",
      });
    } finally {
      setBusy(false);
    }
  }

  async function review(event: FormEvent) {
    event.preventDefault();
    if (!report || !revisionId) return;
    setBusy(true);
    try {
      const result = await api.reports.review(report.id, {
        revision_id: revisionId,
        version: report.version,
        decision,
        comment: comment.trim(),
      });
      setReport(result.report);
      setComment("");
      toast.success(
        decision === "approved" ? "Informe aprobado" : "Revisión registrada",
      );
    } catch (reason) {
      toast.error("No se pudo registrar la revisión", {
        description:
          reason instanceof ApiError
            ? reason.problem.detail
            : "Puede que otra persona haya actualizado el informe.",
      });
      await load();
    } finally {
      setBusy(false);
    }
  }

  async function publish() {
    if (!report) return;
    setBusy(true);
    try {
      setReport(await api.reports.publish(report.id, report.version));
      toast.success("Informe publicado", {
        description:
          "La versión anterior del mismo tipo queda sustituida cuando procede.",
      });
    } catch (reason) {
      toast.error("No se pudo publicar", {
        description:
          reason instanceof ApiError
            ? reason.problem.detail
            : "Actualiza el informe y vuelve a intentarlo.",
      });
      await load();
    } finally {
      setBusy(false);
    }
  }

  async function download(reportArtifactId: string) {
    if (!report) return;
    try {
      const link = await api.reports.downloadLink(report.id, reportArtifactId);
      triggerDownload(link.url);
    } catch {
      toast.error("No se pudo preparar la descarga", {
        description: "El enlace puede haber caducado. Vuelve a intentarlo.",
      });
    }
  }

  if (loading)
    return (
      <div className="report-viewer-state" role="status">
        <span className="auth-spinner" /> Cargando informe…
      </div>
    );

  if (error || !report)
    return (
      <div className="report-viewer-state reporting-error" role="alert">
        <AlertTriangle size={24} />
        <strong>Informe no disponible</strong>
        <p>{error}</p>
        <button className="vector-secondary" onClick={() => void load()}>
          Reintentar
        </button>
      </div>
    );

  const successorHref = `${routeBase}/dossiers/${report.dossier_id}/reports?new=1&template=${encodeURIComponent(report.template_key)}`;
  const reviews = (report.reviews ?? []).flatMap((item) => {
    const parsed = record(item);
    return parsed ? [parsed] : [];
  });

  return (
    <article className={`report-viewer ${embedded ? "embedded" : ""}`}>
      <header className="report-viewer-header">
        <div>
          <div className="report-viewer-meta">
            <span className={`report-status ${report.status}`}>
              {reportStatusLabel[report.status]}
            </span>
            <span>
              {report.template_key} · plantilla {report.template_version}
            </span>
            <span>Generación {report.generation_version}</span>
          </div>
          <h1>{report.title}</h1>
          <p>
            {report.confidentiality_label || "Uso interno"} · actualizado {formatDateTime(report.updated_at)}
          </p>
        </div>
        <div className="report-viewer-actions">
          {report.status === "failed" && (
            <PermissionGate permission="report.generate">
              <button className="vector-secondary" disabled={busy} onClick={() => void retry()}>
                <RefreshCw size={16} /> Reintentar
              </button>
            </PermissionGate>
          )}
          {report.status === "reviewed" && (
            <PermissionGate permission="report.publish">
              <button className="vector-primary" disabled={busy} onClick={() => void publish()}>
                <Send size={16} /> Publicar
              </button>
            </PermissionGate>
          )}
          {["published", "superseded"].includes(report.status) && (
            <PermissionGate permission="report.generate">
              <Link className="vector-secondary" href={successorHref}>
                <FileClock size={16} /> Preparar versión sucesora
              </Link>
            </PermissionGate>
          )}
        </div>
      </header>

      {report.job_id && ["draft", "generating"].includes(report.status) && (
        <section className="report-job-card" aria-label="Progreso de generación">
          <FileClock size={19} />
          <div>
            <strong>Oracle está preparando el informe</strong>
            <JobProgress jobId={report.job_id} onTerminal={() => void load()} allowActions />
          </div>
        </section>
      )}

      {report.status === "failed" && (
        <div className="reporting-error" role="alert">
          <strong>La generación no se completó</strong>
          <p>
            Código seguro: {report.error_code || "generation_failed"}. Puedes
            reintentar sin sobrescribir este intento.
          </p>
        </div>
      )}

      {report.status === "superseded" && (
        <div className="report-superseded" role="note">
          <FileCheck2 size={18} />
          <p>
            <strong>Versión histórica de solo lectura.</strong> Otro informe
            publicado del mismo tipo la ha sustituido; sus citas y artefactos
            permanecen disponibles para auditoría.
          </p>
        </div>
      )}

      {content ? (
        <div className="report-content-layout">
          <main className="report-content">
            <section className="report-executive-summary">
              <span className="section-kicker">Resumen ejecutivo</span>
              <p>{content.executive_summary}</p>
              <span className="confidence">Confianza {content.confidence}%</span>
            </section>
            {content.sections.map((section, sectionIndex) => (
              <section key={`${section.heading}-${sectionIndex}`} className="report-section">
                <h2>{section.heading}</h2>
                {section.paragraphs.map((paragraph, paragraphIndex) => (
                  <article
                    key={`${sectionIndex}-${paragraphIndex}`}
                    className={`report-claim ${paragraph.kind}`}
                  >
                    <div>
                      <span>{claimLabel(paragraph.kind)}</span>
                      <small>Confianza {paragraph.confidence}%</small>
                    </div>
                    <p>{paragraph.text}</p>
                    {!!paragraph.evidence_ids.length && (
                      <footer aria-label="Citas del párrafo">
                        {paragraph.evidence_ids.map((evidenceId, citationIndex) => {
                          const item = evidenceById.get(evidenceId);
                          return (
                            <button
                              key={evidenceId}
                              disabled={!item}
                              onClick={() => item && setSelectedEvidence(item)}
                              aria-label={`Abrir evidencia ${citationIndex + 1}`}
                              title={item?.sourceLabel || "Evidencia no incluida en el detalle"}
                            >
                              [{citationIndex + 1}]
                            </button>
                          );
                        })}
                      </footer>
                    )}
                  </article>
                ))}
              </section>
            ))}
            {!!content.open_questions.length && (
              <section className="report-open-questions">
                <h2>Preguntas abiertas</h2>
                <ul>
                  {content.open_questions.map((question) => (
                    <li key={question}>{question}</li>
                  ))}
                </ul>
              </section>
            )}
            {!!content.warnings.length && (
              <section className="report-warnings" role="note">
                <h2>Advertencias metodológicas</h2>
                <ul>
                  {content.warnings.map((warning) => (
                    <li key={warning}>{warning}</li>
                  ))}
                </ul>
              </section>
            )}
          </main>
          <aside className="report-source-index">
            <span className="section-kicker">Snapshot reproducible</span>
            <h2>Fuentes y evidencias</h2>
            <p>{evidence.length} referencias vinculadas a esta generación.</p>
            <ol>
              {evidence.map((item, index) => (
                <li key={item.id}>
                  <button onClick={() => setSelectedEvidence(item)}>
                    <span>[{index + 1}]</span>
                    <strong>{item.sourceLabel}</strong>
                    <small>{item.locator}</small>
                  </button>
                </li>
              ))}
            </ol>
          </aside>
        </div>
      ) : (
        !["draft", "generating", "failed"].includes(report.status) && (
          <div className="reporting-empty">
            <FileClock size={28} />
            <strong>Esta revisión no contiene una salida legible</strong>
            <p>Conservamos el registro, pero no se presenta como insight válido.</p>
          </div>
        )
      )}

      {!!report.artifacts.length && (
        <section className="report-artifacts" aria-labelledby="report-artifacts-title">
          <h2 id="report-artifacts-title">Artefactos</h2>
          <div>
            {report.artifacts.map((artifact) => (
              <article key={artifact.id}>
                <span>{artifact.format.toUpperCase()}</span>
                <div>
                  <strong>{artifact.media_type}</strong>
                  <small>{formatBytes(artifact.byte_size)} · checksum verificado</small>
                </div>
                <button
                  className="icon-button bordered"
                  disabled={artifact.status !== "available"}
                  aria-label={`Descargar artefacto ${artifact.format}`}
                  onClick={() => void download(artifact.id)}
                >
                  <Download size={16} />
                </button>
              </article>
            ))}
          </div>
        </section>
      )}

      {report.status === "ready" && revisionId && (
        <PermissionGate permission="report.review">
          <form className="report-review" onSubmit={review}>
            <header>
              <div>
                <span className="section-kicker">Control humano</span>
                <h2>Revisar informe</h2>
              </div>
              <CheckCircle2 size={20} />
            </header>
            <div className="report-review-fields">
              <label>
                Decisión
                <select
                  value={decision}
                  onChange={(event) =>
                    setDecision(
                      event.target.value as
                        | "approved"
                        | "changes_requested"
                        | "comment",
                    )
                  }
                >
                  <option value="approved">Aprobar</option>
                  <option value="changes_requested">Solicitar cambios</option>
                  <option value="comment">Añadir comentario</option>
                </select>
              </label>
              <label>
                Comentario
                <textarea
                  value={comment}
                  maxLength={2000}
                  required={decision !== "approved"}
                  onChange={(event) => setComment(event.target.value)}
                  placeholder="Explica la decisión para conservar trazabilidad."
                />
              </label>
            </div>
            <button className="vector-primary" disabled={busy}>
              <CheckCircle2 size={16} /> {busy ? "Guardando…" : "Registrar revisión"}
            </button>
          </form>
        </PermissionGate>
      )}

      {!!reviews.length && (
        <section className="report-review-history">
          <h2>Historial de revisión</h2>
          {reviews.map((review, index) => (
            <article key={String(review.id ?? index)}>
              <strong>{String(review.decision ?? "Revisión")}</strong>
              <p>{String(review.comment ?? "Sin comentario")}</p>
              <small>{formatDateTime(String(review.created_at ?? ""))}</small>
            </article>
          ))}
        </section>
      )}

      <Dialog.Root
        open={Boolean(selectedEvidence)}
        onOpenChange={(open) => !open && setSelectedEvidence(null)}
      >
        <Dialog.Portal>
          <Dialog.Overlay className="report-dialog-overlay" />
          <Dialog.Content className="evidence-dialog" aria-describedby="evidence-description">
            <header>
              <div>
                <span className="section-kicker">Evidencia · solo lectura</span>
                <Dialog.Title>{selectedEvidence?.sourceLabel}</Dialog.Title>
              </div>
              <Dialog.Close className="icon-button bordered" aria-label="Cerrar evidencia">
                <X size={17} />
              </Dialog.Close>
            </header>
            <Dialog.Description id="evidence-description">
              Esta fuente pertenece al snapshot inmutable utilizado para generar el informe.
            </Dialog.Description>
            <blockquote>{selectedEvidence?.extract || "Extracto no disponible."}</blockquote>
            <dl>
              <div><dt>Localización</dt><dd>{selectedEvidence?.locator}</dd></div>
              <div><dt>Clasificación</dt><dd>{selectedEvidence?.classification}</dd></div>
              <div><dt>ID de evidencia</dt><dd>{selectedEvidence?.id}</dd></div>
            </dl>
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    </article>
  );
}

export function ReportDrawer({
  reportId,
  routeBase,
  open,
  onOpenChange,
}: {
  reportId: string | null;
  routeBase: "/app" | "/concept-a";
  open: boolean;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="report-dialog-overlay" />
        <Dialog.Content className="report-drawer-content">
          <Dialog.Title className="sr-only">Detalle del informe</Dialog.Title>
          <Dialog.Description className="sr-only">
            Revisión, citas, artefactos y workflow del informe seleccionado.
          </Dialog.Description>
          <Dialog.Close className="report-drawer-close icon-button bordered" aria-label="Cerrar informe">
            <X size={18} />
          </Dialog.Close>
          {reportId && <ReportViewer reportId={reportId} routeBase={routeBase} embedded />}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}

export function ReportViewerRoute({
  routeBase = "/app",
}: {
  routeBase?: "/app" | "/concept-a";
}) {
  const { id } = useParams<{ id: string }>();
  return (
    <div className="reporting-page report-detail-page">
      <Link className="back-link" href={`${routeBase}/reports`}>
        Volver a la biblioteca
      </Link>
      <ReportViewer reportId={id} routeBase={routeBase} />
    </div>
  );
}
