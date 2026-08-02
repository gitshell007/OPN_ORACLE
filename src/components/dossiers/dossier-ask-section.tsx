"use client";

import {
  ApiError,
  api,
  type DossierConversation,
  type DossierMessage,
} from "@oracle/api-client";
import { MessageSquare, RefreshCw, Send } from "lucide-react";
import { FormEvent, useCallback, useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { AsyncActionButton } from "@/components/ui/async-action-button";
import { idempotencyKey } from "@/components/reporting/reporting-utils";

const STORAGE_PREFIX = "oracle:dossier-ask:";

type AskSession = {
  conversationId: string;
  messageId: string | null;
  title?: string;
};

function storageKey(dossierId: string): string {
  return `${STORAGE_PREFIX}${dossierId}`;
}

function readSession(dossierId: string): AskSession | null {
  try {
    const raw = sessionStorage.getItem(storageKey(dossierId));
    if (!raw) return null;
    const parsed = JSON.parse(raw) as AskSession;
    if (parsed?.conversationId) return parsed;
  } catch {
    // sessionStorage is convenience; API is durable.
  }
  return null;
}

function writeSession(dossierId: string, session: AskSession): void {
  try {
    sessionStorage.setItem(storageKey(dossierId), JSON.stringify(session));
  } catch {
    // optional
  }
}

export function DossierAskSection({ dossierId }: { dossierId: string }) {
  const [conversation, setConversation] = useState<DossierConversation | null>(null);
  const [question, setQuestion] = useState("");
  const [pendingMessageId, setPendingMessageId] = useState<string | null>(null);
  const [message, setMessage] = useState<DossierMessage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [hydrating, setHydrating] = useState(true);
  const pollTimer = useRef<number | null>(null);
  const pollMessageRef = useRef<
    ((conversationId: string, messageId: string) => Promise<void>) | null
  >(null);

  const stopPoll = useCallback(() => {
    if (pollTimer.current != null) {
      window.clearTimeout(pollTimer.current);
      pollTimer.current = null;
    }
  }, []);

  const pollMessage = useCallback(
    async (conversationId: string, messageId: string) => {
      try {
        const current = await api.dossierConversations.getMessage(
          dossierId,
          conversationId,
          messageId,
        );
        setMessage(current);
        setPendingMessageId(messageId);
        writeSession(dossierId, {
          conversationId,
          messageId,
          title: "Preguntar a Oracle",
        });
        if (["queued", "running"].includes(current.status)) {
          stopPoll();
          pollTimer.current = window.setTimeout(() => {
            void pollMessageRef.current?.(conversationId, messageId);
          }, 2000);
        } else {
          stopPoll();
        }
      } catch (reason) {
        setError(
          reason instanceof ApiError
            ? reason.problem.detail
            : "No se pudo consultar el estado de la respuesta.",
        );
      }
    },
    [dossierId, stopPoll],
  );

  useEffect(() => {
    pollMessageRef.current = pollMessage;
  }, [pollMessage]);

  // Reload-safe rehydrate: conversation + last message from sessionStorage → GET API
  useEffect(() => {
    let cancelled = false;
    const kickoff = window.setTimeout(() => {
      void (async () => {
        setHydrating(true);
        const stored = readSession(dossierId);
        if (!stored?.conversationId) {
          if (!cancelled) setHydrating(false);
          return;
        }
        setConversation({
          id: stored.conversationId,
          dossier_id: dossierId,
          status: "open",
          title: stored.title ?? "Preguntar a Oracle",
        });
        if (stored.messageId) {
          setPendingMessageId(stored.messageId);
          try {
            const current = await api.dossierConversations.getMessage(
              dossierId,
              stored.conversationId,
              stored.messageId,
            );
            if (cancelled) return;
            setMessage(current);
            if (["queued", "running"].includes(current.status)) {
              void pollMessage(stored.conversationId, stored.messageId);
            }
          } catch {
            // Stale session entry; keep UI usable for a new question.
          }
        }
        if (!cancelled) setHydrating(false);
      })();
    }, 0);
    return () => {
      cancelled = true;
      window.clearTimeout(kickoff);
      stopPoll();
    };
  }, [dossierId, pollMessage, stopPoll]);

  async function ensureConversation(): Promise<DossierConversation> {
    if (conversation) return conversation;
    const created = await api.dossierConversations.create(dossierId, {
      title: "Preguntar a Oracle",
    });
    setConversation(created);
    writeSession(dossierId, {
      conversationId: created.id,
      messageId: pendingMessageId,
      title: created.title,
    });
    return created;
  }

  async function onSubmit(event: FormEvent) {
    event.preventDefault();
    const text = question.trim();
    if (!text) return;
    setBusy(true);
    setError(null);
    try {
      const thread = await ensureConversation();
      const accepted = await api.dossierConversations.enqueueMessage(
        dossierId,
        thread.id,
        { content_text: text },
        idempotencyKey(`ask-${dossierId}-${Date.now()}`),
      );
      setPendingMessageId(accepted.message_id);
      writeSession(dossierId, {
        conversationId: thread.id,
        messageId: accepted.message_id,
        title: thread.title,
      });
      setQuestion("");
      toast.success("Pregunta registrada", {
        description: "La respuesta se generará en segundo plano (202).",
      });
      void pollMessage(thread.id, accepted.message_id);
    } catch (reason) {
      setError(
        reason instanceof ApiError
          ? reason.problem.detail
          : "No se pudo encolar la pregunta.",
      );
    } finally {
      setBusy(false);
    }
  }

  if (hydrating) {
    return (
      <div className="dossier-loading" role="status" aria-label="Restaurando conversación">
        <span />
        <span />
        <span />
      </div>
    );
  }

  return (
    <div className="dossier-section-page">
      <header className="vector-panel">
        <div>
          <span className="section-kicker">Asistente del expediente</span>
          <h1>Preguntar a Oracle</h1>
          <p>
            La pregunta se persiste antes de encolar el job. No modifica la intención ni los
            hechos de memoria. Tras recargar se recupera el último mensaje desde la API.
          </p>
        </div>
      </header>

      <section className="vector-panel">
        <form onSubmit={(event) => void onSubmit(event)} className="stack-form">
          <label className="field full">
            <span>Tu pregunta</span>
            <textarea
              required
              minLength={1}
              maxLength={8000}
              rows={4}
              value={question}
              onChange={(event) => setQuestion(event.target.value)}
              placeholder="Ej. ¿Qué adjudicatario concentra el CPV 35400000 en este expediente?"
            />
          </label>
          <AsyncActionButton
            type="submit"
            className="vector-primary"
            loading={busy}
            disabled={busy || !question.trim()}
          >
            <Send size={15} /> Enviar pregunta
          </AsyncActionButton>
        </form>
        {error ? (
          <p role="alert" className="form-error">
            {error}
          </p>
        ) : null}
      </section>

      <section className="vector-panel" aria-live="polite">
        <header>
          <h2>
            <MessageSquare size={16} /> Estado
          </h2>
          {pendingMessageId && conversation ? (
            <button
              type="button"
              className="vector-secondary"
              onClick={() => void pollMessage(conversation.id, pendingMessageId)}
            >
              <RefreshCw size={14} /> Actualizar
            </button>
          ) : null}
        </header>
        {!message ? (
          <p>
            Aún no hay respuestas. Tras enviar, el estado se conserva al recargar mediante
            la conversación y el message_id guardados y un GET a la API.
          </p>
        ) : (
          <article className="ask-result">
            <p>
              <strong>Estado:</strong> {message.status}
              {message.background_job_id ? ` · job ${message.background_job_id}` : ""}
            </p>
            <p>
              <strong>Pregunta:</strong> {message.content_text}
            </p>
            <p className="muted">
              <strong>Timestamps:</strong>{" "}
              {message.created_at ? `creado ${String(message.created_at)}` : "—"}
              {message.updated_at ? ` · actualizado ${String(message.updated_at)}` : ""}
            </p>
            {message.status === "succeeded" ? (
              <div className="stack-form">
                {Boolean(message.answer_payload?.degraded) ? (
                  <p role="status" className="form-error">
                    Respuesta degradada: la cobertura de memoria reportó fallos o el
                    publicador operó en modo degradado. No se ocultan ausencias.
                  </p>
                ) : null}
                <div>
                  <strong>Respuesta</strong>
                  <pre className="answer-block">
                    {String(message.answer_payload?.text ?? "Sin texto")}
                  </pre>
                </div>
                {Array.isArray(message.answer_payload?.citations) &&
                message.answer_payload.citations.length > 0 ? (
                  <div>
                    <strong>Citas</strong>
                    <ul className="citation-list">
                      {message.answer_payload.citations.map(
                        (citation: { evidence_id?: string; quote?: string }, idx: number) => {
                          const eid = String(citation?.evidence_id ?? "");
                          return (
                            <li key={`${eid}-${idx}`}>
                              <a
                                href={`#evidence-${eid}`}
                                className="citation-link"
                                title="Abrir evidencia materializada del expediente"
                              >
                                {eid.slice(0, 8)}…
                              </a>
                              {citation?.quote ? (
                                <span className="citation-quote"> — {String(citation.quote)}</span>
                              ) : null}
                            </li>
                          );
                        },
                      )}
                    </ul>
                  </div>
                ) : null}
                {Array.isArray(message.answer_payload?.conflicts) &&
                message.answer_payload.conflicts.length > 0 ? (
                  <div role="status">
                    <strong>Contradicciones</strong>
                    <ul>
                      {message.answer_payload.conflicts.map(
                        (row: { statement?: string }, idx: number) => (
                          <li key={`conflict-${idx}`}>{String(row?.statement ?? row)}</li>
                        ),
                      )}
                    </ul>
                  </div>
                ) : null}
                {message.coverage_manifest || message.answer_payload?.coverage_summary ? (
                  <div>
                    <strong>Cobertura</strong>
                    <CoverageSummary
                      coverage={
                        (message.answer_payload?.coverage_summary as Record<string, unknown>) ||
                        (message.coverage_manifest as Record<string, unknown>) ||
                        {}
                      }
                      mode={String(message.answer_payload?.memory_mode ?? "")}
                    />
                  </div>
                ) : null}
              </div>
            ) : null}
            {message.error_message ? (
              <p role="alert">Error: {message.error_message}</p>
            ) : null}
            {conversation && pendingMessageId ? (
              <div className="inline-actions">
                <button
                  type="button"
                  className="vector-secondary"
                  onClick={() => void pollMessage(conversation.id, pendingMessageId)}
                >
                  <RefreshCw size={14} /> Actualizar
                </button>
                {["queued", "running"].includes(message.status) &&
                message.background_job_id ? (
                  <AsyncActionButton
                    type="button"
                    className="vector-secondary"
                    onClick={() =>
                      void (async () => {
                        try {
                          // Cooperative cancel via durable job fencing (If-Match version=0 best-effort).
                          await api.jobs.cancel(String(message.background_job_id), 0);
                          void pollMessage(conversation.id, pendingMessageId);
                        } catch {
                          void pollMessage(conversation.id, pendingMessageId);
                        }
                      })()
                    }
                  >
                    Cancelar
                  </AsyncActionButton>
                ) : null}
              </div>
            ) : null}
          </article>
        )}
      </section>
    </div>
  );
}

function CoverageSummary({
  coverage,
  mode,
}: {
  coverage: Record<string, unknown>;
  mode: string;
}) {
  const count = (value: unknown): number => {
    if (Array.isArray(value)) return value.length;
    if (typeof value === "number") return value;
    return 0;
  };
  return (
    <ul className="coverage-summary">
      {mode ? (
        <li>
          <strong>Modo:</strong> {mode}
        </li>
      ) : null}
      <li>
        <strong>Consultadas/solicitadas:</strong> {count(coverage.requested)}
      </li>
      <li>
        <strong>Usadas:</strong> {count(coverage.used)}
      </li>
      <li>
        <strong>Fallidas:</strong> {count(coverage.failed)}
      </li>
      <li>
        <strong>Excluidas:</strong> {count(coverage.excluded)}
      </li>
      <li>
        <strong>Truncadas:</strong> {count(coverage.truncated)}
      </li>
    </ul>
  );
}
