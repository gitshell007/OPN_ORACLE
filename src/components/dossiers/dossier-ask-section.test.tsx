import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DossierAskSection } from "./dossier-ask-section";

const createConversation = vi.fn();
const enqueueMessage = vi.fn();
const getMessage = vi.fn();
const listConversations = vi.fn();
const listMessages = vi.fn();

vi.mock("@oracle/api-client", () => ({
  ApiError: class ApiError extends Error {
    problem = { detail: "fallo" };
  },
  api: {
    dossierConversations: {
      create: (...args: unknown[]) => createConversation(...args),
      enqueueMessage: (...args: unknown[]) => enqueueMessage(...args),
      getMessage: (...args: unknown[]) => getMessage(...args),
      list: (...args: unknown[]) => listConversations(...args),
      listMessages: (...args: unknown[]) => listMessages(...args),
    },
  },
}));

vi.mock("@/components/ui/async-action-button", () => ({
  AsyncActionButton: ({
    children,
    loading: _loading,
    ...props
  }: React.ButtonHTMLAttributes<HTMLButtonElement> & { loading?: boolean }) => (
    <button type="submit" {...props}>
      {children}
    </button>
  ),
}));

vi.mock("@/components/reporting/reporting-utils", () => ({
  idempotencyKey: () => "idem-test-key-123456",
}));

describe("DossierAskSection", () => {
  afterEach(() => {
    cleanup();
    createConversation.mockReset();
    enqueueMessage.mockReset();
    getMessage.mockReset();
    listConversations.mockReset();
    listMessages.mockReset();
    sessionStorage.clear();
  });

  it("encola pregunta con 202 y consulta estado", async () => {
    listConversations.mockResolvedValue({ items: [] });
    createConversation.mockResolvedValue({
      id: "c1",
      dossier_id: "d1",
      status: "open",
      title: "Preguntar a Oracle",
    });
    enqueueMessage.mockResolvedValue({ job_id: "j1", message_id: "m1" });
    getMessage.mockResolvedValue({
      id: "m1",
      conversation_id: "c1",
      dossier_id: "d1",
      role: "user",
      status: "succeeded",
      sequence: 1,
      content_text: "¿Qué sabemos?",
      answer_payload: { text: "Respuesta de prueba", mutates_intent: false },
    });

    render(<DossierAskSection dossierId="d1" />);
    await waitFor(() => expect(screen.getByLabelText("Tu pregunta")).toBeInTheDocument());
    fireEvent.change(screen.getByLabelText("Tu pregunta"), {
      target: { value: "¿Qué sabemos?" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Enviar pregunta/i }));

    await waitFor(() => expect(enqueueMessage).toHaveBeenCalled());
    expect(createConversation).toHaveBeenCalledWith("d1", { title: "Preguntar a Oracle" });
    await waitFor(() => expect(screen.getByText("Respuesta de prueba")).toBeInTheDocument());
    const stored = JSON.parse(sessionStorage.getItem("oracle:dossier-ask:d1") ?? "{}");
    expect(stored.conversationId).toBe("c1");
    expect(stored.messageId).toBe("m1");
  });

  it("rehidrata message y reanuda poll al recargar desde sessionStorage", async () => {
    sessionStorage.setItem(
      "oracle:dossier-ask:d1",
      JSON.stringify({ conversationId: "c-reload", messageId: "m-reload" }),
    );
    getMessage.mockResolvedValue({
      id: "m-reload",
      conversation_id: "c-reload",
      dossier_id: "d1",
      role: "user",
      status: "succeeded",
      sequence: 1,
      content_text: "Pregunta restaurada",
      answer_payload: { text: "Respuesta restaurada", mutates_intent: false },
    });

    render(<DossierAskSection dossierId="d1" />);

    await waitFor(() =>
      expect(getMessage).toHaveBeenCalledWith("d1", "c-reload", "m-reload"),
    );
    await waitFor(() =>
      expect(screen.getByText("Respuesta restaurada")).toBeInTheDocument(),
    );
    expect(screen.getByText(/Pregunta restaurada/)).toBeInTheDocument();
    expect(createConversation).not.toHaveBeenCalled();
    // Fast path must not list when sessionStorage hit succeeds.
    expect(listConversations).not.toHaveBeenCalled();
  });

  it("recupera la última conversación desde la API si se pierde sessionStorage (cierre de pestaña)", async () => {
    // Simulate: question already answered in DB, but tab closed → sessionStorage empty.
    sessionStorage.clear();
    listConversations.mockResolvedValue({
      items: [
        {
          id: "c-api",
          dossier_id: "d1",
          status: "open",
          title: "Preguntar a Oracle",
        },
      ],
    });
    listMessages.mockResolvedValue({
      items: [
        {
          id: "m-api",
          conversation_id: "c-api",
          dossier_id: "d1",
          role: "user",
          status: "succeeded",
          sequence: 1,
          content_text: "¿Quién es el administrador único?",
          answer_payload: {
            text: "Respuesta durable tras cerrar pestaña",
            mutates_intent: false,
          },
        },
      ],
    });

    render(<DossierAskSection dossierId="d1" />);

    await waitFor(() =>
      expect(listConversations).toHaveBeenCalledWith("d1", { limit: 1 }),
    );
    await waitFor(() =>
      expect(listMessages).toHaveBeenCalledWith("d1", "c-api", { limit: 1 }),
    );
    await waitFor(() =>
      expect(screen.getByText("Respuesta durable tras cerrar pestaña")).toBeInTheDocument(),
    );
    expect(screen.getByText(/administrador único/)).toBeInTheDocument();
    expect(getMessage).not.toHaveBeenCalled();
    // Convenience cache rewritten from API.
    const stored = JSON.parse(sessionStorage.getItem("oracle:dossier-ask:d1") ?? "{}");
    expect(stored.conversationId).toBe("c-api");
    expect(stored.messageId).toBe("m-api");
  });

  it("reanuda el sondeo si el mensaje recuperado de la API está en queued/running", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    sessionStorage.clear();
    listConversations.mockResolvedValue({
      items: [{ id: "c-run", dossier_id: "d1", status: "open", title: "Preguntar a Oracle" }],
    });
    listMessages.mockResolvedValue({
      items: [
        {
          id: "m-run",
          conversation_id: "c-run",
          dossier_id: "d1",
          role: "user",
          status: "running",
          sequence: 1,
          content_text: "Pregunta en curso",
          answer_payload: {},
        },
      ],
    });
    getMessage
      .mockResolvedValueOnce({
        id: "m-run",
        conversation_id: "c-run",
        dossier_id: "d1",
        role: "user",
        status: "running",
        sequence: 1,
        content_text: "Pregunta en curso",
        answer_payload: {},
      })
      .mockResolvedValue({
        id: "m-run",
        conversation_id: "c-run",
        dossier_id: "d1",
        role: "user",
        status: "succeeded",
        sequence: 1,
        content_text: "Pregunta en curso",
        answer_payload: { text: "Listo tras poll", mutates_intent: false },
      });

    render(<DossierAskSection dossierId="d1" />);

    await waitFor(() => expect(listMessages).toHaveBeenCalled());
    await waitFor(() => expect(screen.getByText(/Pregunta en curso/)).toBeInTheDocument());
    await vi.advanceTimersByTimeAsync(2100);
    await waitFor(() => expect(getMessage).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(2100);
    await waitFor(() => expect(screen.getByText("Listo tras poll")).toBeInTheDocument());
    vi.useRealTimers();
  });

  it("muestra vacío si no hay conversaciones en API ni sessionStorage", async () => {
    sessionStorage.clear();
    listConversations.mockResolvedValue({ items: [] });
    render(<DossierAskSection dossierId="d1" />);
    await waitFor(() => expect(listConversations).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.getByText(/Aún no hay respuestas/)).toBeInTheDocument(),
    );
  });
});
