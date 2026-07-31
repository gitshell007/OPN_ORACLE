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
    fireEvent.change(screen.getByLabelText("Tu pregunta"), {
      target: { value: "¿Qué sabemos?" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Enviar pregunta/i }));

    await waitFor(() => expect(enqueueMessage).toHaveBeenCalled());
    expect(createConversation).toHaveBeenCalledWith("d1", { title: "Preguntar a Oracle" });
    await waitFor(() => expect(screen.getByText("Respuesta de prueba")).toBeInTheDocument());
  });
});
