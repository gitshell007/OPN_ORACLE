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
        dossierType="project"
        profileConfig={{}}
        draft={null}
        onDraftChange={() => undefined}
        onSave={(event) => event.preventDefault()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});
