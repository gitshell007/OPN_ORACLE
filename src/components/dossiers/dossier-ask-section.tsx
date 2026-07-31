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
            busy={busy}
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
            {message.status === "succeeded" ? (
              <div>
                <strong>Respuesta</strong>
                <pre className="answer-block">
                  {String(message.answer_payload?.text ?? "Sin texto")}
                </pre>
              </div>
            ) : null}
            {message.error_message ? (
              <p role="alert">Error: {message.error_message}</p>
            ) : null}
          </article>
        )}
      </section>
    </div>
  );
}
