import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DossierCustomBriefSection } from "./dossier-custom-brief-section";

const createBrief = vi.fn();
const getBrief = vi.fn();
const listBriefs = vi.fn();

vi.mock("@oracle/api-client", () => ({
  ApiError: class ApiError extends Error {
    problem = { detail: "fallo brief" };
  },
  api: {
    customBriefs: {
      create: (...args: unknown[]) => createBrief(...args),
      get: (...args: unknown[]) => getBrief(...args),
      list: (...args: unknown[]) => listBriefs(...args),
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
  idempotencyKey: () => "idem-brief-key-12345678",
}));

const proposedBrief = {
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
};

describe("DossierCustomBriefSection", () => {
  afterEach(() => {
    cleanup();
    createBrief.mockReset();
    getBrief.mockReset();
    listBriefs.mockReset();
    sessionStorage.clear();
  });

  it("crea brief 202 y hace poll hasta plan proposed", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    listBriefs.mockResolvedValue({ items: [] });
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
      .mockResolvedValue(proposedBrief);

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
      expect(screen.getByText("Plan propuesto")).toBeInTheDocument(),
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

    render(<DossierCustomBriefSection dossierId="d1" />);

    await waitFor(() => expect(getBrief).toHaveBeenCalledWith("d1", "r-reload"));
    await waitFor(() =>
      expect(screen.getByText("Plan propuesto")).toBeInTheDocument(),
    );
    expect(screen.getByText(/Encargo restaurado/)).toBeInTheDocument();
    expect(screen.getByText("Siguientes acciones")).toBeInTheDocument();
    expect(createBrief).not.toHaveBeenCalled();
    expect(listBriefs).not.toHaveBeenCalled();
  });

  it("recupera el último brief desde la API si se pierde sessionStorage", async () => {
    sessionStorage.clear();
    listBriefs.mockResolvedValue({
      items: [
        {
          id: "r-api",
          tenant_id: "t",
          dossier_id: "d1",
          title: "Brief",
          status: "draft",
          report_type: "custom_assistant",
          template_key: "custom_assistant_brief",
          template_version: "v1",
          generation_version: 1,
          brief_request: "Encargo durable sin sessionStorage",
          plan_status: "proposed",
          proposed_plan: { sections: [{ title: "Sección durable" }] },
          background_job_id: "j-api",
          requested_by_user_id: "u1",
        },
      ],
    });

    render(<DossierCustomBriefSection dossierId="d1" />);

    await waitFor(() => expect(listBriefs).toHaveBeenCalledWith("d1", { limit: 1 }));
    await waitFor(() =>
      expect(screen.getByText("Plan propuesto")).toBeInTheDocument(),
    );
    expect(screen.getByText(/Encargo durable sin sessionStorage/)).toBeInTheDocument();
    expect(screen.getByText("Sección durable")).toBeInTheDocument();
    expect(getBrief).not.toHaveBeenCalled();
    const stored = JSON.parse(sessionStorage.getItem("oracle:dossier-brief:d1") ?? "{}");
    expect(stored.reportId).toBe("r-api");
  });

  it("muestra error de carga del brief (sessionStorage stale → API vacía)", async () => {
    sessionStorage.setItem(
      "oracle:dossier-brief:d1",
      JSON.stringify({ reportId: "r-bad" }),
    );
    getBrief.mockRejectedValue(new Error("red"));
    listBriefs.mockResolvedValue({ items: [] });
    render(<DossierCustomBriefSection dossierId="d1" />);
    // Failed rehydrate should leave form usable without hanging
    await waitFor(() =>
      expect(screen.getByLabelText("Encargo del informe")).toBeInTheDocument(),
    );
  });
});
