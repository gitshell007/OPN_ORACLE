"use client";

import { ApiError, api } from "@oracle/api-client";
import type { components } from "@oracle/api-client";
import { useEffect, useRef, useState } from "react";
import { RotateCcw, Square } from "lucide-react";
import { toast } from "sonner";
import { productStatusLabel } from "@/lib/product-copy";

type Job = components["schemas"]["JobResponse"];

const terminal = new Set<Job["status"]>([
  "succeeded",
  "failed",
  "cancelled",
]);

export function JobProgress({
  jobId,
  label = "Procesando en segundo plano",
  onTerminal,
  allowActions = false,
}: {
  jobId: string;
  label?: string;
  onTerminal?: (job: Job) => void;
  allowActions?: boolean;
}) {
  const [job, setJob] = useState<Job | null>(null);
  const [error, setError] = useState(false);
  const [mutating, setMutating] = useState(false);
  const callback = useRef(onTerminal);
  const announcedTerminal = useRef<string | null>(null);

  useEffect(() => {
    callback.current = onTerminal;
  }, [onTerminal]);

  useEffect(() => {
    let active = true;
    let timer: number | undefined;
    let failures = 0;

    const load = async () => {
      try {
        const next = await api.jobs.get(jobId);
        if (!active) return;
        setJob(next);
        setError(false);
        failures = 0;
        if (terminal.has(next.status)) {
          if (announcedTerminal.current !== `${next.id}:${next.status}`) {
            announcedTerminal.current = `${next.id}:${next.status}`;
            if (next.status === "succeeded") toast.success("Proceso completado");
            if (next.status === "failed")
              toast.error("El proceso necesita atención");
          }
          callback.current?.(next);
          return;
        }
        timer = window.setTimeout(load, next.status === "queued" ? 2500 : 1800);
      } catch (reason) {
        if (!active) return;
        setError(true);
        failures += 1;
        if (!(reason instanceof ApiError && reason.status === 404)) {
          const delay = Math.min(30_000, 2_000 * 2 ** Math.min(failures, 4));
          timer = window.setTimeout(load, delay);
        }
      }
    };

    void load();
    return () => {
      active = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [jobId]);

  const mutate = async (action: "retry" | "cancel") => {
    if (!job) return;
    setMutating(true);
    try {
      const next =
        action === "retry"
          ? await api.jobs.retry(job.id, job.version)
          : await api.jobs.cancel(job.id, job.version);
      announcedTerminal.current = null;
      setJob(next);
      setError(false);
      toast.success(action === "retry" ? "Reintento encolado" : "Cancelación solicitada");
    } catch (reason) {
      toast.error(
        reason instanceof ApiError
          ? reason.problem.detail
          : "No se pudo actualizar el proceso.",
      );
    } finally {
      setMutating(false);
    }
  };

  if (error && !job)
    return (
      <span className="job-progress-error" role="status">
        Progreso no disponible
      </span>
    );

  const progress = Math.round(job?.progress ?? 0);
  return (
    <div className="job-progress" aria-live="polite">
      <div>
        <span>{job?.stage ? productStatusLabel(job.stage) : label}</span>
        <b>{progress}%</b>
      </div>
      <div
        className="job-progress-track"
        role="progressbar"
        aria-label={label}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={progress}
      >
        <span style={{ width: `${progress}%` }} />
      </div>
      {job?.status === "failed" && (
        <small role="alert">
          {job.error_message || "El proceso terminó con un error controlado."}
        </small>
      )}
      {allowActions && job && (
        <div className="job-progress-actions">
          {job.status === "failed" && job.retryable && (
            <button disabled={mutating} onClick={() => void mutate("retry")}>
              <RotateCcw size={12} /> Reintentar
            </button>
          )}
          {["queued", "running", "retrying"].includes(job.status) &&
            !job.cancel_requested && (
              <button disabled={mutating} onClick={() => void mutate("cancel")}>
                <Square size={11} /> Cancelar
              </button>
            )}
        </div>
      )}
    </div>
  );
}
