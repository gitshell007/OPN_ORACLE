"use client";

import { X } from "lucide-react";
import { useId, useMemo, useState } from "react";
import { EU_COUNTRIES, PRIORITY_COUNTRY_CODES, euCountryName } from "@/lib/eu-countries";

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

  const options = useMemo(() => {
    const priority = priorityCodes
      .map((code) => EU_COUNTRIES.find((country) => country.code === code))
      .filter((country): country is (typeof EU_COUNTRIES)[number] => Boolean(country));
    const rest = EU_COUNTRIES.filter((country) => !priorityCodes.includes(country.code)).sort(
      (a, b) => a.name.localeCompare(b.name, "es"),
    );
    const ordered = [...priority, ...rest];
    const needle = filter.trim().toLowerCase();
    if (!needle) return ordered;
    return ordered.filter(
      (country) =>
        country.name.toLowerCase().includes(needle) ||
        country.code.toLowerCase().includes(needle),
    );
  }, [filter, priorityCodes]);

  function toggle(code: string) {
    onChange(value.includes(code) ? value.filter((item) => item !== code) : [...value, code]);
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
        placeholder="Filtrar países…"
        aria-label={`Filtrar ${label}`}
      />
      <div className="eu-country-options" role="group" aria-labelledby={labelId}>
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
        {options.length === 0 && <p className="eu-country-empty">Sin coincidencias.</p>}
      </div>
      {hint && <small>{hint}</small>}
    </div>
  );
}
