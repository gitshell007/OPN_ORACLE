"""Offline access to the official Spanish Common Procurement Vocabulary."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Any

_CPV_DATA_PATH = Path(__file__).with_name("data") / "cpv_2008_es.json"
_CPV_PATTERN = re.compile(r"^(?P<code>\d{8})(?:-(?P<check_digit>\d))?$")


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
