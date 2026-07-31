import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DossierAskSection } from "./dossier-ask-section";

const createConversation = vi.fn();
const enqueueMessage = vi.fn();
const getMessage = vi.fn();

vi.mock("@oracle/api-client", () => ({
  ApiError: class ApiError extends Error {
    problem = { detail: "fallo" };
  },
  api: {
    dossierConversations: {
      create: (...args: unknown[]) => createConversation(...args),
      enqueueMessage: (...args: unknown[]) => enqueueMessage(...args),
      getMessage: (...args: unknown[]) => getMessage(...args),
    },
  },
}));

vi.mock("@/components/ui/async-action-button", () => ({
  AsyncActionButton: ({
    children,
    busy: _busy,
    ...props
  }: React.ButtonHTMLAttributes<HTMLButtonElement> & { busy?: boolean }) => (
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
    sessionStorage.clear();
  });

  it("encola pregunta con 202 y consulta estado", async () => {
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
  });
});
