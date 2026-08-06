"use client";

/**
 * G-19 · lista de actores propuestos (no competidores).
 * Muestra organización, afiliación, tipo, país y citas cerradas.
 * Candidatos sin evidence_id o sin candidate_id server-owned no son seleccionables.
 * La aceptación se construye con candidate_id + source_ids.
 */

import type {
  MarketActorCandidate,
  MarketActorDiscoveryOutput,
  MarketActorSelection,
} from "@oracle/api-client";

const ACTOR_TYPE_LABELS: Record<string, string> = {
  company: "Empresa",
  research_group: "Grupo de investigación",
  technology_center: "Centro tecnológico",
  regulator: "Regulador",
  potential_customer: "Cliente potencial",
};

export function actorIsSelectable(candidate: MarketActorCandidate): boolean {
  if (candidate.selectable === false) return false;
  if (!candidate.candidate_id) return false;
  const ids = candidate.evidence_ids ?? [];
  const sources = candidate.citable_sources ?? [];
  return ids.length > 0 && sources.length > 0;
}

/** Build accept payload from selected candidate_ids (never name-only). */
export function buildActorAcceptSelection(
  output: MarketActorDiscoveryOutput | null | undefined,
  selectedCandidateIds: Set<string>,
): MarketActorSelection[] {
  const candidates = output?.candidates ?? [];
  const selected: MarketActorSelection[] = [];
  for (const candidate of candidates) {
    const cid = candidate.candidate_id;
    if (!cid || !selectedCandidateIds.has(cid)) continue;
    if (!actorIsSelectable(candidate)) continue;
    const source_ids = (candidate.evidence_ids ?? []).filter(Boolean);
    if (source_ids.length === 0) continue;
    selected.push({
      candidate_id: cid,
      organization: candidate.organization,
      source_ids,
    });
  }
  return selected;
}

export function ActorDiscoveryList({
  output,
  selectedCandidateIds,
  onToggle,
}: {
  output: MarketActorDiscoveryOutput | null | undefined;
  selectedCandidateIds: Set<string>;
  onToggle(candidateId: string, next: boolean): void;
}) {
  const candidates = output?.candidates ?? [];
  const warnings = output?.warnings ?? [];

  if (candidates.length === 0) {
    return (
      <div data-testid="actor-discovery-empty">
        <p className="muted">No hay actores publicables con cita cerrada.</p>
        {warnings.length > 0 ? (
          <ul className="actor-discovery-warnings" data-testid="actor-discovery-warnings">
            {warnings.map((w) => (
              <li key={w}>{w}</li>
            ))}
          </ul>
        ) : null}
      </div>
    );
  }

  return (
    <div>
      <h3 className="actor-discovery-heading" data-testid="actor-discovery-heading">
        Actores sugeridos
      </h3>
      <ul className="actor-discovery-list" data-testid="actor-discovery-list">
        {candidates.map((candidate) => {
          const selectable = actorIsSelectable(candidate);
          const cid = candidate.candidate_id ?? "";
          const checked = Boolean(cid && selectedCandidateIds.has(cid));
          const sources = candidate.citable_sources ?? [];
          const rowKey = cid || `org:${candidate.organization}`;
          const typeLabel =
            ACTOR_TYPE_LABELS[candidate.actor_type] || candidate.actor_type || "—";
          return (
            <li
              key={rowKey}
              className={selectable ? "actor-discovery-item" : "actor-discovery-item blocked"}
              data-testid="actor-discovery-item"
              data-selectable={selectable ? "true" : "false"}
              data-candidate-id={cid || undefined}
            >
              <label className="actor-discovery-row">
                <input
                  type="checkbox"
                  disabled={!selectable || !cid}
                  checked={selectable && checked}
                  aria-label={
                    selectable
                      ? `Seleccionar ${candidate.organization}`
                      : `${candidate.organization} sin cita cerrada (no seleccionable)`
                  }
                  onChange={(event) => {
                    if (!cid) return;
                    onToggle(cid, event.target.checked);
                  }}
                />
                <span className="actor-discovery-org">{candidate.organization}</span>
                {candidate.affiliation ? (
                  <span className="muted actor-discovery-affiliation">
                    {candidate.affiliation}
                  </span>
                ) : null}
                <span className="muted actor-discovery-type" data-testid="actor-type">
                  {typeLabel}
                </span>
                {candidate.country ? (
                  <span className="muted actor-discovery-country">{candidate.country}</span>
                ) : null}
              </label>
              <p className="actor-discovery-summary">
                {candidate.summary || candidate.rationale}
              </p>
              {sources.length > 0 ? (
                <ul className="actor-citable-sources" data-testid="actor-citable-sources">
                  {sources.map((src) => {
                    const label = src.label || src.title || src.domain || "Fuente";
                    const domain = src.domain || "";
                    return (
                      <li key={src.source_id}>
                        <a
                          href={src.url}
                          rel="noreferrer noopener"
                          target="_blank"
                          data-testid="actor-source-link"
                        >
                          {label}
                          {domain ? ` (${domain})` : ""}
                        </a>{" "}
                        <span
                          className="source-origin-badge"
                          data-testid="source-origin-web-search"
                          title="Origen: búsqueda web de Signal; no es evidencia documental validada"
                        >
                          {src.origin_label || "Fuente encontrada por búsqueda"}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              ) : (
                <p className="muted" data-testid="actor-no-citable-source">
                  Sin cita cerrada — no seleccionable
                </p>
              )}
            </li>
          );
        })}
      </ul>
      {warnings.length > 0 ? (
        <ul className="actor-discovery-warnings" data-testid="actor-discovery-warnings">
          {warnings.map((w) => (
            <li key={w}>{w}</li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
