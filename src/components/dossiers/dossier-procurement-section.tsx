"use client";

import {
  api,
  type DossierProcurementItem,
} from "@oracle/api-client";
import { ExternalLink, RefreshCw, Trash2 } from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { PermissionGate } from "@/components/auth/auth-boundary";
import {
  formatDate,
  formatMoney,
  problemMessage,
  snapshotNumber,
  snapshotText,
} from "@/components/procurement/procurement-helpers";

function snapshotAmount(item: DossierProcurementItem): number | null {
  const direct = snapshotNumber(item.snapshot, [
    "amount",
    "award_amount",
    "budget",
    "estimated_value",
  ]);
  if (direct !== null) return direct;
  const entries = item.snapshot.entries;
  if (!Array.isArray(entries)) return null;
  const total = entries.reduce((sum, entry) => {
    if (!entry || typeof entry !== "object") return sum;
    const value = (entry as Record<string, unknown>).award_amount;
    return typeof value === "number" && Number.isFinite(value) ? sum + value : sum;
  }, 0);
  return total > 0 ? total : null;
}

function snapshotTitle(item: DossierProcurementItem): string {
  return (
    snapshotText(item.snapshot, ["title", "object", "subject", "contract_title"]) ||
    `${item.kind === "tender" ? "Licitación" : "Adjudicación"} ${item.folder_id}`
  );
}

function snapshotBuyer(item: DossierProcurementItem): string {
  return (
    snapshotText(item.snapshot, ["buyer", "contracting_authority", "organ"]) ||
    "Órgano no publicado"
  );
}

function snapshotDeadline(item: DossierProcurementItem): string | null {
  return snapshotText(item.snapshot, ["deadline", "deadline_date", "award_date"]);
}

function snapshotIsUte(item: DossierProcurementItem): boolean {
  if (item.snapshot.is_ute === true) return true;
  const entries = item.snapshot.entries;
  return Array.isArray(entries) && entries.some(
    (entry) => entry && typeof entry === "object" && (entry as Record<string, unknown>).is_ute === true,
  );
}

function awardEntriesSummary(item: DossierProcurementItem): string | null {
  const entries = item.snapshot.entries;
  if (!Array.isArray(entries) || entries.length === 0) return null;
  const winners = new Set<string>();
  for (const entry of entries) {
    if (!entry || typeof entry !== "object") continue;
    const winner = (entry as Record<string, unknown>).winner;
    if (typeof winner === "string" && winner.trim()) winners.add(winner);
  }
  return `${entries.length} lote${entries.length === 1 ? "" : "s"}${
    winners.size ? ` · ${Array.from(winners).slice(0, 3).join(", ")}` : ""
  }`;
}

export function DossierProcurementSection({ dossierId }: { dossierId: string }) {
  const [items, setItems] = useState<DossierProcurementItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [removingId, setRemovingId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const response = await api.dossierProcurement.list(dossierId);
      setItems(response.data);
    } catch (reason) {
      setError(
        problemMessage(
          reason,
          "No se pudieron cargar las referencias de contratación.",
        ),
      );
    } finally {
      setLoading(false);
    }
  }, [dossierId]);

  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  async function remove(itemId: string) {
    setRemovingId(itemId);
    setError(null);
    try {
      await api.dossierProcurement.remove(dossierId, itemId);
      setItems((current) => current.filter((item) => item.id !== itemId));
    } catch (reason) {
      setError(
        problemMessage(reason, "No se pudo desfijar la referencia."),
      );
    } finally {
      setRemovingId(null);
    }
  }

  return (
    <section className="vector-panel dossier-procurement-section" aria-busy={loading}>
      <header>
        <div>
          <span className="section-kicker">Contratación pública</span>
          <h2>Referencias fijadas al expediente</h2>
        </div>
        <button
          className="vector-secondary"
          type="button"
          onClick={() => void load()}
          disabled={loading}
        >
          <RefreshCw size={15} />
          Actualizar
        </button>
      </header>
      {error && (
        <div className="inline-error" role="alert">
          {error}
        </div>
      )}
      {loading ? (
        <div className="global-inventory-state" role="status">
          Cargando referencias de contratación…
        </div>
      ) : items.length ? (
        <div className="procurement-card-list">
          {items.map((item) => {
            const entries = awardEntriesSummary(item);
            const isUte = item.kind === "award" && snapshotIsUte(item);
            return (
              <article className="procurement-card" key={item.id}>
                <header>
                  <div>
                    <strong>{snapshotTitle(item)}</strong>
                    <small>{snapshotBuyer(item)}</small>
                  </div>
                  <div>
                    {isUte && <span className="status">UTE · En consorcio</span>}
                    <span className="status">
                      {item.kind === "tender" ? "Licitación" : "Adjudicación"}
                    </span>
                  </div>
                </header>
                {entries && <p>{entries}</p>}
                <dl>
                  <div>
                    <dt>Organismo licitador</dt>
                    <dd>{snapshotBuyer(item)}</dd>
                  </div>
                  <div>
                    <dt>Referencia</dt>
                    <dd>{item.folder_id}</dd>
                  </div>
                  <div>
                    <dt>{item.kind === "tender" ? "Plazo" : "Fecha"}</dt>
                    <dd>{formatDate(snapshotDeadline(item))}</dd>
                  </div>
                  <div>
                    <dt>Importe</dt>
                    <dd>{formatMoney(snapshotAmount(item))}</dd>
                  </div>
                  <div>
                    <dt>Evidencia</dt>
                    <dd>{item.evidence_id}</dd>
                  </div>
                </dl>
                <footer>
                  {item.source_url && (
                    <a
                      className="vector-secondary"
                      href={item.source_url}
                      target="_blank"
                      rel="noreferrer"
                    >
                      <ExternalLink size={14} />
                      Ver fuente oficial
                    </a>
                  )}
                  <PermissionGate permission="opportunity.write">
                    <button
                      className="vector-danger"
                      type="button"
                      disabled={removingId === item.id}
                      onClick={() => void remove(item.id)}
                    >
                      <Trash2 size={14} />
                      Desfijar
                    </button>
                  </PermissionGate>
                </footer>
              </article>
            );
          })}
        </div>
      ) : (
        <div className="global-inventory-state">
          <strong>No hay licitaciones o adjudicaciones fijadas</strong>
          <p>
            Puedes fijarlas desde Contratación pública o desde el panel de Actores.
          </p>
        </div>
      )}
    </section>
  );
}
