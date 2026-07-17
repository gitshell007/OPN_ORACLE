"use client";

import {
  api,
  type ProcurementAwardItem,
  type ProcurementAwardsResponse,
  type ProcurementSuggestKind,
} from "@oracle/api-client";
import { ExternalLink, RefreshCw, Search } from "lucide-react";
import { type FormEvent, useEffect, useRef, useState } from "react";
import { PinToDossierControl } from "./pin-to-dossier-control";
import { cpvLabel, formatDate, formatMoney, problemMessage } from "./procurement-helpers";

export function ProcurementAwardsPanel({
  initialCompany = "",
}: {
  initialCompany?: string;
}) {
  const [mode, setMode] = useState<"company" | "buyer">("company");
  const [query, setQuery] = useState(initialCompany);
  const [selectedExact, setSelectedExact] = useState(Boolean(initialCompany));
  const [suggestions, setSuggestions] = useState<string[]>([]);
  const [suggesting, setSuggesting] = useState(false);
  const [result, setResult] = useState<ProcurementAwardsResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const suggestKind: ProcurementSuggestKind = mode === "company" ? "winner" : "buyer";
  const suggestSequence = useRef(0);
  const latestSuggestInput = useRef({
    kind: suggestKind,
    query: query.trim(),
    selectedExact,
  });

  useEffect(() => {
    latestSuggestInput.current = {
      kind: suggestKind,
      query: query.trim(),
      selectedExact,
    };
  }, [query, selectedExact, suggestKind]);

  useEffect(() => {
    const value = query.trim();
    const requestKind = suggestKind;
    const sequence = suggestSequence.current + 1;
    suggestSequence.current = sequence;
    if (value.length < 2 || selectedExact) {
      return;
    }
    let cancelled = false;
    const kickoff = window.setTimeout(async () => {
      setSuggesting(true);
      try {
        const response = await api.procurement.suggest({
          q: value,
          kind: requestKind,
          limit: 8,
        });
        const latest = latestSuggestInput.current;
        if (
          !cancelled &&
          suggestSequence.current === sequence &&
          latest.query === value &&
          latest.kind === requestKind &&
          !latest.selectedExact
        ) {
          setSuggestions(response.suggestions);
        }
      } catch {
        const latest = latestSuggestInput.current;
        if (
          !cancelled &&
          suggestSequence.current === sequence &&
          latest.query === value &&
          latest.kind === requestKind &&
          !latest.selectedExact
        ) {
          setSuggestions([]);
        }
      } finally {
        const latest = latestSuggestInput.current;
        if (
          !cancelled &&
          suggestSequence.current === sequence &&
          latest.query === value &&
          latest.kind === requestKind
        ) {
          setSuggesting(false);
        }
      }
    }, 220);
    return () => {
      cancelled = true;
      window.clearTimeout(kickoff);
    };
  }, [query, selectedExact, suggestKind]);

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
            onChange={(event) => {
              const nextMode = event.target.value as "company" | "buyer";
              const nextKind: ProcurementSuggestKind = nextMode === "company" ? "winner" : "buyer";
              suggestSequence.current += 1;
              latestSuggestInput.current = { kind: nextKind, query: "", selectedExact: false };
              setMode(nextMode);
              setQuery("");
              setSelectedExact(false);
              setResult(null);
              setSuggestions([]);
            }}
          >
            <option value="company">Adjudicatario</option>
            <option value="buyer">Órgano comprador</option>
          </select>
        </label>
        <label className="procurement-autocomplete">
          <span>{mode === "company" ? "Adjudicatario registral" : "Órgano de contratación"}</span>
          <div>
            <Search size={15} />
            <input
              value={query}
              onChange={(event) => {
                const nextQuery = event.target.value;
                suggestSequence.current += 1;
                latestSuggestInput.current = {
                  kind: suggestKind,
                  query: nextQuery.trim(),
                  selectedExact: false,
                };
                setQuery(nextQuery);
                setSelectedExact(false);
                setSuggestions([]);
                if (nextQuery.trim().length < 2) setSuggesting(false);
              }}
              placeholder={mode === "company" ? "Iturri" : "Gobierno de Aragón"}
              aria-describedby="procurement-awards-help"
            />
          </div>
          {(suggestions.length > 0 || suggesting) && (
            <div className="procurement-suggestions" role="listbox">
              {suggesting && <small>Buscando denominaciones registrales…</small>}
              {suggestions.map((suggestion) => (
                <button
                  key={suggestion}
                  type="button"
                  role="option"
                  aria-selected={suggestion === query}
                  onClick={() => {
                    suggestSequence.current += 1;
                    latestSuggestInput.current = {
                      kind: suggestKind,
                      query: suggestion.trim(),
                      selectedExact: true,
                    };
                    setQuery(suggestion);
                    setSelectedExact(true);
                    setSuggestions([]);
                    setSuggesting(false);
                  }}
                >
                  {suggestion}
                </button>
              ))}
            </div>
          )}
        </label>
        <button className="vector-primary" type="submit" disabled={loading}>
          Buscar adjudicaciones
        </button>
      </form>
      <p id="procurement-awards-help" className="procurement-muted">
        La búsqueda usa la denominación registral exacta: escribe un prefijo y
        selecciona una sugerencia de adjudicatario u órgano de contratación.
      </p>
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
