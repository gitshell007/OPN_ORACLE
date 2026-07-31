"use client";

import {
  ApiError,
  api,
  type DossierConversation,
  type DossierMessage,
} from "@oracle/api-client";
import { MessageSquare, RefreshCw, Send } from "lucide-react";
import { FormEvent, useCallback, useEffect, useState } from "react";
import { toast } from "sonner";
import { AsyncActionButton } from "@/components/ui/async-action-button";
import { idempotencyKey } from "@/components/reporting/reporting-utils";

const STORAGE_PREFIX = "oracle:dossier-ask:";

function storageKey(dossierId: string): string {
  return `${STORAGE_PREFIX}${dossierId}:conversation`;
}

export function DossierAskSection({ dossierId }: { dossierId: string }) {
  const [conversation, setConversation] = useState<DossierConversation | null>(null);
  const [question, setQuestion] = useState("");
  const [pendingMessageId, setPendingMessageId] = useState<string | null>(null);
  const [message, setMessage] = useState<DossierMessage | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    try {
      const raw = sessionStorage.getItem(storageKey(dossierId));
      if (raw) {
        const parsed = JSON.parse(raw) as DossierConversation;
        if (parsed?.id) setConversation(parsed);
      }
    } catch {
      // sessionStorage is convenience only; durable state is the API.
    }
  }, [dossierId]);

  const pollMessage = useCallback(
    async (conversationId: string, messageId: string) => {
      try {
        const current = await api.dossierConversations.getMessage(
          dossierId,
          conversationId,
          messageId,
        );
        setMessage(current);
        if (["queued", "running"].includes(current.status)) {
          window.setTimeout(() => void pollMessage(conversationId, messageId), 2000);
        }
      } catch (reason) {
        setError(
          reason instanceof ApiError
            ? reason.problem.detail
            : "No se pudo consultar el estado de la respuesta.",
        );
      }
    },
    [dossierId],
  );

  async function ensureConversation(): Promise<DossierConversation> {
    if (conversation) return conversation;
    const created = await api.dossierConversations.create(dossierId, {
      title: "Preguntar a Oracle",
    });
    setConversation(created);
    try {
      sessionStorage.setItem(storageKey(dossierId), JSON.stringify(created));
    } catch {
      // optional
    }
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

  return (
    <div className="dossier-section-page">
      <header className="vector-panel">
        <div>
          <span className="section-kicker">Asistente del expediente</span>
          <h1>Preguntar a Oracle</h1>
          <p>
            La pregunta se persiste antes de encolar el job. No modifica la intención ni los
            hechos de memoria.
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
          <p>Aún no hay respuestas en esta sesión. Tras enviar, el estado se conserva al recargar si el mensaje existe en API.</p>
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
