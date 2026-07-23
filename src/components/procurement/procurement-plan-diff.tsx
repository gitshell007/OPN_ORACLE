"use client";

import type { TenderSearchChipDiff } from "./procurement-search-wizard-model";

const CHANGE_LABELS = {
  added: "Añadido",
  removed: "Retirado",
  retained: "Conservado",
} as const;

export function ProcurementPlanDiff({
  changes,
  version,
}: {
  changes: TenderSearchChipDiff[];
  version: number;
}) {
  return (
    <section
      className="procurement-plan-diff"
      aria-labelledby="procurement-plan-diff-heading"
    >
      <header>
        <div>
          <h3 id="procurement-plan-diff-heading">
            Cambios respecto a v{version}
          </h3>
          <p>
            La propuesta aún no modifica el plan aceptado. Revisa cada cambio
            antes de aceptar la siguiente versión.
          </p>
        </div>
      </header>
      <div className="procurement-plan-diff-groups">
        {(["added", "removed", "retained"] as const).map((change) => {
          const items = changes.filter((item) => item.change === change);
          return (
            <div key={change}>
              <strong>
                {CHANGE_LABELS[change]} · {items.length}
              </strong>
              <div>
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
          );
        })}
      </div>
    </section>
  );
}
