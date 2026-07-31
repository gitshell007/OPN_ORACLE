import { cleanup, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DossierActivitySection } from "./dossier-activity-section";

const getActivity = vi.fn();

vi.mock("@oracle/api-client", () => ({
  ApiError: class ApiError extends Error {
    problem = { detail: "fallo api" };
  },
  api: {
    dossierActivity: {
      get: (...args: unknown[]) => getActivity(...args),
    },
  },
}));

describe("DossierActivitySection", () => {
  afterEach(() => {
    cleanup();
    getActivity.mockReset();
  });

  it("carga el read model y muestra filas", async () => {
    getActivity.mockResolvedValue({
      dossier_id: "d1",
      intent: { schema_key: "market" },
      requirements: [],
      offerings: [],
      summary: { total: 1, by_state: { active: 1 }, by_kind: { signal_monitor: 1 } },
      items: [
        {
          kind: "signal_monitor",
          id: "m1",
          title: "Radar ES",
          product_state: "active",
          cadence: "daily",
          last_error: null,
        },
      ],
      pagination: { limit: 100, offset: 0, total: 1 },
    });

    render(<DossierActivitySection dossierId="d1" />);
    await waitFor(() => expect(screen.getByText("Radar ES")).toBeInTheDocument());
    expect(getActivity).toHaveBeenCalledWith("d1", { limit: 100, offset: 0 });
    expect(screen.getAllByText("Activo").length).toBeGreaterThan(0);
  });

  it("muestra error recuperable", async () => {
    getActivity.mockRejectedValue(new Error("red"));
    render(<DossierActivitySection dossierId="d1" />);
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/No se pudo cargar/),
    );
  });
});
