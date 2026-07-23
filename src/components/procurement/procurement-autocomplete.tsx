"use client";

import {
  type KeyboardEvent as ReactKeyboardEvent,
  useId,
  useState,
} from "react";

interface ProcurementAutocompleteProps {
  label: string;
  value: string;
  placeholder?: string;
  suggestions: string[];
  loading?: boolean;
  loadingLabel?: string;
  describedBy?: string;
  invalid?: boolean;
  onChange: (value: string) => void;
  onSelect: (value: string) => void;
  onConfirmFreeText?: (value: string) => void;
}

export function ProcurementAutocomplete({
  label,
  value,
  placeholder,
  suggestions,
  loading = false,
  loadingLabel = "Buscando sugerencias…",
  describedBy,
  invalid = false,
  onChange,
  onSelect,
  onConfirmFreeText,
}: ProcurementAutocompleteProps) {
  const inputId = useId();
  const listboxId = useId();
  const [open, setOpen] = useState(false);
  const [activeIndex, setActiveIndex] = useState(-1);
  const showSuggestions = open && (loading || suggestions.length > 0);

  function chooseSuggestion(index: number) {
    const suggestion = suggestions[index];
    if (!suggestion) return;
    onSelect(suggestion);
    setActiveIndex(-1);
    setOpen(false);
  }

  function handleKeyDown(event: ReactKeyboardEvent<HTMLInputElement>) {
    if (event.key === "Escape") {
      setOpen(false);
      setActiveIndex(-1);
      return;
    }
    if (event.key === "ArrowDown" && suggestions.length > 0) {
      event.preventDefault();
      setOpen(true);
      setActiveIndex((current) =>
        current >= suggestions.length - 1 ? 0 : current + 1,
      );
      return;
    }
    if (event.key === "ArrowUp" && suggestions.length > 0) {
      event.preventDefault();
      setOpen(true);
      setActiveIndex((current) =>
        current <= 0 ? suggestions.length - 1 : current - 1,
      );
      return;
    }
    if (event.key === "Enter" && open && activeIndex >= 0) {
      event.preventDefault();
      chooseSuggestion(activeIndex);
      return;
    }
    if (event.key === "Enter" && onConfirmFreeText && value.trim()) {
      event.preventDefault();
      setOpen(false);
      onConfirmFreeText(value.trim());
    }
  }

  return (
    <div
      className="procurement-filter-autocomplete"
      onBlur={(event) => {
        if (!event.currentTarget.contains(event.relatedTarget as Node | null)) {
          setOpen(false);
          setActiveIndex(-1);
        }
      }}
    >
      <label htmlFor={inputId}>{label}</label>
      <input
        id={inputId}
        role="combobox"
        aria-autocomplete="list"
        aria-controls={listboxId}
        aria-expanded={showSuggestions}
        aria-activedescendant={
          activeIndex >= 0 ? `${listboxId}-${activeIndex}` : undefined
        }
        aria-describedby={describedBy}
        aria-invalid={invalid}
        value={value}
        placeholder={placeholder}
        onFocus={() => setOpen(true)}
        onChange={(event) => {
          onChange(event.target.value);
          setActiveIndex(-1);
          setOpen(true);
        }}
        onKeyDown={handleKeyDown}
      />
      {showSuggestions && (
        <div
          id={listboxId}
          className="procurement-filter-suggestions"
          role="listbox"
        >
          {loading && <small role="status">{loadingLabel}</small>}
          {suggestions.map((suggestion, index) => (
            <button
              id={`${listboxId}-${index}`}
              key={suggestion}
              type="button"
              role="option"
              aria-selected={index === activeIndex}
              onMouseDown={(event) => event.preventDefault()}
              onClick={() => chooseSuggestion(index)}
            >
              {suggestion}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
