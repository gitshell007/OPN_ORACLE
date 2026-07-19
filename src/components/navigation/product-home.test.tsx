import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => {
  const can = vi.fn(() => true);
  return {
    home: vi.fn(),
    reports: vi.fn(),
    notifications: vi.fn(),
    jobs: vi.fn(),
    can,
    authValue: { can },
  };
});

vi.mock("@oracle/api-client", () => ({
  ApiError: class ApiError extends Error {},
  api: {
    home: { get: mocks.home },
    reports: { list: mocks.reports },
    notifications: { list: mocks.notifications },
    jobs: { list: mocks.jobs },
  },
}));
vi.mock("@/components/auth/auth-provider", () => ({
  useAuth: () => mocks.authValue,
}));
vi.mock("./create-product-dossier-dialog", () => ({
  CreateProductDossierDialog: () => null,
}));

import { ProductHome } from "./product-home";

const metrics = [
  { key: "dossiers", label: "Expedientes activos", count: 0, href: "/app/dossiers", available: true },
  { key: "signals", label: "Señales nuevas", count: 0, href: "/app/signals", available: true },
];

describe("ProductHome", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    mocks.reports.mockResolvedValue({ data: [] });
    mocks.notifications.mockResolvedValue({ data: [], meta: { unread_count: 0 } });
    mocks.jobs.mockResolvedValue({ data: [] });
  });

  afterEach(cleanup);

  it("muestra un primer paso accionable en vez de métricas vacías", async () => {
    mocks.home.mockResolvedValue({ dossier_total: 0, metrics, attention: [] });
    render(<ProductHome />);

    expect(await screen.findByRole("heading", { name: "Tu primer radar estratégico empieza aquí" })).toBeVisible();
    expect(screen.getByRole("button", { name: "Crear el primer expediente" })).toBeVisible();
    expect(screen.queryByText("Expedientes activos")).not.toBeInTheDocument();
  });

  it("identifica los elementos prioritarios y conserva destinos coherentes", async () => {
    mocks.home.mockResolvedValue({
      dossier_total: 1,
      metrics: [{ ...metrics[0], count: 1 }, { ...metrics[1], count: 1 }],
      attention: [{
        kind: "signals",
        id: "link-1",
        dossier_id: "dossier-1",
        dossier_title: "Expediente industrial",
        title: "Nueva inversión confirmada",
        status: "new",
        score: 67,
        due_at: null,
        updated_at: "2026-07-12T10:00:00Z",
        href: "/app/dossiers/dossier-1/signals",
      }],
    });
    render(<ProductHome />);

    expect(await screen.findByRole("heading", { name: "Trabajo que requiere atención" })).toBeVisible();
    expect(screen.getByText("señal")).toBeVisible();
    expect(screen.getByText("Expediente industrial")).toBeVisible();
    expect(screen.getByText("Nueva")).toBeVisible();
    expect(screen.getByRole("link", { name: "Ver cartera" })).toHaveAttribute("href", "/app/dossiers");
    expect(screen.getByRole("link", { name: /Nueva inversión confirmada/ })).toHaveAttribute(
      "href",
      "/app/dossiers/dossier-1/signals",
    );
    expect(screen.getByRole("link", { name: "Ver procesos" })).toHaveAttribute(
      "href",
      "/app/admin/audit?view=processes",
    );
    expect(mocks.jobs).not.toHaveBeenCalled();
  });
});
