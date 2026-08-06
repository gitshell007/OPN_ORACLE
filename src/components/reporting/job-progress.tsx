"use client";

import { ApiError, api } from "@oracle/api-client";
import type { components } from "@oracle/api-client";
import { useCallback, useEffect, useRef, useState } from "react";
import { RotateCcw, Square } from "lucide-react";
import { toast } from "sonner";
import { AsyncActionButton } from "@/components/ui/async-action-button";
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
  const [pollEpoch, setPollEpoch] = useState(0);
  const callback = useRef(onTerminal);
  const announcedTerminal = useRef<string | null>(null);
  const pollTimer = useRef<number | undefined>(undefined);
  const pollCycle = useRef(0);
  const toastId = `job-progress:${jobId}`;

  useEffect(() => {
    callback.current = onTerminal;
  }, [onTerminal]);

  const announceTerminal = useCallback(
    (next: Job) => {
      const announcementKey = `${next.id}:${next.status}`;
      if (announcedTerminal.current === announcementKey) return;

      announcedTerminal.current = announcementKey;
      if (next.status === "succeeded")
        toast.success("Proceso completado", { id: toastId, duration: 4000 });
      if (next.status === "failed")
        toast.error("El proceso necesita atención", {
          id: toastId,
          duration: 8000,
          closeButton: true,
        });
      if (next.status === "cancelled")
        toast.message("Proceso cancelado", { id: toastId, duration: 4000 });
      callback.current?.(next);
    },
    [toastId],
  );

  const stopCurrentPoll = () => {
    pollCycle.current += 1;
    if (pollTimer.current !== undefined) {
      window.clearTimeout(pollTimer.current);
      pollTimer.current = undefined;
    }
  };

  useEffect(() => {
    const cycle = pollCycle.current + 1;
    pollCycle.current = cycle;
    let failures = 0;

    const schedule = (delay: number) => {
      pollTimer.current = window.setTimeout(() => {
        pollTimer.current = undefined;
        if (pollCycle.current !== cycle) return;
        void load();
      }, delay);
    };

    const load = async () => {
      try {
        const next = await api.jobs.get(jobId);
        if (pollCycle.current !== cycle) return;
        setJob(next);
        setError(false);
        failures = 0;
        if (terminal.has(next.status)) {
          announceTerminal(next);
          return;
        }
        if (announcedTerminal.current?.startsWith(`${next.id}:failed`)) {
          toast.dismiss(toastId);
          announcedTerminal.current = null;
        }
        schedule(next.status === "queued" ? 2500 : 1800);
      } catch (reason) {
        if (pollCycle.current !== cycle) return;
        setError(true);
        failures += 1;
        if (!(reason instanceof ApiError && reason.status === 404)) {
          const delay = Math.min(30_000, 2_000 * 2 ** Math.min(failures, 4));
          schedule(delay);
        }
      }
    };

    void load();
    return () => {
      if (pollCycle.current === cycle) pollCycle.current += 1;
      if (pollTimer.current !== undefined) {
        window.clearTimeout(pollTimer.current);
        pollTimer.current = undefined;
      }
    };
  }, [announceTerminal, jobId, pollEpoch, toastId]);

  const mutate = async (action: "retry" | "cancel") => {
    if (!job) return;
    setMutating(true);
    try {
      const next =
        action === "retry"
          ? await api.jobs.retry(job.id, job.version)
          : await api.jobs.cancel(job.id, job.version);
      announcedTerminal.current = null;
      stopCurrentPoll();
      setJob(next);
      setError(false);
      toast.success(action === "retry" ? "Reintento encolado" : "Cancelación solicitada", {
        id: toastId,
        duration: 4000,
      });
      if (terminal.has(next.status)) {
        announceTerminal(next);
      } else {
        setPollEpoch((epoch) => epoch + 1);
      }
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
            <AsyncActionButton className="" loading={mutating} onClick={() => void mutate("retry")}>
              <RotateCcw size={12} /> Reintentar
            </AsyncActionButton>
          )}
          {["queued", "running", "retrying"].includes(job.status) &&
            !job.cancel_requested && (
              <AsyncActionButton className="" loading={mutating} onClick={() => void mutate("cancel")}>
                <Square size={11} /> Cancelar
              </AsyncActionButton>
            )}
        </div>
      )}
    </div>
  );
}
