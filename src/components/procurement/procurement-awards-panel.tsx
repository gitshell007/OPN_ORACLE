"use client";

import {
  api,
  type ProcurementAwardItem,
  type ProcurementAwardsResponse,
} from "@oracle/api-client";
import { ExternalLink, RefreshCw, Search } from "lucide-react";
import { type FormEvent, useState } from "react";
import { PinToDossierControl } from "./pin-to-dossier-control";
import { cpvLabel, formatDate, formatMoney, problemMessage } from "./procurement-helpers";

export function ProcurementAwardsPanel({
  initialCompany = "",
}: {
  initialCompany?: string;
}) {
  const [mode, setMode] = useState<"company" | "buyer">("company");
  const [query, setQuery] = useState(initialCompany);
  const [result, setResult] = useState<ProcurementAwardsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function load(event?: FormEvent) {
    event?.preventDefault();
    const value = query.trim();
    if (!value) return;
    setLoading(true);
    setError(null);
    try {
      const response = await api.procurement.awards({
        company: mode === "company" ? value : undefined,
        buyer: mode === "buyer" ? value : undefined,
        limit: 25,
        offset: 0,
      });
      setResult(response);
    } catch (reason) {
      setError(
        problemMessage(reason, "No se pudieron consultar adjudicaciones."),
      );
    } finally {
      setLoading(false);
    }
  }

  const items = result?.items ?? [];

  return (
    <section className="vector-panel procurement-awards-panel">
      <header>
        <div>
          <span className="section-kicker">Contratación pública</span>
          <h2>Adjudicaciones detectadas</h2>
        </div>
        <button
          className="vector-secondary"
          type="button"
          onClick={() => void load()}
          disabled={loading || !query.trim()}
        >
          <RefreshCw size={15} />
          Actualizar
        </button>
      </header>
      <form className="procurement-awards-search" onSubmit={load}>
        <label>
          <span>Buscar por</span>
          <select
            value={mode}
            onChange={(event) => setMode(event.target.value as "company" | "buyer")}
          >
            <option value="company">Adjudicatario</option>
            <option value="buyer">Órgano comprador</option>
          </select>
        </label>
        <label>
          <span>{mode === "company" ? "Empresa" : "Comprador"}</span>
          <div>
            <Search size={15} />
            <input
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={mode === "company" ? "Iturri" : "Gobierno de Aragón"}
            />
          </div>
        </label>
        <button className="vector-primary" type="submit" disabled={loading}>
          Buscar adjudicaciones
        </button>
      </form>
      {error && (
        <div className="inline-error" role="alert">
          {error}
        </div>
      )}
      {loading ? (
        <div className="global-inventory-state" role="status">
          Buscando adjudicaciones…
        </div>
      ) : items.length ? (
        <div className="procurement-awards-list">
          {items.map((item) => (
            <AwardCard key={`${item.folder_id}:${item.lot_id ?? "lot"}`} item={item} />
          ))}
        </div>
      ) : result ? (
        <div className="global-inventory-state">
          <strong>No hay adjudicaciones para esta búsqueda</strong>
          <p>Prueba con otra sociedad, UTE o comprador público.</p>
        </div>
      ) : (
        <p className="procurement-muted">
          Introduce una empresa para revisar contratos adjudicados y alimentar un expediente.
        </p>
      )}
    </section>
  );
}

function AwardCard({ item }: { item: ProcurementAwardItem }) {
  return (
    <article className="procurement-award-card">
      <header>
        <div>
          <strong>{item.title || "Adjudicación sin título"}</strong>
          <small>{item.buyer || "Comprador no publicado"}</small>
        </div>
        <span className="status">{item.status || "Adjudicada"}</span>
      </header>
      <dl>
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
          <dd>{item.lot_id || "Sin lote"}</dd>
        </div>
        <div>
          <dt>CPV</dt>
          <dd>{cpvLabel(item.cpv)}</dd>
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
        <PinToDossierControl compact kind="award" folderId={item.folder_id} />
      </footer>
    </article>
  );
}
