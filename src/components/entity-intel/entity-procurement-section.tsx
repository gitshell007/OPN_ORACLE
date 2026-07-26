"use client";

import {
  api,
  type ProcurementAwardItem,
  type ProcurementAwardsResponse,
  type EntityIntelKind,
} from "@oracle/api-client";
import { ArrowUpDown, ExternalLink, FileSearch, RefreshCw } from "lucide-react";
import { useCallback, useEffect, useMemo, useState } from "react";
import { PinToDossierControl } from "@/components/procurement/pin-to-dossier-control";
import {
  cpvLabel,
  formatDate,
  formatMoney,
  problemMessage,
} from "@/components/procurement/procurement-helpers";

const PAGE_SIZE = 25;

type AwardSortKey =
  | "signal"
  | "date_desc"
  | "date_asc"
  | "amount_desc"
  | "amount_asc"
  | "buyer";

function awardAmount(item: ProcurementAwardItem): number {
  return typeof item.award_amount === "number" && Number.isFinite(item.award_amount)
    ? item.award_amount
    : Number.NEGATIVE_INFINITY;
}

function sortAwards(
  items: ProcurementAwardItem[],
  sort: AwardSortKey,
): ProcurementAwardItem[] {
  if (sort === "signal") return items;
  const copy = [...items];
  copy.sort((a, b) => {
    switch (sort) {
      case "date_desc":
      case "date_asc": {
        const da = a.award_date || "";
        const db = b.award_date || "";
        // Missing dates sink to the end in both directions.
        if (!da && !db) return 0;
        if (!da) return 1;
        if (!db) return -1;
        const cmp = da.localeCompare(db);
        return sort === "date_desc" ? -cmp : cmp;
      }
      case "amount_desc":
      case "amount_asc": {
        const aa = awardAmount(a);
        const ab = awardAmount(b);
        if (aa === ab) return (a.title || "").localeCompare(b.title || "", "es");
        return sort === "amount_desc" ? ab - aa : aa - ab;
      }
      case "buyer":
        return (a.buyer || "").localeCompare(b.buyer || "", "es", {
          sensitivity: "base",
        });
      default:
        return 0;
    }
  });
  return copy;
}

function AwardCard({ item }: { item: ProcurementAwardItem }) {
  const lotId =
    item.lot_id && /^[A-Za-z]\d{8}$/.test(item.lot_id.trim())
      ? null
      : item.lot_id;
  return (
    <article className="procurement-award-card">
      <header>
        <div>
          <strong>{item.title || "Adjudicación sin título"}</strong>
        </div>
        <div>
          {item.is_ute && <span className="status">UTE · En consorcio</span>}
          <span className="status">{item.status || "Adjudicada"}</span>
        </div>
      </header>
      <dl>
        <div>
          <dt>Organismo licitador</dt>
          <dd>{item.buyer || "No publicado"}</dd>
        </div>
        <div>
          <dt>Adjudicatario</dt>
          <dd>{item.winner || "No publicado"}</dd>
        </div>
        <div>
          <dt>Importe</dt>
          <dd>{formatMoney(item.award_amount)}</dd>
        </div>
        <div>
          <dt>Fecha</dt>
          <dd>{formatDate(item.award_date)}</dd>
        </div>
        <div>
          <dt>Lote</dt>
          <dd>{lotId || "Sin lote"}</dd>
        </div>
        <div>
          <dt>CPV</dt>
          <dd>{cpvLabel(item.cpv)}</dd>
        </div>
      </dl>
      <footer className="procurement-card-actions">
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
        <PinToDossierControl compact kind="award" folderId={item.folder_id} />
      </footer>
    </article>
  );
}

export function EntityProcurementSection({
  name,
  type,
  onTotalChange,
}: {
  name: string;
  type: EntityIntelKind;
  onTotalChange?: (total: number | null) => void;
}) {
  const [result, setResult] = useState<ProcurementAwardsResponse | null>(null);
  const [loading, setLoading] = useState(type === "company");
  const [error, setError] = useState<string | null>(null);
  const [offset, setOffset] = useState(0);
  const [sort, setSort] = useState<AwardSortKey>("date_desc");

  const load = useCallback(
    async (nextOffset = 0) => {
      if (type !== "company") {
        setResult(null);
        setLoading(false);
        onTotalChange?.(null);
        return;
      }
      setLoading(true);
      setError(null);
      try {
        const response = await api.procurement.awards({
          company: name,
          limit: PAGE_SIZE,
          offset: nextOffset,
        });
        setResult(response);
        setOffset(nextOffset);
        onTotalChange?.(
          typeof response.total === "number" ? response.total : response.items.length,
        );
      } catch (reason) {
        // Keep previous page on transient failures so pagination does not blank the list.
        onTotalChange?.(null);
        setError(
          problemMessage(
            reason,
            "No se pudieron consultar las adjudicaciones de esta entidad.",
          ),
        );
      } finally {
        setLoading(false);
      }
    },
    [name, onTotalChange, type],
  );

  useEffect(() => {
    const kickoff = window.setTimeout(() => void load(0), 0);
    return () => window.clearTimeout(kickoff);
  }, [load]);

  const rawItems = result?.items ?? [];
  const items = useMemo(() => sortAwards(rawItems, sort), [rawItems, sort]);
  const total = result?.total ?? 0;
  const amountSum = useMemo(
    () =>
      items.reduce(
        (sum, item) =>
          sum + (typeof item.award_amount === "number" ? item.award_amount : 0),
        0,
      ),
    [items],
  );

  if (type === "person") {
    return (
      <section className="entity-procurement-section">
        <EntitySourceNote
          title="Licitaciones y adjudicaciones"
          detail={
            "Signal publica adjudicaciones por sociedad adjudicataria u órgano comprador. " +
            "Para personas físicas no hay un histórico PLACSP filtrable por nombre en este contrato; " +
            "consulta la empresa vinculada o el workspace de contratación."
          }
        />
      </section>
    );
  }

  return (
    <section className="entity-procurement-section">
      <header className="entity-procurement-header">
        <div>
          <p className="section-kicker">Contratación pública · PLACSP</p>
          <h2>Adjudicaciones de {name}</h2>
          <p>
            Contratos en los que esta sociedad figura como adjudicataria (o como miembro de UTE)
            en el registro Signal. No es el universo de licitaciones abiertas: es el histórico de
            adjudicaciones filtrado por empresa.
          </p>
        </div>
        <button
          className="vector-secondary"
          type="button"
          disabled={loading}
          onClick={() => void load(offset)}
        >
          <RefreshCw size={15} className={loading ? "analytics-progress-spin" : undefined} />
          {loading ? "Consultando…" : "Actualizar"}
        </button>
      </header>

      {result && (
        <div className="entity-procurement-summary" aria-label="Resumen de adjudicaciones">
          <article>
            <span>Adjudicaciones (proveedor)</span>
            <strong>{new Intl.NumberFormat("es-ES").format(total)}</strong>
          </article>
          <article>
            <span>En esta página</span>
            <strong>{items.length}</strong>
          </article>
          <article>
            <span>Importe página</span>
            <strong>{formatMoney(amountSum || null)}</strong>
          </article>
          <article>
            <span>Denominación normalizada</span>
            <strong>{result.company_norm || name}</strong>
          </article>
        </div>
      )}

      {error && (
        <div className="inline-error" role="alert">
          {error}
          <button type="button" onClick={() => void load(offset)}>
            Reintentar
          </button>
        </div>
      )}

      {loading && !result ? (
        <div className="global-inventory-state" role="status">
          <FileSearch size={18} aria-hidden="true" />
          Consultando adjudicaciones PLACSP de {name}…
        </div>
      ) : items.length > 0 ? (
        <>
          <div className="entity-procurement-toolbar">
            <label>
              <span>
                <ArrowUpDown size={12} aria-hidden="true" /> Ordenar página
              </span>
              <select
                value={sort}
                onChange={(event) => setSort(event.target.value as AwardSortKey)}
                aria-label="Ordenar adjudicaciones de esta página"
              >
                <option value="date_desc">Fecha · más recientes</option>
                <option value="date_asc">Fecha · más antiguas</option>
                <option value="amount_desc">Importe · mayor a menor</option>
                <option value="amount_asc">Importe · menor a mayor</option>
                <option value="buyer">Organismo licitador · A-Z</option>
                <option value="signal">Orden del proveedor</option>
              </select>
            </label>
          </div>
          {sort !== "signal" && (
            <p className="procurement-local-sort-note" role="status">
              Orden local sobre los {items.length} resultados de esta página; no reordena los{" "}
              {total} del histórico del proveedor (Signal no expone orden global por fecha o
              importe).
            </p>
          )}
          <div className="procurement-awards-list">
            {items.map((item) => (
              <AwardCard
                key={`${item.folder_id}:${item.lot_id ?? "lot"}:${item.award_date ?? ""}:${item.title ?? ""}`}
                item={item}
              />
            ))}
          </div>
          {total > PAGE_SIZE && (
            <div className="entity-pagination">
              <button
                className="vector-secondary"
                type="button"
                disabled={offset <= 0 || loading}
                onClick={() => void load(Math.max(0, offset - PAGE_SIZE))}
              >
                Anterior
              </button>
              <span>
                {offset + 1}-{Math.min(offset + rawItems.length, total)} de {total}
                {loading ? " · cargando…" : ""}
              </span>
              <button
                className="vector-secondary"
                type="button"
                disabled={offset + PAGE_SIZE >= total || loading}
                onClick={() => void load(offset + PAGE_SIZE)}
              >
                Siguiente
              </button>
            </div>
          )}
        </>
      ) : result ? (
        <div className="global-inventory-state">
          <strong>Sin adjudicaciones en el registro para esta denominación</strong>
          <p>
            Prueba la forma registral exacta (Signal es sensible a la razón social). Si la
            empresa opera en UTE, el adjudicatario puede figurar con otro nombre.
          </p>
        </div>
      ) : null}

      <p className="entity-procurement-footnote">
        Fuente: Signal registry/awards. Oracle no inventa contratos: solo muestra lo que el
        proveedor devuelve para el filtro de empresa. Las licitaciones aún abiertas se consultan
        en el workspace de contratación; aquí se listan adjudicaciones históricas.
      </p>
    </section>
  );
}

function EntitySourceNote({ title, detail }: { title: string; detail: string }) {
  return (
    <div className="entity-source-status is-empty" role="status">
      <FileSearch size={18} aria-hidden="true" />
      <div>
        <strong>{title}</strong>
        <p>{detail}</p>
      </div>
    </div>
  );
}
