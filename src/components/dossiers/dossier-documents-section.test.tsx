import { cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  upload: vi.fn(),
  search: vi.fn(),
  reprocess: vi.fn(),
  remove: vi.fn(),
  createEvidence: vi.fn(),
  replace: vi.fn(),
  params: new URLSearchParams(),
  success: vi.fn(),
}));

vi.mock("next/navigation", () => ({
  usePathname: () => "/app/dossiers/dossier-1/documents",
  useRouter: () => ({ replace: mocks.replace }),
  useSearchParams: () => mocks.params,
}));
vi.mock("@oracle/api-client", () => ({
  ApiError: class ApiError extends Error {},
  api: { documents: {
    list: mocks.list,
    upload: mocks.upload,
    search: mocks.search,
    reprocess: mocks.reprocess,
    remove: mocks.remove,
    createEvidence: mocks.createEvidence,
  } },
}));
vi.mock("sonner", () => ({ toast: { success: mocks.success } }));
vi.mock("@/components/auth/auth-boundary", () => ({
  PermissionGate: ({ children }: { children: React.ReactNode }) => children,
}));

import { DossierDocumentsSection } from "./dossier-documents-section";

const document = {
  id: "document-1",
  dossier_id: "dossier-1",
  filename: "convocatoria.pdf",
  media_type: "application/pdf",
  byte_size: 2048,
  checksum: "aabbcc",
  classification: "internal" as const,
  status: "ready" as const,
  scan_status: "clean",
  safe_error_code: null,
  current_version_id: "version-1",
  version: 2,
  created_at: "2026-07-11T08:00:00Z",
  updated_at: "2026-07-11T09:00:00Z",
};

describe("DossierDocumentsSection", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.params = new URLSearchParams();
    mocks.list.mockResolvedValue({ items: [document] });
    mocks.search.mockResolvedValue({ items: [] });
  });
  afterEach(cleanup);

  it("consume el deep link selected y expone integridad y descarga", async () => {
    mocks.params = new URLSearchParams("selected=document-1");
    render(<DossierDocumentsSection dossierId="dossier-1" />);
    const detail = await screen.findByRole("dialog", { name: "convocatoria.pdf" });
    expect(within(detail).getByText(/Huella de integridad:/)).toBeVisible();
    expect(within(detail).getByRole("link", { name: /Descargar/ })).toHaveAttribute(
      "href",
      "/api/v1/documents/document-1/download",
    );
  });

  it("envía una búsqueda acotada al expediente", async () => {
    render(<DossierDocumentsSection dossierId="dossier-1" />);
    await screen.findAllByText("convocatoria.pdf");
    fireEvent.change(screen.getByLabelText("Buscar dentro de las fuentes"), {
      target: { value: "plazo oficial" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Buscar" }));
    await waitFor(() => expect(mocks.search).toHaveBeenCalledWith("dossier-1", "plazo oficial"));
  });
});
