/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { PliegoPcapPanel } from "./pliego-pcap-panel";

const pliegoAcquisition = vi.fn();
const uploadPliegoPcap = vi.fn();

vi.mock("@oracle/api-client", () => {
  class ApiError extends Error {
    status: number;
    problem: { code: string; detail: string; title?: string; type?: string; status?: number };
    constructor(
      status: number,
      problem: { code: string; detail: string; title?: string; type?: string; status?: number },
    ) {
      super(problem.detail);
      this.name = "ApiError";
      this.status = status;
      this.problem = problem;
    }
  }
  return {
    ApiError,
    api: {
      dossierProcurement: {
        pliegoAcquisition: (...args: unknown[]) => pliegoAcquisition(...args),
        uploadPliegoPcap: (...args: unknown[]) => uploadPliegoPcap(...args),
      },
    },
  };
});

vi.mock("@/components/auth/auth-boundary", () => ({
  PermissionGate: ({ children }: { children: React.ReactNode }) => <>{children}</>,
}));

vi.mock("@/components/reporting/job-progress", () => ({
  JobProgress: () => <div data-testid="job-progress">job</div>,
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), error: vi.fn() },
}));

const emptyAcquisition = {
  dossier_id: "d1",
  overall_status: "no_disponible" as const,
  overall_reason_code: "signal_documents_empty",
  overall_reason: "Signal no entregó documentos CODICE; suba el PCAP manualmente",
  manual_upload_offered: true,
  manual_upload_priority: true,
  cta: {
    label: "Subir PCAP",
    action: "upload_manual_pcap",
    hint: "La descarga automática es best-effort.",
  },
  signal_document_refs: 0,
  pins_without_documents: 1,
  preferred_document: null,
  acquisitions: [
    {
      key: "pin:x:empty",
      status: "no_disponible",
      reason: "Signal no entregó documentos CODICE; suba el PCAP manualmente",
      manual_upload_offered: true,
    },
  ],
};

const failAcquisition = {
  ...emptyAcquisition,
  overall_status: "no_disponible" as const,
  overall_reason: "Descarga bloqueada (HTTP 403/WAF). Suba el PCAP manualmente.",
  signal_document_refs: 1,
  pins_without_documents: 0,
  acquisitions: [
    {
      key: "uri:https://x",
      status: "no_disponible",
      reason_code: "http_403_waf",
      reason: "Descarga bloqueada (HTTP 403/WAF). Suba el PCAP manualmente.",
      file_name: "PCAP.pdf",
      manual_upload_offered: true,
    },
  ],
};

const partialAcquisition = {
  ...emptyAcquisition,
  overall_status: "extracto_parcial" as const,
  overall_reason: "análisis sobre extracto parcial; no es el PCAP completo",
  signal_document_refs: 1,
  pins_without_documents: 0,
  acquisitions: [
    {
      key: "uri:https://x",
      status: "extracto_parcial",
      reason: "análisis sobre extracto parcial",
      file_name: "extracto.txt",
      manual_upload_offered: true,
    },
  ],
};

describe("PliegoPcapPanel G-11", () => {
  afterEach(() => {
    cleanup();
    vi.clearAllMocks();
  });

  beforeEach(() => {
    pliegoAcquisition.mockResolvedValue(emptyAcquisition);
    uploadPliegoPcap.mockResolvedValue({
      document: {
        id: "doc-1",
        dossier_id: "d1",
        filename: "PCAP.pdf",
        status: "queued",
      },
      job_id: "job-1",
      acquisition_status: "subido",
      message: "PCAP recibido. Oracle lo procesa en segundo plano.",
      pliego_acquisition: {
        ...emptyAcquisition,
        overall_status: "subido",
        preferred_document: {
          id: "doc-1",
          filename: "PCAP.pdf",
          status: "queued",
        },
      },
    });
  });

  it("documents vacío → CTA Subir PCAP visible", async () => {
    render(<PliegoPcapPanel dossierId="d1" />);
    await waitFor(() => {
      expect(screen.getByTestId("pliego-pcap-status").textContent).toMatch(/No disponible/i);
    });
    expect(screen.getByText("Subir PCAP")).toBeTruthy();
    expect(screen.getByTestId("pliego-pcap-cta")).toBeTruthy();
    expect(screen.getByTestId("pliego-pcap-waf-hint")).toBeTruthy();
  });

  it("fallo WAF → CTA + mensaje honesto", async () => {
    pliegoAcquisition.mockResolvedValue(failAcquisition);
    render(<PliegoPcapPanel dossierId="d1" />);
    await waitFor(() => {
      expect(screen.getByTestId("pliego-pcap-status").textContent).toMatch(/403|WAF|No disponible/i);
    });
    expect(screen.getByTestId("pliego-pcap-cta")).toBeTruthy();
    expect(screen.getByTestId("pliego-pcap-waf-hint")).toBeTruthy();
  });

  it("estado parcial honesto", async () => {
    pliegoAcquisition.mockResolvedValue(partialAcquisition);
    render(<PliegoPcapPanel dossierId="d1" />);
    await waitFor(() => {
      expect(screen.getByTestId("pliego-pcap-partial")).toBeTruthy();
    });
    expect(screen.getByTestId("pliego-pcap-status").textContent).toMatch(/Extracto parcial/i);
  });

  it("subida → procesado (job + mensaje)", async () => {
    render(<PliegoPcapPanel dossierId="d1" />);
    await waitFor(() => expect(screen.getByTestId("pliego-pcap-cta")).toBeTruthy());
    const input = screen.getByTestId("pliego-pcap-input") as HTMLInputElement;
    const file = new File(["%PDF-1.4"], "PCAP.pdf", { type: "application/pdf" });
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => {
      expect(uploadPliegoPcap).toHaveBeenCalled();
      expect(screen.getByTestId("pliego-pcap-ok").textContent).toMatch(/PCAP recibido/i);
    });
    expect(screen.getByTestId("job-progress")).toBeTruthy();
  });

  it("error de fichero legible", async () => {
    const { ApiError } = await import("@oracle/api-client");
    uploadPliegoPcap.mockRejectedValue(
      new ApiError(422, {
        type: "about:blank",
        title: "Error",
        status: 422,
        detail: "El archivo supera el límite.",
        code: "document_rejected",
        instance: "/api/v1/dossiers/d1/pliego-pcap",
        request_id: "test-req",
      }),
    );
    render(<PliegoPcapPanel dossierId="d1" />);
    await waitFor(() => expect(screen.getByTestId("pliego-pcap-cta")).toBeTruthy());
    const input = screen.getByTestId("pliego-pcap-input") as HTMLInputElement;
    const file = new File(["x"], "bad.exe", { type: "application/octet-stream" });
    fireEvent.change(input, { target: { files: [file] } });
    await waitFor(() => {
      expect(screen.getByTestId("pliego-pcap-error").textContent).toMatch(/límite|formato|válido/i);
    });
  });
});
