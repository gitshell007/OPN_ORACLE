"""Offline access to the official Spanish Common Procurement Vocabulary."""

from __future__ import annotations

import json
import re
import unicodedata
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

_CPV_DATA_PATH = Path(__file__).with_name("data") / "cpv_2008_es.json"
_CPV_PATTERN = re.compile(r"^(?P<code>\d{8})(?:-(?P<check_digit>\d))?$")
_CPV_PREFIX_PATTERN = re.compile(r"^\d{2,8}(?:-\d)?$")
CPV_SUGGESTION_MAX_LIMIT = 20


@dataclass(frozen=True, slots=True)
class CPVTaxonomy:
    """Versioned CPV labels loaded from the repository, never from the network."""

    version: str
    language: str
    source_uri: str
    downloaded_at: str
    codes: dict[str, str]

    def label(self, value: Any) -> str | None:
        code = normalize_cpv_code(value)
        return self.codes.get(code) if code is not None else None


def fold_search_text(value: str) -> str:
    """Fold case and accents for deterministic Spanish procurement search."""

    decomposed = unicodedata.normalize("NFKD", value)
    return "".join(
        character for character in decomposed if unicodedata.category(character) != "Mn"
    ).casefold()


def normalize_cpv_code(value: Any) -> str | None:
    """Return the eight-digit CPV notation used by Signal and the taxonomy.

    Signal production awards expose eight-digit strings.  The loader also accepts
    the official display form with a check digit (``XXXXXXXX-X``), but deliberately
    rejects labels, comma-separated collections and malformed values.
    """

    if not isinstance(value, str):
        return None
    match = _CPV_PATTERN.fullmatch(value.strip())
    return match.group("code") if match is not None else None


@lru_cache(maxsize=1)
def load_cpv_taxonomy() -> CPVTaxonomy:
    """Load and validate the packaged taxonomy once per process."""

    payload = json.loads(_CPV_DATA_PATH.read_text(encoding="utf-8"))
    metadata = payload.get("metadata")
    raw_codes = payload.get("codes")
    if not isinstance(metadata, dict) or not isinstance(raw_codes, dict):
        raise ValueError("La taxonomía CPV empaquetada no tiene el formato esperado.")

    codes: dict[str, str] = {}
    for raw_code, raw_label in raw_codes.items():
        code = normalize_cpv_code(raw_code)
        if code is None or not isinstance(raw_label, str) or not raw_label.strip():
            raise ValueError("La taxonomía CPV contiene un código o etiqueta no válido.")
        codes[code] = raw_label.strip()

    expected_count = metadata.get("code_count")
    if not isinstance(expected_count, int) or expected_count != len(codes):
        raise ValueError("La taxonomía CPV no coincide con el recuento declarado.")

    return CPVTaxonomy(
        version=str(metadata["version"]),
        language=str(metadata["language"]),
        source_uri=str(metadata["source_uri"]),
        downloaded_at=str(metadata["downloaded_at"]),
        codes=codes,
    )


@lru_cache(maxsize=512)
def _cached_cpv_suggestions(
    folded_query: str,
    code_prefix: str | None,
    limit: int,
) -> tuple[tuple[str, str], ...]:
    taxonomy = load_cpv_taxonomy()
    ranked: list[tuple[int, str, str]] = []
    for code, label in taxonomy.codes.items():
        prefix_match = code_prefix is not None and code.startswith(code_prefix)
        label_match = folded_query in fold_search_text(label)
        if prefix_match or label_match:
            ranked.append((0 if prefix_match else 1, code, label))
    ranked.sort(key=lambda item: (item[0], item[1]))
    return tuple((code, label) for _rank, code, label in ranked[:limit])


def suggest_cpv_codes(query: str, *, limit: int = 8) -> tuple[tuple[str, str], ...]:
    """Return a bounded local CPV lookup without exposing the full taxonomy.

    Official numeric prefixes and accent-folded label substrings are accepted.
    Results are cached in-process because the packaged CPV 2008 vocabulary is
    immutable for the lifetime of a release.
    """

    clean_query = " ".join(query.split())
    folded_query = fold_search_text(clean_query)
    if len(folded_query) < 2:
        raise ValueError("La consulta CPV debe incluir al menos dos caracteres.")
    if not 1 <= limit <= CPV_SUGGESTION_MAX_LIMIT:
        raise ValueError(f"El límite CPV debe estar entre 1 y {CPV_SUGGESTION_MAX_LIMIT}.")

    code_prefix: str | None = None
    if _CPV_PREFIX_PATTERN.fullmatch(clean_query):
        code_prefix = clean_query.split("-", maxsplit=1)[0]
    return _cached_cpv_suggestions(folded_query, code_prefix, limit)
