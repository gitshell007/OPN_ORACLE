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
      intent: {
        id: "intent-1",
        version: 1,
        schema_key: "market",
        schema_version: "v1",
        request_text: "Objetivo: entrar en almacenamiento energético.",
        structured_spec: {},
        status: "accepted",
        content_hash: "hash",
      },
      requirements: [
        {
          id: "requirement-1",
          intent_revision_id: "intent-1",
          class: "market_scan",
          priority: "high",
          question: "¿Qué competidores y oportunidades debemos seguir?",
          decision_to_support: "Entrar o no",
          status: "active",
          alignment_state: "aligned",
        },
      ],
      offerings: [
        {
          id: "offering-1",
          intent_revision_id: "intent-1",
          name: "Integración de baterías",
          description: "Oferta propia",
          status: "active",
        },
      ],
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
    expect(screen.getByText("Memoria aceptada · versión 1")).toBeVisible();
    expect(screen.getByText("Objetivo: entrar en almacenamiento energético.")).toBeVisible();
    expect(screen.getByText("¿Qué competidores y oportunidades debemos seguir?")).toBeVisible();
    expect(screen.getByText("Integración de baterías")).toBeVisible();
  });

  it("muestra error recuperable", async () => {
    getActivity.mockRejectedValue(new Error("red"));
    render(<DossierActivitySection dossierId="d1" />);
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/No se pudo cargar/),
    );
  });

  it("no presenta vigilancia local sin monitor como Activo", async () => {
    getActivity.mockResolvedValue({
      dossier_id: "d1",
      intent: null,
      requirements: [],
      offerings: [],
      summary: {
        total: 1,
        by_state: { needs_attention: 1 },
        by_kind: { surveillance_action: 1 },
      },
      items: [
        {
          kind: "surveillance_action",
          id: "sa1",
          title: "Vigilancia news Nexus/IberVolt",
          product_state: "needs_attention",
          desired_status: "active",
          observed_status: "active",
          cadence: "daily",
          last_error: "SIGNAL-MONITOR-ABSENT: confirmación local sin monitor en Signal",
          target: {
            action_type: "news_mentions",
            degraded: true,
            degraded_reason:
              "SIGNAL-MONITOR-ABSENT: confirmación local sin monitor en Signal; no vigila de verdad",
            signal_monitor_id: null,
            collection_state: "absent",
          },
        },
      ],
      pagination: { limit: 100, offset: 0, total: 1 },
    });

    render(<DossierActivitySection dossierId="d1" />);
    await waitFor(() =>
      expect(screen.getByText("Vigilancia news Nexus/IberVolt")).toBeInTheDocument(),
    );
    expect(screen.getByText("Sin monitor Signal")).toBeVisible();
    expect(screen.getByText("No vigila")).toBeVisible();
    expect(screen.queryByText("Activo")).not.toBeInTheDocument();
  });

  it("no presenta vigilancia con monitor sin recolección como Activo limpio", async () => {
    // Regression SV2-VIGILANCIA-VERDAD: monitor existe pero last_run_at nulo / no recolecta.
    getActivity.mockResolvedValue({
      dossier_id: "d1",
      intent: null,
      requirements: [],
      offerings: [],
      summary: {
        total: 1,
        by_state: { needs_attention: 1 },
        by_kind: { surveillance_action: 1 },
      },
      items: [
        {
          kind: "surveillance_action",
          id: "sa2",
          title: "Vigilancia news Nexus/IberVolt",
          product_state: "needs_attention",
          desired_status: "active",
          observed_status: "active",
          cadence: "daily",
          last_error:
            "SIGNAL-COLLECTION-NEVER: el monitor existe en Signal pero last_run_at es nulo",
          target: {
            action_type: "news_mentions",
            degraded: true,
            degraded_reason:
              "SIGNAL-COLLECTION-NEVER: el monitor existe en Signal pero last_run_at es nulo; no ha recolectado nunca",
            signal_monitor_id: "90e43288-f67d-424a-a3b6-c59ca95eb32c",
            collection_state: "not_collecting",
            provider_health_state: "ok",
            provider_last_run_at: null,
          },
        },
      ],
      pagination: { limit: 100, offset: 0, total: 1 },
    });

    render(<DossierActivitySection dossierId="d1" />);
    await waitFor(() =>
      expect(screen.getByText("Vigilancia news Nexus/IberVolt")).toBeInTheDocument(),
    );
    expect(screen.getByText("Sin recolección")).toBeVisible();
    expect(screen.getByText("No recolecta")).toBeVisible();
    expect(screen.queryByText("Activo")).not.toBeInTheDocument();
    expect(screen.queryByText("Sin monitor Signal")).not.toBeInTheDocument();
  });

  it("distingue recolección real como Activo", async () => {
    getActivity.mockResolvedValue({
      dossier_id: "d1",
      intent: null,
      requirements: [],
      offerings: [],
      summary: {
        total: 1,
        by_state: { active: 1 },
        by_kind: { surveillance_action: 1 },
      },
      items: [
        {
          kind: "surveillance_action",
          id: "sa3",
          title: "Vigilancia real recolectando",
          product_state: "active",
          desired_status: "active",
          cadence: "daily",
          last_success_at: "2026-08-03T18:00:00+00:00",
          target: {
            action_type: "news_mentions",
            degraded: false,
            degraded_reason: null,
            signal_monitor_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            collection_state: "collecting",
            provider_health_state: "ok",
            provider_last_run_at: "2026-08-03T18:00:00+00:00",
          },
        },
      ],
      pagination: { limit: 100, offset: 0, total: 1 },
    });

    render(<DossierActivitySection dossierId="d1" />);
    await waitFor(() =>
      expect(screen.getByText("Vigilancia real recolectando")).toBeInTheDocument(),
    );
    expect(screen.getAllByText("Activo").length).toBeGreaterThan(0);
    expect(screen.queryByText("Sin recolección")).not.toBeInTheDocument();
    expect(screen.queryByText("No recolecta")).not.toBeInTheDocument();
  });
});
