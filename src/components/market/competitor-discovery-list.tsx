"use client";

/**
 * G-18 · lista honesta de competidores propuestos.
 * Solo muestra citas de reserved/citable_sources de Signal (label/dominio + abrir).
 * Nunca presenta source_urls inventadas por el modelo. Candidatos sin evidence_id
 * o sin candidate_id server-owned no son seleccionables.
 * La aceptación se construye con candidate_id + source_ids (nunca solo name).
 */

import type {
  MarketCompetitorCandidate,
  MarketCompetitorDiscoveryOutput,
  MarketCompetitorSelection,
} from "@oracle/api-client";

export function competitorIsSelectable(candidate: MarketCompetitorCandidate): boolean {
  if (candidate.selectable === false) return false;
  if (!candidate.candidate_id) return false;
  const ids = candidate.evidence_ids ?? [];
  const sources = candidate.citable_sources ?? [];
  return ids.length > 0 && sources.length > 0;
}

/** Build accept payload from selected candidate_ids (never name-only). */
export function buildCompetitorAcceptSelection(
  output: MarketCompetitorDiscoveryOutput | null | undefined,
  selectedCandidateIds: Set<string>,
): MarketCompetitorSelection[] {
  const candidates = output?.candidates ?? [];
  const selected: MarketCompetitorSelection[] = [];
  for (const candidate of candidates) {
    const cid = candidate.candidate_id;
    if (!cid || !selectedCandidateIds.has(cid)) continue;
    if (!competitorIsSelectable(candidate)) continue;
    const source_ids = (candidate.evidence_ids ?? []).filter(Boolean);
    if (source_ids.length === 0) continue;
    selected.push({
      candidate_id: cid,
      name: candidate.name,
      source_ids,
    });
  }
  return selected;
}

export function CompetitorDiscoveryList({
  output,
  selectedCandidateIds,
  onToggle,
}: {
  output: MarketCompetitorDiscoveryOutput | null | undefined;
  selectedCandidateIds: Set<string>;
  onToggle(candidateId: string, next: boolean): void;
}) {
  const candidates = output?.candidates ?? [];
  if (candidates.length === 0) {
    return (
      <p className="muted" data-testid="competitor-discovery-empty">
        No hay competidores publicables con cita cerrada.
      </p>
    );
  }

  return (
    <ul className="competitor-discovery-list" data-testid="competitor-discovery-list">
      {candidates.map((candidate) => {
        const selectable = competitorIsSelectable(candidate);
        const cid = candidate.candidate_id ?? "";
        const checked = Boolean(cid && selectedCandidateIds.has(cid));
        const sources = candidate.citable_sources ?? [];
        const rowKey = cid || `name:${candidate.name}`;
        return (
          <li
            key={rowKey}
            className={selectable ? "competitor-discovery-item" : "competitor-discovery-item blocked"}
            data-testid="competitor-discovery-item"
            data-selectable={selectable ? "true" : "false"}
            data-candidate-id={cid || undefined}
          >
            <label className="competitor-discovery-row">
              <input
                type="checkbox"
                disabled={!selectable || !cid}
                checked={selectable && checked}
                aria-label={
                  selectable
                    ? `Seleccionar ${candidate.name}`
                    : `${candidate.name} sin cita cerrada (no seleccionable)`
                }
                onChange={(event) => {
                  if (!cid) return;
                  onToggle(cid, event.target.checked);
                }}
              />
              <span className="competitor-discovery-name">{candidate.name}</span>
              {candidate.country ? (
                <span className="muted competitor-discovery-country">{candidate.country}</span>
              ) : null}
            </label>
            <p className="competitor-discovery-rationale">{candidate.rationale}</p>
            {sources.length > 0 ? (
              <ul className="competitor-citable-sources" data-testid="competitor-citable-sources">
                {sources.map((src) => {
                  const label = src.label || src.title || src.domain || "Fuente";
                  const domain = src.domain || "";
                  return (
                    <li key={src.source_id}>
                      <a
                        href={src.url}
                        rel="noreferrer noopener"
                        target="_blank"
                        data-testid="competitor-source-link"
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
              <p className="muted" data-testid="competitor-no-citable-source">
                Sin cita cerrada — no seleccionable
              </p>
            )}
            {/* Never render candidate.source_urls as citations (model-invented). */}
          </li>
        );
      })}
    </ul>
  );
}
