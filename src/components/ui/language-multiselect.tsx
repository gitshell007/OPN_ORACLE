"use client";

import { X } from "lucide-react";
import { FormEvent, useId, useMemo, useState } from "react";
import {
  filterSurveillanceLanguages,
  isIsoLanguageCode,
  languageName,
} from "@/lib/eu-countries";

/**
 * Multi-select de idiomas de vigilancia con filtro por nombre, código ISO o
 * alias (p. ej. «ale» / «alemán» → de). Reutiliza el layout del selector de
 * países para mantener la misma densidad en el wizard de mercado.
 */
export function LanguageMultiSelect({
  label,
  value,
  onChange,
  hint,
  disabled = false,
}: {
  label: string;
  value: string[];
  onChange(next: string[]): void;
  hint?: string;
  disabled?: boolean;
}) {
  const labelId = useId();
  const [filter, setFilter] = useState("");
  const [customCode, setCustomCode] = useState("");
  const [customError, setCustomError] = useState<string | null>(null);

  const selected = useMemo(
    () => value.map((code) => code.trim().toLowerCase()).filter(Boolean),
    [value],
  );

  const options = useMemo(
    () => filterSurveillanceLanguages(filter, selected),
    [filter, selected],
  );

  function toggle(code: string) {
    const key = code.toLowerCase();
    onChange(
      selected.includes(key)
        ? selected.filter((item) => item !== key)
        : [...selected, key],
    );
  }

  function addCustomCode(event: FormEvent) {
    event.preventDefault();
    const code = customCode.trim().toLowerCase();
    if (!isIsoLanguageCode(code)) {
      setCustomError("Usa un código ISO de idioma de 2 letras (p. ej. de, en, fr).");
      return;
    }
    setCustomError(null);
    if (!selected.includes(code)) {
      onChange([...selected, code]);
    }
    setCustomCode("");
  }

  return (
    <div className="field full eu-country-select language-select">
      <span id={labelId}>{label}</span>
      {selected.length > 0 && (
        <ul className="eu-country-chips" aria-label={`Seleccionados: ${label}`}>
          {selected.map((code) => (
            <li key={code}>
              <button
                type="button"
                disabled={disabled}
                onClick={() => toggle(code)}
                aria-label={`Quitar ${languageName(code)}`}
              >
                {languageName(code)}{" "}
                <small className="language-chip-code">{code}</small>{" "}
                <X size={12} aria-hidden="true" />
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
        placeholder="Buscar por nombre o código (ale, alemán, de…)"
        aria-label={`Filtrar ${label}`}
      />
      <div
        className="eu-country-options language-options"
        role="group"
        aria-labelledby={labelId}
        tabIndex={0}
      >
        {options.map((language) => (
          <label key={language.code}>
            <input
              type="checkbox"
              disabled={disabled}
              checked={selected.includes(language.code)}
              onChange={() => toggle(language.code)}
            />
            <span>{language.name}</span>
            <small>{language.code}</small>
          </label>
        ))}
        {options.length === 0 && (
          <p className="eu-country-empty">Sin coincidencias. Prueba «ale», «inglés» o el código ISO.</p>
        )}
      </div>
      <div className="eu-country-custom">
        <label>
          <span className="sr-only">Añadir idioma por código ISO</span>
          <input
            type="text"
            inputMode="text"
            maxLength={2}
            disabled={disabled}
            value={customCode}
            onChange={(event) => {
              setCustomCode(event.target.value.toLowerCase());
              setCustomError(null);
            }}
            placeholder="ISO (de)"
            aria-label="Código ISO de idioma no listado"
            aria-invalid={customError ? true : undefined}
          />
        </label>
        <button type="button" disabled={disabled} onClick={addCustomCode}>
          Añadir idioma
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
