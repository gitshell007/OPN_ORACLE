"use client";

import { X } from "lucide-react";
import { FormEvent, useId, useMemo, useState } from "react";
import {
  PRESET_GEOGRAPHIES,
  PRIORITY_COUNTRY_CODES,
  euCountryName,
  isIsoGeographyCode,
} from "@/lib/eu-countries";

export function EuCountryMultiSelect({
  label,
  value,
  onChange,
  priorityCodes = PRIORITY_COUNTRY_CODES,
  hint,
  disabled = false,
}: {
  label: string;
  value: string[];
  onChange(next: string[]): void;
  priorityCodes?: readonly string[];
  hint?: string;
  disabled?: boolean;
}) {
  const labelId = useId();
  const [filter, setFilter] = useState("");
  const [customCode, setCustomCode] = useState("");
  const [customError, setCustomError] = useState<string | null>(null);

  const options = useMemo(() => {
    const priority = priorityCodes
      .map((code) => PRESET_GEOGRAPHIES.find((country) => country.code === code))
      .filter((country): country is (typeof PRESET_GEOGRAPHIES)[number] => Boolean(country));
    const rest = PRESET_GEOGRAPHIES.filter((country) => !priorityCodes.includes(country.code)).sort(
      (a, b) => a.name.localeCompare(b.name, "es"),
    );
    const ordered = [...priority, ...rest];
    // Valores ya seleccionados que no están en el catálogo (p. ej. API → ES-VC legado
    // o códigos custom) siguen siendo visibles y quitables.
    const known = new Set(ordered.map((item) => item.code));
    const orphanSelected = value
      .filter((code) => !known.has(code.toUpperCase()) && !known.has(code))
      .map((code) => ({
        code: code.toUpperCase(),
        name: euCountryName(code),
        languages: [] as readonly string[],
      }));
    const withOrphans = [...orphanSelected, ...ordered];
    const needle = filter.trim().toLowerCase();
    if (!needle) return withOrphans;
    return withOrphans.filter(
      (country) =>
        country.name.toLowerCase().includes(needle) ||
        country.code.toLowerCase().includes(needle),
    );
  }, [filter, priorityCodes, value]);

  function toggle(code: string) {
    onChange(value.includes(code) ? value.filter((item) => item !== code) : [...value, code]);
  }

  function addCustomCode(event: FormEvent) {
    event.preventDefault();
    const code = customCode.trim().toUpperCase();
    if (!isIsoGeographyCode(code)) {
      setCustomError("Usa ISO de país (ES) o subdivisión (ES-VC, ES-MD).");
      return;
    }
    setCustomError(null);
    if (!value.includes(code)) {
      onChange([...value, code]);
    }
    setCustomCode("");
  }

  return (
    <div className="field full eu-country-select">
      <span id={labelId}>{label}</span>
      {value.length > 0 && (
        <ul className="eu-country-chips" aria-label={`Seleccionados: ${label}`}>
          {value.map((code) => (
            <li key={code}>
              <button
                type="button"
                disabled={disabled}
                onClick={() => toggle(code)}
                aria-label={`Quitar ${euCountryName(code)}`}
              >
                {euCountryName(code)} <X size={12} aria-hidden="true" />
              </button>
            </li>
          ))}
        </ul>
      )}
      <input
        type="search"
        value={filter}
        disabled={disabled}
        onChange={(event) => setFilter(event.target.value)}
        placeholder="Filtrar países o CCAA…"
        aria-label={`Filtrar ${label}`}
      />
      <div
        className="eu-country-options"
        role="group"
        aria-labelledby={labelId}
        tabIndex={0}
      >
        {options.map((country) => (
          <label key={country.code} className={priorityCodes.includes(country.code) ? "priority" : ""}>
            <input
              type="checkbox"
              disabled={disabled}
              checked={value.includes(country.code)}
              onChange={() => toggle(country.code)}
            />
            <span>{country.name}</span>
            <small>
              {country.code}
              {priorityCodes.includes(country.code) ? " · prioritario" : ""}
            </small>
          </label>
        ))}
        {options.length === 0 && <p className="eu-country-empty">Sin coincidencias en el catálogo.</p>}
      </div>
      <div className="eu-country-custom">
        <label>
          <span className="sr-only">Añadir ámbito por código ISO</span>
          <input
            type="text"
            inputMode="text"
            maxLength={6}
            disabled={disabled}
            value={customCode}
            onChange={(event) => {
              setCustomCode(event.target.value.toUpperCase());
              setCustomError(null);
            }}
            placeholder="ISO (ES o ES-VC)"
            aria-label="Código ISO de país o subdivisión no listado"
            aria-invalid={customError ? true : undefined}
          />
        </label>
        <button type="button" disabled={disabled} onClick={addCustomCode}>
          Añadir ámbito
        </button>
      </div>
      {customError && (
        <small role="alert" className="eu-country-error">
          {customError}
        </small>
      )}
      {hint && <small>{hint}</small>}
    </div>
  );
}
