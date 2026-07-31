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

export function DossierCustomBriefSection({ dossierId }: { dossierId: string }) {
  const [brief, setBrief] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [accepted, setAccepted] = useState<CustomBriefAccepted | null>(null);
  const [detail, setDetail] = useState<CustomBriefDetail | null>(null);
  const [hydrating, setHydrating] = useState(true);
  const pollTimer = useRef<number | null>(null);

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
        if (current.plan_status === "draft" && !current.error_code) {
          stopPoll();
          pollTimer.current = window.setTimeout(() => {
            void pollBrief(reportId);
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
    let cancelled = false;
    const kickoff = window.setTimeout(() => {
      void (async () => {
        setHydrating(true);
        const stored = readSession(dossierId);
        if (!stored?.reportId) {
          if (!cancelled) setHydrating(false);
          return;
        }
        try {
          const current = await api.customBriefs.get(dossierId, stored.reportId);
          if (cancelled) return;
          setDetail(current);
          setAccepted({
            job_id: current.background_job_id ?? stored.jobId ?? "",
            report_id: current.id,
            plan_status: current.plan_status,
            report: current as unknown as Record<string, unknown>,
          });
          if (current.plan_status === "draft" && !current.error_code) {
            void pollBrief(current.id);
          }
        } catch {
          // stale key
        }
        if (!cancelled) setHydrating(false);
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
        idempotencyKey(`brief-${dossierId}-${Date.now()}`),
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

  return (
    <div className="dossier-section-page">
      <header className="vector-panel">
        <div>
          <span className="section-kicker">Asistente de informes</span>
          <h1>Informe libre</h1>
          <p>
            Guarda el encargo como brief y encola la planificación. El plan propuesto se
            muestra al asentar el worker; recargar restaura el informe desde la API.
          </p>
        </div>
      </header>

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
            busy={busy}
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
            <h2>Estado del brief</h2>
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
              <dt>Plan</dt>
              <dd>{PLAN_LABEL[planStatus ?? ""] ?? planStatus ?? "—"}</dd>
            </div>
          </dl>
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
            </div>
          ) : planStatus === "draft" ? (
            <p>Planificando… el estado se actualizará sin recargar (o al pulsar Actualizar).</p>
          ) : null}
          {detail?.error_message ? (
            <p role="alert">Error: {detail.error_message}</p>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}
