"use client";

import {
  ApiError,
  api,
  type CustomBriefAccepted,
  type CustomBriefDetail,
} from "@oracle/api-client";
import { FilePlus2, RefreshCw } from "lucide-react";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { AsyncActionButton } from "@/components/ui/async-action-button";
import { idempotencyKey } from "@/components/reporting/reporting-utils";
import { PageHeader } from "@/components/ui/page-header";

const STORAGE_PREFIX = "oracle:dossier-brief:";

type BriefSession = {
  reportId: string;
  jobId?: string | null;
};

function storageKey(dossierId: string): string {
  return `${STORAGE_PREFIX}${dossierId}`;
}

function readSession(dossierId: string): BriefSession | null {
  try {
    const raw = sessionStorage.getItem(storageKey(dossierId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as BriefSession;
    if (parsed?.reportId) return parsed;
  } catch {
    // optional
  }
  return null;
}

function writeSession(dossierId: string, session: BriefSession): void {
  try {
    sessionStorage.setItem(storageKey(dossierId), JSON.stringify(session));
  } catch {
    // optional
  }
}

const PLAN_LABEL: Record<string, string> = {
  draft: "Borrador / planificando",
  proposed: "Plan propuesto (revisar)",
  accepted: "Plan aceptado",
};

const LIFE_LABEL: Record<string, string> = {
  brief_draft: "Brief en borrador",
  plan_proposed: "Plan propuesto",
  plan_accepted: "Plan aceptado (snapshot congelado)",
  accepted_degraded: "Plan aceptado (generación bloqueada)",
  generating: "Generando informe",
  reviewing: "Revisando",
  ready: "Listo para descargar",
  failed: "Fallido",
  cancelled: "Cancelado",
};

export function DossierCustomBriefSection({ dossierId }: { dossierId: string }) {
  const [brief, setBrief] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [accepted, setAccepted] = useState<CustomBriefAccepted | null>(null);
  const [detail, setDetail] = useState<CustomBriefDetail | null>(null);
  const [hydrating, setHydrating] = useState(true);
  const pollTimer = useRef<number | null>(null);
  const pollBriefRef = useRef<((reportId: string) => Promise<void>) | null>(null);

  const stopPoll = useCallback(() => {
    if (pollTimer.current != null) {
      window.clearTimeout(pollTimer.current);
      pollTimer.current = null;
    }
  }, []);

  const pollBrief = useCallback(
    async (reportId: string) => {
      try {
        const current = await api.customBriefs.get(dossierId, reportId);
        setDetail(current);
        setAccepted((prev) =>
          prev
            ? { ...prev, plan_status: current.plan_status, report_id: current.id }
            : {
                job_id: current.background_job_id ?? "",
                report_id: current.id,
                plan_status: current.plan_status,
                report: current as unknown as Record<string, unknown>,
              },
        );
        writeSession(dossierId, {
          reportId: current.id,
          jobId: current.background_job_id,
        });
        const life = current.lifecycle_state || current.plan_status;
        const inFlight =
          (!current.error_code && current.plan_status === "draft") ||
          life === "generating" ||
          life === "reviewing" ||
          life === "plan_accepted";
        if (inFlight && life !== "ready" && life !== "failed" && life !== "cancelled") {
          stopPoll();
          pollTimer.current = window.setTimeout(() => {
            void pollBriefRef.current?.(reportId);
          }, 2000);
        } else {
          stopPoll();
        }
      } catch (reason) {
        setError(
          reason instanceof ApiError
            ? reason.problem.detail
            : "No se pudo consultar el estado del brief.",
        );
      }
    },
    [dossierId, stopPoll],
  );

  useEffect(() => {
    pollBriefRef.current = pollBrief;
  }, [pollBrief]);

  // Durable rehydrate: API is source of truth. sessionStorage is only a shortcut.
  useEffect(() => {
    let cancelled = false;
    const kickoff = window.setTimeout(() => {
      void (async () => {
        setHydrating(true);
        try {
          const stored = readSession(dossierId);

          const applyBrief = (current: CustomBriefDetail) => {
            setDetail(current);
            setAccepted({
              job_id: current.background_job_id ?? "",
              report_id: current.id,
              plan_status: current.plan_status,
              report: current as unknown as Record<string, unknown>,
            });
            writeSession(dossierId, {
              reportId: current.id,
              jobId: current.background_job_id,
            });
            const life = current.lifecycle_state || current.plan_status;
            const inFlight =
              (!current.error_code && current.plan_status === "draft") ||
              life === "generating" ||
              life === "reviewing" ||
              life === "plan_accepted";
            if (inFlight && life !== "ready" && life !== "failed" && life !== "cancelled") {
              void pollBrief(current.id);
            }
          };

          // Fast path: same-tab reload with valid session marker.
          if (stored?.reportId) {
            try {
              const current = await api.customBriefs.get(dossierId, stored.reportId);
              if (cancelled) return;
              applyBrief(current);
              return;
            } catch {
              // Stale key — fall through to API list.
            }
          }

          // Tab closed / logout / other device: recover latest brief from API.
          const listed = await api.customBriefs.list(dossierId, { limit: 1 });
          if (cancelled) return;
          const latest = listed.items?.[0];
          if (!latest?.id) return;
          applyBrief(latest);
        } catch {
          // Empty or unreachable API: leave form usable.
        } finally {
          if (!cancelled) setHydrating(false);
        }
      })();
    }, 0);
    return () => {
      cancelled = true;
      window.clearTimeout(kickoff);
      stopPoll();
    };
  }, [dossierId, pollBrief, stopPoll]);

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const text = brief.trim();
    if (text.length < 1) return;
    setBusy(true);
    setError(null);
    try {
      const result = await api.customBriefs.create(
        dossierId,
        { brief_request: text },
        idempotencyKey(`brief-${dossierId}-${crypto.randomUUID()}`),
      );
      setAccepted(result);
      writeSession(dossierId, {
        reportId: result.report_id,
        jobId: result.job_id,
      });
      toast.success("Brief registrado", {
        description: "Plan en cola (202). Se actualizará al proponerse.",
      });
      void pollBrief(result.report_id);
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.problem.detail
          : "No se pudo crear el informe personalizado.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (hydrating) {
    return (
      <div className="dossier-loading" role="status" aria-label="Restaurando brief">
        <span />
        <span />
        <span />
      </div>
    );
  }

  const planStatus = detail?.plan_status ?? accepted?.plan_status ?? null;
  const sections = (detail?.proposed_plan?.sections as Array<{ title?: string }> | undefined) ?? [];

  async function withVersion(
    action: (version: number) => Promise<CustomBriefDetail>,
  ) {
    if (!detail?.id) return;
    const version = detail.version ?? 1;
    setBusy(true);
    setError(null);
    try {
      const next = await action(version);
      setDetail(next);
      setAccepted((prev) =>
        prev
          ? { ...prev, plan_status: next.plan_status, report_id: next.id }
          : {
              job_id: next.background_job_id ?? "",
              report_id: next.id,
              plan_status: next.plan_status,
              report: next as unknown as Record<string, unknown>,
            },
      );
      writeSession(dossierId, {
        reportId: next.id,
        jobId: next.background_job_id,
      });
      const life = next.lifecycle_state || next.plan_status;
      if (
        life === "generating" ||
        life === "reviewing" ||
        life === "plan_accepted" ||
        (next.plan_status === "draft" && !next.error_code)
      ) {
        void pollBrief(next.id);
      }
      toast.success("Informe actualizado");
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.problem.detail
          : "No se pudo actualizar el informe.",
      );
    } finally {
      setBusy(false);
    }
  }

  const life =
    detail?.lifecycle_state ||
    (planStatus === "proposed"
      ? "plan_proposed"
      : planStatus === "accepted"
        ? "plan_accepted"
        : planStatus === "draft"
          ? "brief_draft"
          : planStatus || "");



  return (
    <div className="dossier-section-page">
      <PageHeader
        eyebrow="Asistente de informes"
        title="Informe libre"
        description="Guarda el encargo como brief y encola la planificación. El plan propuesto se muestra al asentar el worker; al volver (incluso tras cerrar la pestaña) se recupera el último brief del expediente desde la API."
      />

      <section className="vector-panel">
        <form onSubmit={(event) => void onSubmit(event)} className="stack-form">
          <label className="field full">
            <span>Encargo del informe</span>
            <textarea
              required
              minLength={1}
              maxLength={20000}
              rows={6}
              value={brief}
              onChange={(event) => setBrief(event.target.value)}
              placeholder="Describe audiencia, alcance, periodo, fuentes deseadas y formato…"
            />
          </label>
          <AsyncActionButton
            type="submit"
            className="vector-primary"
            loading={busy}
            disabled={busy || !brief.trim()}
          >
            <FilePlus2 size={15} /> Crear brief y planificar
          </AsyncActionButton>
        </form>
        {error ? (
          <p role="alert" className="form-error">
            {error}
          </p>
        ) : null}
      </section>

      {accepted ? (
        <section className="vector-panel" aria-live="polite">
          <header>
            <h2>Estado del informe</h2>
            <button
              type="button"
              className="vector-secondary"
              onClick={() => void pollBrief(accepted.report_id)}
            >
              <RefreshCw size={14} /> Actualizar
            </button>
          </header>
          <dl className="placeholder-contract">
            <div>
              <dt>Informe</dt>
              <dd>{accepted.report_id}</dd>
            </div>
            <div>
              <dt>Job</dt>
              <dd>{accepted.job_id || detail?.background_job_id || "—"}</dd>
            </div>
            <div>
              <dt>Ciclo de vida</dt>
              <dd>{LIFE_LABEL[life] ?? life ?? PLAN_LABEL[planStatus ?? ""] ?? planStatus ?? "—"}</dd>
            </div>
            <div>
              <dt>Versión</dt>
              <dd>{detail?.version ?? "—"}</dd>
            </div>
          </dl>
          {detail?.memory_degraded || detail?.accepted_degraded || detail?.generation_blocked ? (
            <p role="status" className="muted">
              {detail?.generation_blocked
                ? `Generación bloqueada (${detail.generation_blocked_code || "blocked"}): ${
                    detail.generation_blocked_reason ||
                    detail.memory_degraded_reason ||
                    "la memoria del expediente no está disponible ahora"
                  }`
                : `Degradado: ${
                    detail.memory_degraded_reason ||
                    "la memoria del expediente no está disponible ahora"
                  }`}
            </p>
          ) : null}
          {detail?.accepted_snapshot_hash ? (
            <p className="muted">
              Snapshot: <code>{detail.accepted_snapshot_hash.slice(0, 16)}…</code>
            </p>
          ) : null}
          {detail?.brief_request ? (
            <p>
              <strong>Encargo:</strong> {detail.brief_request}
            </p>
          ) : null}
          {planStatus === "proposed" && sections.length > 0 ? (
            <div>
              <strong>Secciones propuestas</strong>
              <ul>
                {sections.map((section, index) => (
                  <li key={`${section.title ?? "s"}-${index}`}>
                    {section.title ?? `Sección ${index + 1}`}
                  </li>
                ))}
              </ul>
              <p className="muted">
                Acepte o rechace el plan. La aceptación congela el snapshot; no hay autoaceptación.
              </p>
              <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap" }}>
                <AsyncActionButton
                  type="button"
                  className="vector-primary"
                  loading={busy}
                  disabled={busy}
                  onClick={() =>
                    void withVersion((v) =>
                      api.customBriefs.acceptPlan(dossierId, detail!.id, v, {
                        start_generation: true,
                      }),
                    )
                  }
                >
                  Aceptar plan y generar
                </AsyncActionButton>
                <AsyncActionButton
                  type="button"
                  className="vector-secondary"
                  loading={busy}
                  disabled={busy}
                  onClick={() =>
                    void withVersion((v) =>
                      api.customBriefs.rejectPlan(
                        dossierId,
                        detail!.id,
                        v,
                        "rechazado en UI",
                      ),
                    )
                  }
                >
                  Rechazar plan
                </AsyncActionButton>
              </div>
            </div>
          ) : planStatus === "draft" || life === "generating" || life === "reviewing" ? (
            <p>
              {life === "generating" || life === "reviewing"
                ? "Generando/revisando… el estado se conserva al recargar."
                : "Planificando… el estado se actualizará sin recargar (o al pulsar Actualizar)."}
            </p>
          ) : null}
          <div style={{ display: "flex", gap: "0.5rem", flexWrap: "wrap", marginTop: "0.75rem" }}>
            {life === "generating" || life === "reviewing" || life === "plan_accepted" ? (
              <AsyncActionButton
                type="button"
                className="vector-secondary"
                loading={busy}
                disabled={busy}
                onClick={() =>
                  void withVersion((v) => api.customBriefs.cancel(dossierId, detail!.id, v))
                }
              >
                Cancelar
              </AsyncActionButton>
            ) : null}
            {life === "failed" ? (
              <AsyncActionButton
                type="button"
                className="vector-primary"
                loading={busy}
                disabled={busy}
                onClick={() =>
                  void withVersion((v) => api.customBriefs.retry(dossierId, detail!.id, v))
                }
              >
                Reintentar
              </AsyncActionButton>
            ) : null}
            {detail?.downloadable ? (
              <a
                className="vector-primary"
                href={api.customBriefs.downloadUrl(dossierId, detail.id)}
                download
              >
                Descargar artefacto
              </a>
            ) : null}
          </div>
          {detail?.error_message ? (
            <p role="alert">
              Error: {detail.error_code}: {detail.error_message}
            </p>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
