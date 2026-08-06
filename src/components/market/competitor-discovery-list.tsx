"use client";

/**
 * G-18 · lista honesta de competidores propuestos.
 * Solo muestra citas de reserved/citable_sources de Signal (label/dominio + abrir).
 * Nunca presenta source_urls inventadas por el modelo. Candidatos sin evidence_id
 * no son seleccionables.
 */

import type {
  MarketCompetitorCandidate,
  MarketCompetitorDiscoveryOutput,
} from "@oracle/api-client";

export function competitorIsSelectable(candidate: MarketCompetitorCandidate): boolean {
  if (candidate.selectable === false) return false;
  const ids = candidate.evidence_ids ?? [];
  const sources = candidate.citable_sources ?? [];
  return ids.length > 0 && sources.length > 0;
}

export function CompetitorDiscoveryList({
  output,
  selectedNames,
  onToggle,
}: {
  output: MarketCompetitorDiscoveryOutput | null | undefined;
  selectedNames: Set<string>;
  onToggle(name: string, next: boolean): void;
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
        const checked = selectedNames.has(candidate.name);
        const sources = candidate.citable_sources ?? [];
        return (
          <li
            key={candidate.name}
            className={selectable ? "competitor-discovery-item" : "competitor-discovery-item blocked"}
            data-testid="competitor-discovery-item"
            data-selectable={selectable ? "true" : "false"}
          >
            <label className="competitor-discovery-row">
              <input
                type="checkbox"
                disabled={!selectable}
                checked={selectable && checked}
                aria-label={
                  selectable
                    ? `Seleccionar ${candidate.name}`
                    : `${candidate.name} sin cita cerrada (no seleccionable)`
                }
                onChange={(event) => onToggle(candidate.name, event.target.checked)}
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
