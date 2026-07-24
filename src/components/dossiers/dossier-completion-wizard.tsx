"use client";

import * as Dialog from "@radix-ui/react-dialog";
import {
  api,
  type DossierWizardAnswer,
  type DossierWizardOutput,
  type DossierWizardRecommendedAction,
  type JobResponse,
} from "@oracle/api-client";
import {
  ArrowRight,
  CheckCircle2,
  CircleAlert,
  FileSearch,
  RefreshCw,
  Sparkles,
  X,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { type FormEvent, useCallback, useEffect, useMemo, useState } from "react";
import { JobProgress } from "@/components/reporting/job-progress";
import { AsyncActionButton, HydratedActionButton } from "@/components/ui/async-action-button";

const terminal = new Set(["succeeded", "failed", "cancelled"]);

function wizardKey(dossierId: string, kind: string): string {
  return `oracle:wizard-prefill:${dossierId}:${kind}`;
}

function idempotencyKey(dossierId: string): string {
  const suffix =
    typeof crypto !== "undefined" && "randomUUID" in crypto
      ? crypto.randomUUID()
      : `${Date.now()}-${Math.random().toString(16).slice(2)}`;
  return `dossier-wizard-${dossierId}-${suffix}`.slice(0, 200);
}

function statusLabel(status: DossierWizardOutput["section_diagnostics"][number]["status"]) {
  if (status === "ok") return "Completo";
  if (status === "incomplete") return "Incompleto";
  return "Vacío";
}

function sectionLabel(section: DossierWizardOutput["section_diagnostics"][number]["section"]) {
  return {
    goal: "Objetivo",
    signals: "Señales",
    procurement: "Contratación pública",
    opportunities: "Oportunidades",
    risks: "Riesgos",
    actors: "Actores",
    hypotheses: "Hipótesis",
    other: "Otros",
  }[section];
}

function actionLabel(kind: DossierWizardRecommendedAction["kind"]) {
  return {
    create_signal_monitor: "Crear vigilancia",
    pin_procurement: "Buscar licitaciones",
    create_opportunity: "Crear oportunidad",
    create_risk: "Crear riesgo",
    create_actor: "Crear actor",
    refine_goal: "Refinar objetivo",
    other: "Ver orientación",
  }[kind];
}

function safeString(value: unknown): string {
  return typeof value === "string" ? value : "";
}

export function DossierCompletionWizard({ dossierId }: { dossierId: string }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [loading, setLoading] = useState(false);
  const [running, setRunning] = useState(false);
  const [job, setJob] = useState<JobResponse | null>(null);
  const [output, setOutput] = useState<DossierWizardOutput | null>(null);
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [error, setError] = useState<string | null>(null);

  const answerPayload = useMemo<DossierWizardAnswer[]>(
    () =>
      Object.entries(answers)
        .map(([question_id, answer]) => ({ question_id, answer: answer.trim() }))
        .filter((item) => item.answer),
    [answers],
  );

  const loadLatest = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const latest = await api.dossierCompletionWizard.latest(dossierId);
      setJob(latest.job);
      setOutput(latest.artifact?.output ?? null);
      const nonTerminal = latest.job && !terminal.has(latest.job.status);
      setRunning(Boolean(nonTerminal));
    } catch {
      setError("No se pudo recuperar la última ronda del asistente.");
    } finally {
      setLoading(false);
    }
  }, [dossierId]);

  useEffect(() => {
    if (!open) return;
    let cancelled = false;
    queueMicrotask(() => {
      if (!cancelled) void loadLatest();
    });
    return () => {
      cancelled = true;
    };
  }, [loadLatest, open]);

  async function runRound(event?: FormEvent) {
    event?.preventDefault();
    setRunning(true);
    setError(null);
    try {
      const response = await api.dossierCompletionWizard.run(
        dossierId,
        { answers: answerPayload },
        idempotencyKey(dossierId),
      );
      setJob(response.job);
      setOutput(response.artifact?.output ?? output);
    } catch {
      setRunning(false);
      setError(
        "No se pudo lanzar la ronda. Si Signal aún no conoce esta task, el proceso puede quedar bloqueado hasta desplegarla.",
      );
    }
  }

  function onTerminal() {
    setRunning(false);
    setAnswers({});
    void loadLatest();
  }

  function applyAction(action: DossierWizardRecommendedAction) {
    const prefill = action.prefill ?? {};
    if (action.kind === "create_signal_monitor") {
      sessionStorage.setItem(wizardKey(dossierId, "monitor"), JSON.stringify(prefill));
      router.push(`/app/dossiers/${dossierId}/settings?wizard_prefill=monitor`);
      setOpen(false);
      return;
    }
    if (action.kind === "pin_procurement") {
      const query = new URLSearchParams();
      const keywords = safeString(prefill.procurement_query) || safeString(prefill.query);
      if (keywords) query.set("keywords", keywords);
      router.push(`/app/procurement${query.size ? `?${query.toString()}` : ""}`);
      setOpen(false);
      return;
    }
    if (action.kind === "create_opportunity" || action.kind === "create_risk") {
      const kind = action.kind === "create_opportunity" ? "opportunity" : "risk";
      sessionStorage.setItem(wizardKey(dossierId, kind), JSON.stringify(prefill));
      router.push(
        `/app/dossiers/${dossierId}/${kind === "opportunity" ? "opportunities" : "risks"}?wizard_prefill=${kind}`,
      );
      setOpen(false);
      return;
    }
    if (action.kind === "create_actor") {
      sessionStorage.setItem(wizardKey(dossierId, "actor"), JSON.stringify(prefill));
      router.push(`/app/dossiers/${dossierId}/actors?wizard_prefill=actor`);
      setOpen(false);
      return;
    }
    if (action.kind === "refine_goal") {
      router.push(`/app/dossiers/${dossierId}/settings`);
      setOpen(false);
    }
  }

  return (
    <Dialog.Root open={open} onOpenChange={setOpen}>
      <Dialog.Trigger asChild>
        <HydratedActionButton className="vector-ai">
          <Sparkles size={15} aria-hidden="true" />
          Mejorar con Oracle
        </HydratedActionButton>
      </Dialog.Trigger>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog-content dossier-wizard-dialog">
          <div className="dialog-header">
            <div>
              <span className="section-kicker">Asistente guiado</span>
              <Dialog.Title>Mejorar expediente con Oracle</Dialog.Title>
              <Dialog.Description>
                Diagnóstico por rondas: Oracle propone preguntas y acciones, pero la persona decide
                qué ejecutar.
              </Dialog.Description>
            </div>
            <Dialog.Close className="icon-button" aria-label="Cerrar">
              <X />
            </Dialog.Close>
          </div>

          {error && (
            <p className="form-error" role="alert">
              {error}
            </p>
          )}
          {loading ? (
            <div className="intelligence-loading" role="status">
              <span className="auth-spinner" /> Recuperando última ronda…
            </div>
          ) : (
            <>
              {job && running && (
                <div className="wizard-job-status">
                  <JobProgress
                    jobId={job.id}
                    label="Analizando completitud"
                    onTerminal={onTerminal}
                    allowActions
                  />
                </div>
              )}

              {!output && !running && (
                <section className="wizard-empty">
                  <FileSearch size={28} aria-hidden="true" />
                  <h2>Empieza con un diagnóstico del expediente</h2>
                  <p>
                    Revisaré objetivo, señales, licitaciones, actores, oportunidades y riesgos para
                    sugerir el siguiente paso concreto.
                  </p>
                  <AsyncActionButton className="vector-ai" type="button" loading={running} onClick={() => void runRound()}>
                    <Sparkles size={15} aria-hidden="true" />
                    Lanzar diagnóstico
                  </AsyncActionButton>
                </section>
              )}

              {output && (
                <form className="wizard-round" onSubmit={runRound}>
                  <section className="wizard-summary">
                    <div>
                      <h2>Diagnóstico</h2>
                      <p>{output.summary}</p>
                    </div>
                    <span>Confianza {output.confidence} %</span>
                  </section>

                  <div className="wizard-diagnostics">
                    {output.section_diagnostics.map((item) => (
                      <article key={`${item.section}-${item.status}`}>
                        <span className={`wizard-status ${item.status}`}>
                          {item.status === "ok" ? (
                            <CheckCircle2 size={14} aria-hidden="true" />
                          ) : (
                            <CircleAlert size={14} aria-hidden="true" />
                          )}
                          {statusLabel(item.status)}
                        </span>
                        <strong>{sectionLabel(item.section)}</strong>
                        <p>{item.explanation}</p>
                      </article>
                    ))}
                  </div>

                  {output.questions.length > 0 && (
                    <section className="wizard-questions">
                      <h2>Preguntas para afinar la siguiente ronda</h2>
                      {output.questions.map((question) => (
                        <label className="field" key={question.id}>
                          <span>{question.question}</span>
                          <textarea
                            value={answers[question.id] ?? ""}
                            onChange={(event) =>
                              setAnswers((current) => ({
                                ...current,
                                [question.id]: event.target.value,
                              }))
                            }
                            placeholder={question.expected_input}
                            aria-describedby={`wizard-question-${question.id}`}
                          />
                          <small id={`wizard-question-${question.id}`}>
                            {question.why_it_matters}
                          </small>
                        </label>
                      ))}
                    </section>
                  )}

                  {output.recommended_actions.length > 0 && (
                    <section className="wizard-actions">
                      <h2>Acciones recomendadas</h2>
                      {output.recommended_actions.map((action) => (
                        <article key={`${action.kind}-${action.title}`}>
                          <div>
                            <span>{actionLabel(action.kind)}</span>
                            <strong>{action.title}</strong>
                            <p>{action.rationale}</p>
                          </div>
                          <button
                            className="vector-secondary"
                            type="button"
                            onClick={() => applyAction(action)}
                          >
                            Abrir formulario <ArrowRight size={14} aria-hidden="true" />
                          </button>
                        </article>
                      ))}
                    </section>
                  )}

                  {output.warnings.length > 0 && (
                    <section className="wizard-warnings">
                      <h2>Límites del análisis</h2>
                      <ul>
                        {output.warnings.map((warning) => (
                          <li key={warning}>{warning}</li>
                        ))}
                      </ul>
                    </section>
                  )}

                  <div className="dialog-actions">
                    <Dialog.Close className="vector-secondary" type="button">
                      Cerrar
                    </Dialog.Close>
                    <AsyncActionButton className="vector-ai" type="submit" loading={running}>
                      {running ? (
                        <>
                          <RefreshCw size={15} aria-hidden="true" />
                          Lanzando…
                        </>
                      ) : (
                        <>
                          <Sparkles size={15} aria-hidden="true" />
                          Lanzar nueva ronda
                        </>
                      )}
                    </AsyncActionButton>
                  </div>
                </form>
              )}
            </>
          )}
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
