import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DossierProfilePanel } from "./dossier-profile-panel";
import {
  ANNUAL_TURNOVER_INVALID_MSG,
  PAST_SERVICES_MAX_LEN,
  type CompetitiveProfileDraft,
  type CustomProfileDraft,
  type MarketProfileDraft,
  profileConfigFromDraft,
} from "@/lib/dossier-profile";

const marketDraft: MarketProfileDraft = {
  kind: "market",
  own_offer: "Integración de baterías",
  decision_to_make: "Entrar o no",
  horizon: "Q4",
  segments: "utility",
  channels: "licitación",
  target_buyers: "operadores",
  competitors: "Gamma, Delta",
  partners: "Partner",
  regulators: "CNE",
  barriers: "Permisos lentos",
  success_indicators: "pipeline",
  keywords: "almacenamiento",
  annual_turnover: "",
  past_services: "",
};

const ciDraft: CompetitiveProfileDraft = {
  kind: "competitive_intelligence",
  own_offer: "Producto",
  business_objective: "Ganar cuota",
  competitors: "Rival",
  segments: "",
  geographies: "ES",
  target_buyers: "",
  horizon: "",
  keywords: "limpieza",
  cpv: "90910000",
  sources: "PLACSP",
  participation_criteria: "",
  exclusion_criteria: "",
  success_indicators: "",
  annual_turnover: "",
  past_services: "",
};

const customDraft: CustomProfileDraft = {
  kind: "custom",
  own_offer: "Software e IA",
  decision_to_make: "Priorizar PLACSP software",
  competitors: "Capgemini, NTT DATA, Inetum",
  barriers: "Homologación",
  cpv: "72000000, 72200000",
  keywords: "IA, software",
  geographies: "ES",
  target_buyers: "AAPP",
  segments: "sector público",
  business_objective: "Ganar cuota IT pública",
  success_indicators: "pipeline",
  sources: "PLACSP",
  annual_turnover: "",
  past_services: "",
};

describe("DossierProfilePanel", () => {
  afterEach(cleanup);

  it("muestra y edita el perfil de mercado en configuración", () => {
    const onDraftChange = vi.fn();
    const onSave = vi.fn((event: { preventDefault(): void }) => event.preventDefault());
    render(
      <DossierProfilePanel
        dossierId="d1"
        dossierType="market"
        profileConfig={{ version: "market.v1", own_offer: "Integración de baterías" }}
        draft={marketDraft}
        onDraftChange={onDraftChange}
        onSave={onSave}
      />,
    );

    expect(screen.getByRole("heading", { name: "Perfil del expediente" })).toBeVisible();
    expect(screen.getByLabelText("Oferta propia")).toHaveValue("Integración de baterías");
    expect(screen.getByLabelText("Decisión a tomar")).toHaveValue("Entrar o no");
    expect(screen.getByLabelText("Competidores")).toHaveValue("Gamma, Delta");
    expect(screen.getByLabelText("Barreras")).toHaveValue("Permisos lentos");

    fireEvent.change(screen.getByLabelText("Oferta propia"), {
      target: { value: "Nueva oferta" },
    });
    expect(onDraftChange).toHaveBeenCalled();

    fireEvent.click(screen.getByRole("button", { name: /Guardar perfil/ }));
    expect(onSave).toHaveBeenCalled();
  });

  it("muestra CPV en modo lectura para inteligencia competitiva", () => {
    render(
      <DossierProfilePanel
        dossierId="d1"
        dossierType="competitive_intelligence"
        profileConfig={{
          version: "competitive-intelligence.v1",
          own_offer: "Producto",
          cpv: ["90910000"],
        }}
        draft={{
          kind: "competitive_intelligence",
          own_offer: "Producto",
          business_objective: "Ganar cuota",
          competitors: "Rival",
          segments: "",
          geographies: "ES",
          target_buyers: "",
          horizon: "",
          keywords: "limpieza",
          cpv: "90910000",
          sources: "PLACSP",
          participation_criteria: "",
          exclusion_criteria: "",
          success_indicators: "",
          annual_turnover: "1500000",
          past_services: "Limpieza hospitalaria 2023-2025 con certificados",
        }}
        onDraftChange={() => undefined}
        onSave={(event) => event.preventDefault()}
        readOnly
      />,
    );

    expect(screen.getByTestId("dossier-profile-summary")).toBeVisible();
    expect(screen.getByText("Producto")).toBeVisible();
    expect(screen.getByText("90910000")).toBeVisible();
    expect(screen.getByRole("link", { name: /Editar en configuración/ })).toHaveAttribute(
      "href",
      "/app/dossiers/d1/settings#dossier-profile",
    );
  });

  it("no renderiza nada para tipos sin perfil tipado ni datos", () => {
    const { container } = render(
      <DossierProfilePanel
        dossierId="d1"
        dossierType="unknown_type"
        profileConfig={{}}
        draft={null}
        onDraftChange={() => undefined}
        onSave={(event) => event.preventDefault()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("edita el perfil custom (oferta, competidores, CPV, barreras, decisión)", () => {
    const onDraftChange = vi.fn();
    const onSave = vi.fn((event: { preventDefault(): void }) => event.preventDefault());
    render(
      <DossierProfilePanel
        dossierId="d1"
        dossierType="custom"
        profileConfig={{
          version: "custom.v1",
          own_offer: "Software e IA",
          competitors: [{ name: "Capgemini", aliases: [] }],
        }}
        draft={{
          kind: "custom",
          own_offer: "Software e IA",
          decision_to_make: "Priorizar PLACSP software",
          competitors: "Capgemini, NTT DATA, Inetum",
          barriers: "Homologación",
          cpv: "72000000, 72200000",
          keywords: "IA, software",
          geographies: "ES",
          target_buyers: "AAPP",
          segments: "sector público",
          business_objective: "Ganar cuota IT pública",
          success_indicators: "pipeline",
          sources: "PLACSP",
          annual_turnover: "",
          past_services: "",
        }}
        onDraftChange={onDraftChange}
        onSave={onSave}
      />,
    );

    expect(screen.getByRole("heading", { name: "Perfil del expediente" })).toBeVisible();
    expect(screen.getByLabelText("Oferta propia")).toHaveValue("Software e IA");
    expect(screen.getByLabelText("Decisión a tomar")).toHaveValue("Priorizar PLACSP software");
    expect(screen.getByLabelText("Competidores")).toHaveValue("Capgemini, NTT DATA, Inetum");
    expect(screen.getByLabelText("Códigos CPV")).toHaveValue("72000000, 72200000");
    expect(screen.getByLabelText("Barreras")).toHaveValue("Homologación");

    fireEvent.change(screen.getByLabelText("Oferta propia"), {
      target: { value: "Software, plataformas e IA" },
    });
    expect(onDraftChange).toHaveBeenCalled();
    fireEvent.click(screen.getByRole("button", { name: /Guardar perfil/ }));
    expect(onSave).toHaveBeenCalled();
  });

  it("muestra el perfil custom en modo lectura con enlace a configuración", () => {
    render(
      <DossierProfilePanel
        dossierId="ab7bba16"
        dossierType="custom"
        profileConfig={{
          version: "custom.v1",
          own_offer: "Software e IA Nexus",
          competitors: [{ name: "Capgemini", aliases: [] }],
          cpv: ["72000000"],
        }}
        draft={{
          kind: "custom",
          own_offer: "Software e IA Nexus",
          decision_to_make: "Priorizar cuentas",
          competitors: "Capgemini, NTT DATA, Inetum",
          barriers: "Homologación",
          cpv: "72000000",
          keywords: "",
          geographies: "ES",
          target_buyers: "",
          segments: "",
          business_objective: "",
          success_indicators: "",
          sources: "",
          annual_turnover: "2000000",
          past_services: "Plataformas IA 2023-2025 con certificados de buena ejecución",
        }}
        onDraftChange={() => undefined}
        onSave={(event) => event.preventDefault()}
        readOnly
      />,
    );

    expect(screen.getByTestId("dossier-profile-summary")).toBeVisible();
    expect(screen.getByText("Software e IA Nexus")).toBeVisible();
    expect(screen.getByText("Capgemini, NTT DATA, Inetum")).toBeVisible();
    expect(screen.getByText("72000000")).toBeVisible();
    expect(screen.getByText("2000000")).toBeVisible();
    expect(
      screen.getByText("Plataformas IA 2023-2025 con certificados de buena ejecución"),
    ).toBeVisible();
    expect(screen.getByRole("link", { name: /Editar en configuración/ })).toHaveAttribute(
      "href",
      "/app/dossiers/ab7bba16/settings#dossier-profile",
    );
  });

  it("muestra campos de solvencia declarada editables con ayuda inequívoca", () => {
    const onDraftChange = vi.fn();
    const onSave = vi.fn((event: { preventDefault(): void }) => event.preventDefault());
    render(
      <DossierProfilePanel
        dossierId="d1"
        dossierType="market"
        profileConfig={{ version: "market.v1", own_offer: "Integración de baterías" }}
        draft={{ ...marketDraft, annual_turnover: "2000000.5", past_services: "Servicios EPC" }}
        onDraftChange={onDraftChange}
        onSave={onSave}
      />,
    );

    const volume = screen.getByLabelText("Volumen anual de negocio declarado (EUR)");
    const services = screen.getByLabelText("Servicios similares de los últimos 3 años");
    expect(volume).toHaveValue("2000000.5");
    expect(services).toHaveValue("Servicios EPC");
    expect(
      screen.getAllByText(/declarado por el cliente; no sustituye certificados/i).length,
    ).toBeGreaterThanOrEqual(2);

    fireEvent.change(volume, { target: { value: "2500000" } });
    expect(onDraftChange).toHaveBeenCalled();
    const last = onDraftChange.mock.calls.at(-1)?.[0] as MarketProfileDraft;
    expect(last.annual_turnover).toBe("2500000");

    fireEvent.change(services, {
      target: { value: "Instalación de baterías 2023-2025 con certificados" },
    });
    fireEvent.click(screen.getByRole("button", { name: /Guardar perfil/ }));
    expect(onSave).toHaveBeenCalled();
  });

  it.each([
    {
      kind: "market" as const,
      dossierType: "market",
      draft: marketDraft,
      profileConfig: { version: "market.v1", own_offer: "Integración de baterías" },
    },
    {
      kind: "competitive_intelligence" as const,
      dossierType: "competitive_intelligence",
      draft: ciDraft,
      profileConfig: {
        version: "competitive-intelligence.v1",
        own_offer: "Producto",
        competitors: [{ name: "Rival" }],
      },
    },
    {
      kind: "custom" as const,
      dossierType: "custom",
      draft: customDraft,
      profileConfig: {
        version: "custom.v1",
        own_offer: "Software e IA",
        competitors: [{ name: "Capgemini" }],
      },
    },
  ])(
    "inválido en $kind: error accesible, draft intacto y PATCH/onSave no llamado; corregir → PATCH con número",
    ({ dossierType, draft, profileConfig }) => {
      const invalid = "1.000.000 EUR";
      let current = { ...draft, annual_turnover: invalid, past_services: "Servicios OK" };
      const onSave = vi.fn((event: { preventDefault(): void }) => event.preventDefault());
      const onDraftChange = vi.fn((next: typeof draft) => {
        current = next as typeof current;
      });

      const { rerender } = render(
        <DossierProfilePanel
          dossierId="d1"
          dossierType={dossierType}
          profileConfig={profileConfig}
          draft={current}
          onDraftChange={onDraftChange}
          onSave={onSave}
        />,
      );

      const volume = screen.getByLabelText("Volumen anual de negocio declarado (EUR)");
      expect(volume).toHaveValue(invalid);

      fireEvent.click(screen.getByRole("button", { name: /Guardar perfil/ }));
      expect(onSave).not.toHaveBeenCalled();
      const alert = screen.getByRole("alert");
      expect(alert).toHaveTextContent(ANNUAL_TURNOVER_INVALID_MSG);
      expect(volume).toHaveAttribute("aria-invalid", "true");
      // Draft text preserved exactly (not cleared, not coerced to previous/absence)
      expect(volume).toHaveValue(invalid);
      expect(() => profileConfigFromDraft(current)).toThrow();

      // Correct the value → error clears on re-render + save proceeds
      current = { ...current, annual_turnover: "2000000" };
      rerender(
        <DossierProfilePanel
          dossierId="d1"
          dossierType={dossierType}
          profileConfig={profileConfig}
          draft={current}
          onDraftChange={onDraftChange}
          onSave={onSave}
        />,
      );
      expect(screen.queryByRole("alert")).toBeNull();
      fireEvent.click(screen.getByRole("button", { name: /Guardar perfil/ }));
      expect(onSave).toHaveBeenCalledTimes(1);
      expect(profileConfigFromDraft(current).annual_turnover).toBe(2_000_000);
    },
  );

  it("servicios max+1: no trunca, error visible y onSave/PATCH bloqueado", () => {
    const over = "x".repeat(PAST_SERVICES_MAX_LEN + 1);
    const draft = { ...marketDraft, annual_turnover: "100", past_services: over };
    const onSave = vi.fn((event: { preventDefault(): void }) => event.preventDefault());
    render(
      <DossierProfilePanel
        dossierId="d1"
        dossierType="market"
        profileConfig={{ version: "market.v1", own_offer: "X" }}
        draft={draft}
        onDraftChange={() => undefined}
        onSave={onSave}
      />,
    );

    const services = screen.getByLabelText(
      "Servicios similares de los últimos 3 años",
    ) as HTMLTextAreaElement;
    expect(services).toHaveValue(over);
    expect(services.value.length).toBe(PAST_SERVICES_MAX_LEN + 1);

    fireEvent.click(screen.getByRole("button", { name: /Guardar perfil/ }));
    expect(onSave).not.toHaveBeenCalled();
    expect(screen.getByRole("alert")).toHaveTextContent(/4000/);
    expect(services).toHaveValue(over);
    expect(() => profileConfigFromDraft(draft)).toThrow(/4000|caracteres/i);
  });

  it("read-only muestra valor persistido y no controles/errores de edición", () => {
    render(
      <DossierProfilePanel
        dossierId="d1"
        dossierType="market"
        profileConfig={{
          version: "market.v1",
          own_offer: "Baterías",
          annual_turnover: 2_000_000,
          past_services: "EPC 2024",
        }}
        draft={{
          ...marketDraft,
          annual_turnover: "2000000",
          past_services: "EPC 2024",
        }}
        onDraftChange={() => undefined}
        onSave={(event) => event.preventDefault()}
        readOnly
      />,
    );

    expect(screen.getByTestId("dossier-profile-summary")).toBeVisible();
    expect(screen.getByText("2000000")).toBeVisible();
    expect(screen.getByText("EPC 2024")).toBeVisible();
    expect(screen.queryByRole("button", { name: /Guardar perfil/ })).toBeNull();
    expect(screen.queryByLabelText("Volumen anual de negocio declarado (EUR)")).toBeNull();
    expect(screen.queryByRole("alert")).toBeNull();
  });
});
