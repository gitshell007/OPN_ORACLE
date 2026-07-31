import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DossierCustomBriefSection } from "./dossier-custom-brief-section";

const createBrief = vi.fn();
const getBrief = vi.fn();
const jobsGet = vi.fn();
const jobsCancel = vi.fn();
const jobsRetry = vi.fn();

vi.mock("@oracle/api-client", () => ({
  ApiError: class ApiError extends Error {
    problem = { detail: "fallo brief" };
    status = 409;
  },
  api: {
    customBriefs: {
      create: (...args: unknown[]) => createBrief(...args),
      get: (...args: unknown[]) => getBrief(...args),
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
  idempotencyKey: () => "idem-brief-key-12345678",
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn(), message: vi.fn(), dismiss: vi.fn() },
}));

describe("DossierCustomBriefSection", () => {
  afterEach(() => {
    cleanup();
    createBrief.mockReset();
    getBrief.mockReset();
    jobsGet.mockReset();
    jobsCancel.mockReset();
    jobsRetry.mockReset();
    sessionStorage.clear();
  });

  it("crea brief 202 y hace poll hasta plan proposed", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    createBrief.mockResolvedValue({
      job_id: "j1",
      report_id: "r1",
      plan_status: "draft",
    });
    getBrief
      .mockResolvedValueOnce({
        id: "r1",
        tenant_id: "t",
        dossier_id: "d1",
        title: "Brief",
        status: "draft",
        report_type: "custom_assistant",
        template_key: "custom_assistant_brief",
        template_version: "v1",
        generation_version: 1,
        brief_request: "Encargo de prueba",
        plan_status: "draft",
        background_job_id: "j1",
        requested_by_user_id: "u1",
      })
      .mockResolvedValue({
        id: "r1",
        tenant_id: "t",
        dossier_id: "d1",
        title: "Brief",
        status: "draft",
        report_type: "custom_assistant",
        template_key: "custom_assistant_brief",
        template_version: "v1",
        generation_version: 1,
        brief_request: "Encargo de prueba",
        plan_status: "proposed",
        proposed_plan: {
          sections: [{ title: "Resumen ejecutivo" }, { title: "Evidencias y fuentes" }],
        },
        background_job_id: "j1",
        requested_by_user_id: "u1",
      });
    jobsGet.mockResolvedValue({
      id: "j1",
      status: "succeeded",
      version: 2,
      progress: 100,
      retryable: false,
      cancel_requested: false,
      tenant_id: "t",
      job_type: "oracle.report.custom_brief.plan",
      queue: "ai",
    });

    render(<DossierCustomBriefSection dossierId="d1" />);
    await waitFor(() =>
      expect(screen.getByLabelText("Encargo del informe")).toBeInTheDocument(),
    );
    fireEvent.change(screen.getByLabelText("Encargo del informe"), {
      target: { value: "Encargo de prueba" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Crear brief y planificar/i }));

    await waitFor(() => expect(createBrief).toHaveBeenCalled());
    await waitFor(() => expect(getBrief).toHaveBeenCalled());
    await vi.advanceTimersByTimeAsync(2100);
    await waitFor(() =>
      expect(screen.getByText("Plan propuesto (revisar)")).toBeInTheDocument(),
    );
    expect(screen.getByText("Resumen ejecutivo")).toBeInTheDocument();
    const stored = JSON.parse(sessionStorage.getItem("oracle:dossier-brief:d1") ?? "{}");
    expect(stored.reportId).toBe("r1");
    vi.useRealTimers();
  });

  it("rehidrata brief al recargar y muestra plan proposed", async () => {
    sessionStorage.setItem(
      "oracle:dossier-brief:d1",
      JSON.stringify({ reportId: "r-reload", jobId: "j-reload" }),
    );
    getBrief.mockResolvedValue({
      id: "r-reload",
      tenant_id: "t",
      dossier_id: "d1",
      title: "Brief",
      status: "draft",
      report_type: "custom_assistant",
      template_key: "custom_assistant_brief",
      template_version: "v1",
      generation_version: 1,
      brief_request: "Encargo restaurado",
      plan_status: "proposed",
      proposed_plan: { sections: [{ title: "Siguientes acciones" }] },
      background_job_id: "j-reload",
      requested_by_user_id: "u1",
    });
    jobsGet.mockResolvedValue({
      id: "j-reload",
      status: "succeeded",
      version: 1,
      progress: 100,
      retryable: false,
      cancel_requested: false,
      tenant_id: "t",
      job_type: "oracle.report.custom_brief.plan",
      queue: "ai",
    });

    render(<DossierCustomBriefSection dossierId="d1" />);

    await waitFor(() => expect(getBrief).toHaveBeenCalledWith("d1", "r-reload"));
    await waitFor(() =>
      expect(screen.getByText("Plan propuesto (revisar)")).toBeInTheDocument(),
    );
    expect(screen.getByText(/Encargo restaurado/)).toBeInTheDocument();
    expect(screen.getByText("Siguientes acciones")).toBeInTheDocument();
    expect(createBrief).not.toHaveBeenCalled();
  });

  it("muestra error de carga del brief", async () => {
    sessionStorage.setItem(
      "oracle:dossier-brief:d1",
      JSON.stringify({ reportId: "r-bad" }),
    );
    getBrief.mockRejectedValue(new Error("red"));
    render(<DossierCustomBriefSection dossierId="d1" />);
    // Failed rehydrate should leave form usable without hanging
    await waitFor(() =>
      expect(screen.getByLabelText("Encargo del informe")).toBeInTheDocument(),
    );
  });

  it("cancela el job de planificación con If-Match de versión", async () => {
    sessionStorage.setItem(
      "oracle:dossier-brief:d1",
      JSON.stringify({ reportId: "r1", jobId: "j1" }),
    );
    getBrief.mockResolvedValue({
      id: "r1",
      tenant_id: "t",
      dossier_id: "d1",
      title: "Brief",
      status: "draft",
      report_type: "custom_assistant",
      template_key: "custom_assistant_brief",
      template_version: "v1",
      generation_version: 1,
      brief_request: "Encargo cancelable",
      plan_status: "draft",
      background_job_id: "j1",
      requested_by_user_id: "u1",
    });
    jobsGet.mockResolvedValue({
      id: "j1",
      status: "running",
      version: 2,
      progress: 10,
      retryable: true,
      cancel_requested: false,
      tenant_id: "t",
      job_type: "oracle.report.custom_brief.plan",
      queue: "ai",
      stage: "planning",
    });
    jobsCancel.mockResolvedValue({
      id: "j1",
      status: "running",
      version: 3,
      progress: 10,
      retryable: true,
      cancel_requested: true,
      tenant_id: "t",
      job_type: "oracle.report.custom_brief.plan",
      queue: "ai",
      stage: "planning",
    });

    render(<DossierCustomBriefSection dossierId="d1" />);
    const cancel = await screen.findByTestId("job-cancel");
    fireEvent.click(cancel);
    await waitFor(() => expect(jobsCancel).toHaveBeenCalledWith("j1", 2));
    expect(screen.getByText(/Encargo cancelable/)).toBeInTheDocument();
  });
});