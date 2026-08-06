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

describe("ActorDiscoveryList G-20-B structured", () => {
  const structuredOutput: MarketActorDiscoveryOutput = {
    candidates: [
      {
        candidate_id: cid,
        actor_type: "research_group",
        organization: "Institut Néel",
        affiliation: "CNRS",
        parent_organization: "CNRS",
        country: "FR",
        summary: "Lab grafeno Grenoble",
        evidence_ids: [sid],
        citable_sources: [
          {
            source_id: sid,
            title: "Institut Néel HAL",
            url: "https://aurehal.archives-ouvertes.fr/structure/1043183",
            snippet: "graphene",
            rank: 1,
            domain: "aurehal.archives-ouvertes.fr",
            label: "Institut Néel HAL",
            origin: "structured",
            origin_label: "Fuente estructurada (CORDIS/HAL/RNSR/ROR)",
          },
        ],
        confidence: 70,
        selectable: true,
        ids: { rnsr: "200717524X", ror: "04dbzz632" },
        identity_status: "validated",
        rank: 1,
        score: 70,
        score_breakdown: { identity: 40, country: 10 },
        ranking_reasons: ["identity_validated", "country_match:FR"],
      },
      {
        candidate_id: "33333333-3333-4333-8333-333333333333",
        actor_type: "company",
        organization: "NEEL Trimarans",
        country: "FR",
        summary: "Homónimo naval",
        evidence_ids: [sid],
        citable_sources: [
          {
            source_id: sid,
            title: "NEEL Trimarans",
            url: "https://ror.org/05neelt99",
            snippet: "trimarans",
            rank: 2,
            domain: "ror.org",
            label: "NEEL Trimarans",
            origin: "structured",
            origin_label: "Fuente estructurada (CORDIS/HAL/RNSR/ROR)",
          },
        ],
        confidence: 15,
        selectable: true,
        ids: { ror: "05neelt99" },
        identity_status: "unresolved",
        unresolved_reason: "name_only_homonym",
        rank: 2,
        score: 15,
        score_breakdown: { term_match: 5 },
      },
    ],
    warnings: [],
  };

  it("shows RNSR/ROR, identity status and score without validating unresolved", () => {
    render(
      <ActorDiscoveryList
        output={structuredOutput}
        selectedCandidateIds={new Set()}
        onToggle={vi.fn()}
      />,
    );
    expect(screen.getByTestId("actor-id-rnsr")).toHaveTextContent("200717524X");
    const rorIds = screen.getAllByTestId("actor-id-ror").map((el) => el.textContent);
    expect(rorIds).toContain("04dbzz632");
    expect(rorIds).toContain("05neelt99");
    const statuses = screen.getAllByTestId("actor-identity-status");
    expect(statuses[0]).toHaveAttribute("data-status", "validated");
    expect(statuses[0]).toHaveTextContent(/validada/);
    expect(statuses[1]).toHaveAttribute("data-status", "unresolved");
    expect(statuses[1]).toHaveTextContent(/sin resolver/);
    expect(statuses[1]).not.toHaveTextContent(/validada \(ID fuerte\)/);
    expect(screen.getAllByTestId("actor-score-breakdown")[0]).toHaveTextContent(
      "identity=40",
    );
    expect(screen.getAllByTestId("source-origin-structured").length).toBeGreaterThan(0);
  });
});
