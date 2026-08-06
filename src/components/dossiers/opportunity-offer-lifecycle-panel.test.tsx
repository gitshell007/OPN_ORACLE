/** @vitest-environment jsdom */
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ApiError } from "@oracle/api-client";
import { OpportunityOfferLifecyclePanel } from "./opportunity-offer-lifecycle-panel";

const getOfferLifecycle = vi.fn();
const patchOfferLifecycle = vi.fn();

vi.mock("@oracle/api-client", async () => {
  const actual = await vi.importActual<typeof import("@oracle/api-client")>(
    "@oracle/api-client",
  );
  return {
    ...actual,
    api: {
      ...actual.api,
      opportunities: {
        ...actual.api.opportunities,
        getOfferLifecycle: (...args: unknown[]) => getOfferLifecycle(...args),
        patchOfferLifecycle: (...args: unknown[]) => patchOfferLifecycle(...args),
      },
    },
  };
});

vi.mock("@/components/auth/auth-boundary", () => ({
  PermissionGate: ({
    children,
  }: {
    children: React.ReactNode;
    permission: string;
    fallback?: React.ReactNode;
  }) => <>{children}</>,
}));

vi.mock("sonner", () => ({
  toast: { success: vi.fn(), message: vi.fn(), error: vi.fn() },
}));

vi.mock("@/components/ui/async-action-button", () => ({
  AsyncActionButton: ({
    children,
    loading,
    disabled,
    onClick,
    type = "button",
    className,
    ...rest
  }: {
    children: React.ReactNode;
    loading?: boolean;
    disabled?: boolean;
    onClick?: () => void;
    type?: "button" | "submit";
    className?: string;
    [key: string]: unknown;
  }) => (
    <button
      type={type}
      className={className}
      disabled={Boolean(disabled || loading)}
      onClick={onClick}
      {...rest}
    >
      {children}
    </button>
  ),
}));

function lifecycle(
  overrides: Record<string, unknown> = {},
  envelope: Record<string, unknown> = {},
) {
  const life = {
    id: "11111111-1111-1111-1111-111111111111",
    tenant_id: "22222222-2222-2222-2222-222222222222",
    dossier_id: "dossier-1",
    opportunity_id: "opp-1",
    status: "preparando",
    status_label: "Preparando",
    importe_ofertado: null,
    baja_porcentaje: null,
    lotes: [],
    garantia_provisional: null,
    fecha_mesa: null,
    motivo_exclusion: null,
    version: 1,
    etag: 'W/"ool-v1"',
    last_edited_by_user_id: "33333333-3333-3333-3333-333333333333",
    created_at: "2026-08-06T12:00:00+00:00",
    updated_at: "2026-08-06T12:00:00+00:00",
    materialized: true,
    crm_status_note:
      "El estado CRM de la oportunidad es independiente de este ciclo de oferta.",
    ...overrides,
  };
  return {
    lifecycle: life,
    materialized: life.materialized === true,
    ...envelope,
  };
}

function virtualLifecycle() {
  return lifecycle(
    {
      id: null,
      version: 0,
      etag: 'W/"ool-v0"',
      last_edited_by_user_id: null,
      created_at: null,
      updated_at: null,
      materialized: false,
    },
    { materialized: false },
  );
}

describe("OpportunityOfferLifecyclePanel", () => {
  afterEach(() => {
    cleanup();
  });

  beforeEach(() => {
    getOfferLifecycle.mockReset();
    patchOfferLifecycle.mockReset();
    getOfferLifecycle.mockResolvedValue(lifecycle());
  });

  it("maneja estado virtual no materializado y primer guardado con version=0", async () => {
    getOfferLifecycle.mockResolvedValue(virtualLifecycle());
    patchOfferLifecycle.mockResolvedValue(
      lifecycle({
        status: "presentada",
        status_label: "Presentada",
        importe_ofertado: "1000",
        version: 1,
        etag: 'W/"ool-v1"',
        materialized: true,
      }),
    );

    render(
      <OpportunityOfferLifecyclePanel
        dossierId="dossier-1"
        opportunityId="opp-1"
        crmStatus="identified"
        crmStatusLabel="Identificada"
      />,
    );

    await screen.findByTestId("offer-lifecycle-form");
    expect(screen.getByTestId("offer-lifecycle-version").textContent).toMatch(
      /Sin materializar|v0/i,
    );
    expect(screen.getByTestId("offer-lifecycle-virtual-hint")).toBeTruthy();
    expect(screen.getByTestId("offer-lifecycle-save").textContent).toMatch(
      /primera vez/i,
    );

    fireEvent.change(screen.getByTestId("offer-lifecycle-status"), {
      target: { value: "presentada" },
    });
    fireEvent.change(screen.getByTestId("offer-lifecycle-importe"), {
      target: { value: "1000" },
    });
    fireEvent.click(screen.getByTestId("offer-lifecycle-save"));

    await waitFor(() => expect(patchOfferLifecycle).toHaveBeenCalled());
    const [, , payload, ifMatch] = patchOfferLifecycle.mock.calls[0];
    expect(payload.version).toBe(0);
    expect(payload.status).toBe("presentada");
    expect(payload.importe_ofertado).toBe("1000");
    expect(ifMatch).toBe('W/"ool-v0"');

    await waitFor(() =>
      expect(screen.getByTestId("offer-lifecycle-version").textContent).toMatch(/v1/),
    );
  });

  it("consulta, edita y guarda el seguimiento materializado (sin artifact/fit/verdict)", async () => {
    patchOfferLifecycle.mockResolvedValue(
      lifecycle({
        status: "presentada",
        status_label: "Presentada",
        importe_ofertado: "1000",
        version: 2,
        etag: 'W/"ool-v2"',
      }),
    );

    render(
      <OpportunityOfferLifecyclePanel
        dossierId="dossier-1"
        opportunityId="opp-1"
        crmStatus="identified"
        crmStatusLabel="Identificada"
      />,
    );

    expect(await screen.findByTestId("opportunity-offer-lifecycle-panel")).toBeTruthy();
    expect(screen.getByText(/Independiente del estado CRM/i)).toBeTruthy();
    expect(screen.getByText(/CRM actual: Identificada/i)).toBeTruthy();

    await waitFor(() => expect(getOfferLifecycle).toHaveBeenCalledWith("dossier-1", "opp-1"));

    fireEvent.change(screen.getByTestId("offer-lifecycle-status"), {
      target: { value: "presentada" },
    });
    fireEvent.change(screen.getByTestId("offer-lifecycle-importe"), {
      target: { value: "1000" },
    });
    fireEvent.change(screen.getByTestId("offer-lifecycle-baja"), {
      target: { value: "2.5" },
    });
    fireEvent.change(screen.getByTestId("offer-lifecycle-lotes"), {
      target: { value: "Lote 1, Lote 2" },
    });

    expect(screen.getByTestId("offer-lifecycle-save-status").textContent).toMatch(/Sin guardar/);

    fireEvent.click(screen.getByTestId("offer-lifecycle-save"));

    await waitFor(() => expect(patchOfferLifecycle).toHaveBeenCalled());
    const [, , payload, ifMatch] = patchOfferLifecycle.mock.calls[0];
    expect(payload.status).toBe("presentada");
    expect(payload.importe_ofertado).toBe("1000");
    expect(payload.baja_porcentaje).toBe("2.5");
    expect(payload.lotes).toEqual(["Lote 1", "Lote 2"]);
    expect(payload.version).toBe(1);
    expect(ifMatch).toBe('W/"ool-v1"');
  });

  it("exige motivo al pasar a excluida y lo envía", async () => {
    patchOfferLifecycle.mockResolvedValue(
      lifecycle({
        status: "excluida",
        status_label: "Excluida",
        motivo_exclusion: "Solvencia insuficiente",
        version: 2,
        etag: 'W/"ool-v2"',
      }),
    );

    render(
      <OpportunityOfferLifecyclePanel dossierId="dossier-1" opportunityId="opp-1" />,
    );
    await screen.findByTestId("offer-lifecycle-form");

    fireEvent.change(screen.getByTestId("offer-lifecycle-status"), {
      target: { value: "excluida" },
    });
    expect(screen.getByTestId("offer-lifecycle-motivo")).toBeTruthy();

    fireEvent.click(screen.getByTestId("offer-lifecycle-save"));
    await waitFor(() =>
      expect(screen.getByTestId("offer-lifecycle-motivo-error").textContent).toMatch(
        /Obligatorio/,
      ),
    );
    expect(patchOfferLifecycle).not.toHaveBeenCalled();

    fireEvent.change(screen.getByTestId("offer-lifecycle-motivo"), {
      target: { value: "Solvencia insuficiente" },
    });
    fireEvent.click(screen.getByTestId("offer-lifecycle-save"));
    await waitFor(() => expect(patchOfferLifecycle).toHaveBeenCalled());
    expect(patchOfferLifecycle.mock.calls[0][2].motivo_exclusion).toBe(
      "Solvencia insuficiente",
    );
  });

  it("recupera conflicto 409 con recarga", async () => {
    patchOfferLifecycle.mockRejectedValueOnce(
      new ApiError(409, {
        type: "https://oracle.opnconsultoria.com/problems/version-conflict",
        title: "Conflict",
        status: 409,
        detail: "El seguimiento de oferta fue modificado por otro usuario.",
        code: "version_conflict",
        instance: "/api/v1/dossiers/x/opportunities/y/offer-lifecycle",
        request_id: "test-request-id",
      }),
    );
    getOfferLifecycle
      .mockResolvedValueOnce(lifecycle())
      .mockResolvedValueOnce(
        lifecycle({
          status: "presentada",
          status_label: "Presentada",
          version: 5,
          etag: 'W/"ool-v5"',
          importe_ofertado: "999",
        }),
      );

    render(
      <OpportunityOfferLifecyclePanel dossierId="dossier-1" opportunityId="opp-1" />,
    );
    await screen.findByTestId("offer-lifecycle-form");

    fireEvent.change(screen.getByTestId("offer-lifecycle-importe"), {
      target: { value: "1" },
    });
    fireEvent.click(screen.getByTestId("offer-lifecycle-save"));

    expect(await screen.findByTestId("offer-lifecycle-conflict")).toBeTruthy();
    expect(screen.getByTestId("offer-lifecycle-save-status").textContent).toMatch(/409/);

    fireEvent.click(screen.getByTestId("offer-lifecycle-reload"));
    await waitFor(() => expect(getOfferLifecycle).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect((screen.getByTestId("offer-lifecycle-importe") as HTMLInputElement).value).toBe(
        "999",
      ),
    );
  });

  it("muestra dirty-state y permanece visible sin depender de artifact", async () => {
    render(
      <OpportunityOfferLifecyclePanel dossierId="dossier-1" opportunityId="opp-1" />,
    );
    const panel = await screen.findByTestId("opportunity-offer-lifecycle-panel");
    expect(panel).toBeTruthy();
    // No AI artifact / fit / verdict gates in the tree.
    expect(panel.textContent).not.toMatch(/artifact|verdict|fit_assessment/i);

    fireEvent.change(await screen.findByTestId("offer-lifecycle-importe"), {
      target: { value: "50" },
    });
    expect(screen.getByTestId("offer-lifecycle-save-status").textContent).toMatch(/Sin guardar/);
    expect((screen.getByTestId("offer-lifecycle-save") as HTMLButtonElement).disabled).toBe(
      false,
    );
  });
});
