import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import type { MarketActorDiscoveryOutput } from "@oracle/api-client";
import {
  ActorDiscoveryList,
  actorIsSelectable,
  buildActorAcceptSelection,
} from "./actor-discovery-list";

afterEach(() => {
  cleanup();
});
const sid = "11111111-1111-4111-8111-111111111111";
const cid = "22222222-2222-4222-8222-222222222222";

const closedOutput: MarketActorDiscoveryOutput = {
  candidates: [
    {
      candidate_id: cid,
      actor_type: "research_group",
      organization: "Lab Graphene FR",
      affiliation: "CNRS",
      country: "FR",
      summary: "Trabaja en grafeno en Francia",
      rationale: "Trabaja en grafeno en Francia",
      evidence_ids: [sid],
      citable_sources: [
        {
          source_id: sid,
          title: "Lab Graphene",
          url: "https://example.fr/lab",
          snippet: "graphene",
          rank: 1,
          domain: "example.fr",
          label: "Lab Graphene",
          origin: "web_search",
          origin_label: "Fuente encontrada por búsqueda",
        },
      ],
      confidence: 70,
      selectable: true,
    },
    {
      candidate_id: null,
      actor_type: "research_group",
      organization: "Sin cita",
      affiliation: "",
      country: "FR",
      summary: "No publicable",
      evidence_ids: [],
      citable_sources: [],
      confidence: 10,
      selectable: false,
    },
  ],
  warnings: [],
};

describe("ActorDiscoveryList G-19", () => {
  it("lists organization, affiliation, type, country and citations", () => {
    render(
      <ActorDiscoveryList
        output={closedOutput}
        selectedCandidateIds={new Set()}
        onToggle={vi.fn()}
      />,
    );
    expect(screen.getByTestId("actor-discovery-heading")).toHaveTextContent(
      "Actores sugeridos",
    );
    expect(screen.getByText("Lab Graphene FR")).toBeInTheDocument();
    expect(screen.getByText("CNRS")).toBeInTheDocument();
    expect(screen.getAllByTestId("actor-type")[0]).toHaveTextContent(
      "Grupo de investigación",
    );
    expect(screen.getAllByText("FR").length).toBeGreaterThan(0);
    expect(screen.getByTestId("actor-source-link")).toHaveAttribute(
      "href",
      "https://example.fr/lab",
    );
  });

  it("blocks candidates without closed citation", () => {
    render(
      <ActorDiscoveryList
        output={closedOutput}
        selectedCandidateIds={new Set()}
        onToggle={vi.fn()}
      />,
    );
    const items = screen.getAllByTestId("actor-discovery-item");
    expect(items[0]).toHaveAttribute("data-selectable", "true");
    expect(items[1]).toHaveAttribute("data-selectable", "false");
    expect(screen.getAllByTestId("actor-no-citable-source").length).toBe(1);
  });
  it("builds accept selection with candidate_id + source_ids only", () => {
    const selected = buildActorAcceptSelection(closedOutput, new Set([cid]));
    expect(selected).toEqual([
      {
        candidate_id: cid,
        organization: "Lab Graphene FR",
        source_ids: [sid],
      },
    ]);
    expect(actorIsSelectable(closedOutput.candidates[0])).toBe(true);
    expect(actorIsSelectable(closedOutput.candidates[1])).toBe(false);
  });

  it("shows honest empty state", () => {
    render(
      <ActorDiscoveryList
        output={{ candidates: [], warnings: ["Abstención: sin respaldo citable."] }}
        selectedCandidateIds={new Set()}
        onToggle={vi.fn()}
      />,
    );
    expect(screen.getByTestId("actor-discovery-empty")).toBeInTheDocument();
    expect(screen.getByText(/Abstención/)).toBeInTheDocument();
  });
});
