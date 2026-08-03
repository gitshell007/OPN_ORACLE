import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { DossierProfilePanel } from "./dossier-profile-panel";
import type { MarketProfileDraft } from "@/lib/dossier-profile";

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
    expect(screen.getByRole("link", { name: /Editar en configuración/ })).toHaveAttribute(
      "href",
      "/app/dossiers/ab7bba16/settings#dossier-profile",
    );
  });
});
