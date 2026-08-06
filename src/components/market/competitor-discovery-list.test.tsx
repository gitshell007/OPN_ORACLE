import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import type { MarketCompetitorDiscoveryOutput } from "@oracle/api-client";
import {
  CompetitorDiscoveryList,
  competitorIsSelectable,
} from "./competitor-discovery-list";

const closedOutput: MarketCompetitorDiscoveryOutput = {
  candidates: [
    {
      name: "Acme Sensors",
      country: "DE",
      rationale: "Compite en sensores industriales.",
      evidence_ids: ["9067e361-54fa-5b03-8d56-7494b798e453"],
      citable_sources: [
        {
          source_id: "9067e361-54fa-5b03-8d56-7494b798e453",
          title: "Acme Sensors",
          url: "https://acme.example/about",
          domain: "acme.example",
          label: "Acme Sensors",
          origin: "web_search",
          origin_label: "Fuente encontrada por búsqueda",
        },
      ],
      confidence: 80,
      selectable: true,
    },
    {
      name: "Sin Cita",
      country: "ES",
      rationale: "Modelo inventó URL pero sin source_id.",
      evidence_ids: [],
      source_urls: ["https://modelo-inventado.example/x"],
      citable_sources: [],
      confidence: 40,
      selectable: false,
    },
  ],
  warnings: [],
  reserved_citable_sources: [],
};

describe("CompetitorDiscoveryList G-18", () => {
  it("shows closed source label/domain with open action", () => {
    render(
      <CompetitorDiscoveryList
        output={closedOutput}
        selectedNames={new Set()}
        onToggle={() => undefined}
      />,
    );
    const links = screen.getAllByTestId("competitor-source-link");
    expect(links).toHaveLength(1);
    expect(links[0]).toHaveAttribute("href", "https://acme.example/about");
    expect(links[0]).toHaveTextContent(/Acme Sensors/);
    expect(links[0]).toHaveTextContent(/acme\.example/);
    expect(screen.getAllByTestId("source-origin-web-search")[0]).toHaveTextContent(
      "Fuente encontrada por búsqueda",
    );
  });

  it("does not render model-invented source_urls as citations", () => {
    render(
      <CompetitorDiscoveryList
        output={closedOutput}
        selectedNames={new Set()}
        onToggle={() => undefined}
      />,
    );
    expect(screen.queryByText(/modelo-inventado/)).toBeNull();
    const blocked = screen.getAllByTestId("competitor-no-citable-source");
    expect(blocked.length).toBeGreaterThanOrEqual(1);
    expect(blocked[0]).toHaveTextContent(/no seleccionable/i);
  });

  it("blocks selection when candidate has no evidence_id", () => {
    const onToggle = vi.fn();
    const { container } = render(
      <CompetitorDiscoveryList
        output={closedOutput}
        selectedNames={new Set()}
        onToggle={onToggle}
      />,
    );
    const items = container.querySelectorAll('[data-testid="competitor-discovery-item"]');
    const blockedItem = Array.from(items).find((el) => el.getAttribute("data-selectable") === "false");
    const openItem = Array.from(items).find((el) => el.getAttribute("data-selectable") === "true");
    expect(blockedItem).toBeTruthy();
    expect(openItem).toBeTruthy();
    const blocked = blockedItem!.querySelector('input[type="checkbox"]') as HTMLInputElement;
    const open = openItem!.querySelector('input[type="checkbox"]') as HTMLInputElement;
    expect(blocked.disabled).toBe(true);
    expect(blocked.checked).toBe(false);
    expect(open.disabled).toBe(false);
    fireEvent.click(open);
    expect(onToggle).toHaveBeenCalledTimes(1);
    expect(onToggle).toHaveBeenCalledWith("Acme Sensors", true);
  });

  it("competitorIsSelectable requires evidence + public sources", () => {
    expect(competitorIsSelectable(closedOutput.candidates[0])).toBe(true);
    expect(competitorIsSelectable(closedOutput.candidates[1])).toBe(false);
  });
});
