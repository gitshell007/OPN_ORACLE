"use client";

import { X } from "lucide-react";
import type {
  TenderSearchChip,
  TenderSearchChipDiff,
} from "./procurement-search-wizard-model";

const CHANGE_LABELS = {
  added: "Añadido",
  removed: "Retirado",
  retained: "Conservado",
} as const;

export function ProcurementPlanDiff({
  changes,
  version,
  onRemoveChip,
  onDiscardBaseline,
}: {
  changes: TenderSearchChipDiff[];
  version: number;
  onRemoveChip?: (chip: TenderSearchChip) => void;
  onDiscardBaseline?: () => void;
}) {
  const retained = changes.filter((item) => item.change === "retained");
  const added = changes.filter((item) => item.change === "added");
  const removed = changes.filter((item) => item.change === "removed");

  return (
    <section
      className="procurement-plan-diff"
      aria-labelledby="procurement-plan-diff-heading"
    >
      <header className="procurement-plan-diff-header">
        <div>
          <h3 id="procurement-plan-diff-heading">
            Cambios respecto a v{version}
          </h3>
          <p>
            Revisa cada cambio. Puedes quitar conservados con la × o descartar
            por completo la comparación con la versión anterior.
          </p>
        </div>
        {onDiscardBaseline && (
          <button
            type="button"
            className="vector-secondary compact"
            onClick={onDiscardBaseline}
          >
            Descartar versión anterior
          </button>
        )}
      </header>
      <div className="procurement-plan-diff-groups">
        {(
          [
            ["added", added],
            ["removed", removed],
          ] as const
        ).map(([change, items]) => (
          <div key={change}>
            <strong>
              {CHANGE_LABELS[change]} · {items.length}
            </strong>
            <div className="procurement-plan-diff-chip-list">
              {items.map(({ chip }) => (
                <span
                  className={`procurement-diff-chip change-${change}`}
                  key={`${change}:${chip.key}`}
                >
                  <b>{CHANGE_LABELS[change]}</b>
                  <span>
                    {chip.label && chip.category === "candidate_cpv"
                      ? `${chip.value} · ${chip.label}`
                      : chip.value}
                  </span>
                  <small>
                    {chip.provenance === "user"
                      ? "Usuario"
                      : chip.provenance === "measured"
                        ? "Medido"
                        : "IA"}
                  </small>
                </span>
              ))}
              {!items.length && <small>Sin cambios</small>}
            </div>
          </div>
        ))}
      </div>
      <div className="procurement-plan-diff-retained">
        <strong>
          {CHANGE_LABELS.retained} · {retained.length}
        </strong>
        <div className="procurement-plan-diff-chip-list">
          {retained.map(({ chip }) => (
            <span
              className="procurement-diff-chip change-retained"
              key={`retained:${chip.key}`}
            >
              <b>{CHANGE_LABELS.retained}</b>
              <span>
                {chip.label && chip.category === "candidate_cpv"
                  ? `${chip.value} · ${chip.label}`
                  : chip.value}
              </span>
              <small>
                {chip.provenance === "user"
                  ? "Usuario"
                  : chip.provenance === "measured"
                    ? "Medido"
                    : "IA"}
              </small>
              {onRemoveChip && (
                <button
                  type="button"
                  className="procurement-diff-chip-remove"
                  aria-label={`Eliminar ${chip.value}`}
                  onClick={() => onRemoveChip(chip)}
                >
                  <X size={11} />
                </button>
              )}
            </span>
          ))}
          {!retained.length && <small>Sin cambios</small>}
        </div>
      </div>
    </section>
  );
}
