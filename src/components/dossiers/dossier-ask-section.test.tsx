import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DossierAskSection } from "./dossier-ask-section";

const createConversation = vi.fn();
const enqueueMessage = vi.fn();
const getMessage = vi.fn();
const jobsGet = vi.fn();
const jobsCancel = vi.fn();
const jobsRetry = vi.fn();

vi.mock("@oracle/api-client", () => ({
  ApiError: class ApiError extends Error {
    problem = { detail: "fallo" };
    status = 409;
  },
  api: {
    dossierConversations: {
      create: (...args: unknown[]) => createConversation(...args),
      enqueueMessage: (...args: unknown[]) => enqueueMessage(...args),
      getMessage: (...args: unknown[]) => getMessage(...args),
    },
    jobs: {
      get: (...args: unknown[]) => jobsGet(...args),
      cancel: (...args: unknown[]) => jobsCancel(...args),
      retry: (...args: unknown[]) => jobsRetry(...args),
    },
  },
}));

vi.mock("@/components/ui/async-action-button", () => ({
  AsyncActionButton: ({
    children,
    loading: _loading,
    ...props
  }: React.ButtonHTMLAttributes<HTMLButtonElement> & { loading?: boolean }) => (
    <button type={props.type ?? "button"} {...props}>
      {children}
    </button>
  ),
}));

vi.mock("@/components/reporting/reporting-utils", () => ({
  idempotencyKey: () => "idem-test-key-123456",
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), message: vi.fn(), dismiss: vi.fn() },
}));

describe("DossierAskSection", () => {
  afterEach(() => {
    cleanup();
    createConversation.mockReset();
    enqueueMessage.mockReset();
    getMessage.mockReset();
    jobsGet.mockReset();
    jobsCancel.mockReset();
    jobsRetry.mockReset();
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
      background_job_id: "j1",
      answer_payload: { text: "Respuesta de prueba", mutates_intent: false },
    });
    jobsGet.mockResolvedValue({
      id: "j1",
      status: "succeeded",
      version: 2,
      progress: 100,
      retryable: false,
      cancel_requested: false,
      tenant_id: "t",
      job_type: "oracle.dossier_question.answer",
      queue: "ai",
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
      background_job_id: "j-reload",
      answer_payload: { text: "Respuesta restaurada", mutates_intent: false },
    });
    jobsGet.mockResolvedValue({
      id: "j-reload",
      status: "succeeded",
      version: 1,
      progress: 100,
      retryable: false,
      cancel_requested: false,
      tenant_id: "t",
      job_type: "oracle.dossier_question.answer",
      queue: "ai",
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

  it("expone Cancelar versionado mientras el job está en cola", async () => {
    sessionStorage.setItem(
      "oracle:dossier-ask:d1",
      JSON.stringify({ conversationId: "c1", messageId: "m1" }),
    );
    getMessage.mockResolvedValue({
      id: "m1",
      conversation_id: "c1",
      dossier_id: "d1",
      role: "user",
      status: "queued",
      sequence: 1,
      content_text: "Pregunta en cola",
      background_job_id: "j-queued",
    });
    jobsGet.mockResolvedValue({
      id: "j-queued",
      status: "queued",
      version: 3,
      progress: 0,
      retryable: true,
      cancel_requested: false,
      tenant_id: "t",
      job_type: "oracle.dossier_question.answer",
      queue: "ai",
      stage: "queued",
    });
    jobsCancel.mockResolvedValue({
      id: "j-queued",
      status: "cancelled",
      version: 4,
      progress: 0,
      retryable: false,
      cancel_requested: true,
      tenant_id: "t",
      job_type: "oracle.dossier_question.answer",
      queue: "ai",
      stage: "cancelled",
    });

    render(<DossierAskSection dossierId="d1" />);
    const cancel = await screen.findByTestId("job-cancel");
    expect(screen.queryByTestId("job-retry")).toBeNull();
    fireEvent.click(cancel);
    await waitFor(() => expect(jobsCancel).toHaveBeenCalledWith("j-queued", 3));
    // History preserved: question text still shown
    expect(screen.getByText(/Pregunta en cola/)).toBeInTheDocument();
  });

  it("expone Reintentar solo si el job falló y es retryable", async () => {
    sessionStorage.setItem(
      "oracle:dossier-ask:d1",
      JSON.stringify({ conversationId: "c1", messageId: "m1" }),
    );
    getMessage.mockResolvedValue({
      id: "m1",
      conversation_id: "c1",
      dossier_id: "d1",
      role: "user",
      status: "failed",
      sequence: 1,
      content_text: "Pregunta fallida",
      background_job_id: "j-fail",
      error_message: "fallo controlado",
    });
    jobsGet.mockResolvedValue({
      id: "j-fail",
      status: "failed",
      version: 5,
      progress: 0,
      retryable: true,
      cancel_requested: false,
      tenant_id: "t",
      job_type: "oracle.dossier_question.answer",
      queue: "ai",
      error_message: "fallo controlado",
    });
    jobsRetry.mockResolvedValue({
      id: "j-fail",
      status: "queued",
      version: 6,
      progress: 0,
      retryable: true,
      cancel_requested: false,
      tenant_id: "t",
      job_type: "oracle.dossier_question.answer",
      queue: "ai",
      stage: "manual_retry",
    });

    render(<DossierAskSection dossierId="d1" />);
    const retry = await screen.findByTestId("job-retry");
    expect(screen.queryByTestId("job-cancel")).toBeNull();
    fireEvent.click(retry);
    await waitFor(() => expect(jobsRetry).toHaveBeenCalledWith("j-fail", 5));
    expect(screen.getByText(/Pregunta fallida/)).toBeInTheDocument();
  });
});