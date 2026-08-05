"""G06 · política de ``source_urls`` sin red (sin fetch saliente).

Valida forma http(s) + host real y **etiqueta siempre** como «no verificada».
No demuestra que la URL exista ni que respalde al candidato: solo evita
presentar basura como si fuera fuente y deja el estado honesto en API/UI.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from typing import Any
from urllib.parse import urlparse

# Etiqueta canónica visible en API y UI.
SOURCE_URL_UNVERIFIED_LABEL = "no verificada"
SOURCE_URL_UNVERIFIED_STATUS = "no_verificada"

_HOST_RE = re.compile(
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,}$|"
    r"^(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?)$",
    re.IGNORECASE,
)
# Hosts que no cuentan como "reales" para una fuente externa.
_BLOCKED_HOSTS = frozenset(
    {
        "localhost",
        "localhost.localdomain",
        "127.0.0.1",
        "0.0.0.0",
        "::1",
        "example",
        "example.com",
        "example.org",
        "example.net",
        "invalid",
        "test",
        "local",
    }
)


def is_valid_http_source_url(value: str) -> bool:
    """True si es http(s) con host real (DNS-like), sin credenciales ni basura.

    No hace DNS ni HTTP: solo forma. ``example.com`` y loopback se rechazan.
    """

    raw = str(value or "").strip()
    if not raw or len(raw) > 1500 or any(ch.isspace() for ch in raw):
        return False
    try:
        parsed = urlparse(raw)
    except ValueError:
        return False
    if parsed.scheme not in {"http", "https"}:
        return False
    if parsed.username or parsed.password:
        return False
    host = (parsed.hostname or "").strip().rstrip(".").lower()
    if not host or host in _BLOCKED_HOSTS:
        return False
    # IPv4 simple: no es host de fuente web "real" para este producto.
    if re.fullmatch(r"\d{1,3}(?:\.\d{1,3}){3}", host):
        return False
    if not _HOST_RE.match(host):
        return False
    # Exigir al menos un punto (dominio.tld); localhost/IP ya se rechazaron arriba.
    return "." in host


def sanitize_source_urls(urls: Sequence[Any] | None, *, max_items: int = 5) -> list[str]:
    """Devuelve solo URLs http(s) con host real, deduplicadas, cap ``max_items``."""

    out: list[str] = []
    seen: set[str] = set()
    for raw in urls or []:
        url = str(raw or "").strip()
        if not url or url in seen:
            continue
        if not is_valid_http_source_url(url):
            continue
        seen.add(url)
        out.append(url)
        if len(out) >= max_items:
            break
    return out


def annotate_source_urls(urls: Sequence[Any] | None, *, max_items: int = 5) -> list[dict[str, Any]]:
    """Anota cada URL válida con status/label «no verificada» (nunca «verificada»)."""

    annotated: list[dict[str, Any]] = []
    for url in sanitize_source_urls(urls, max_items=max_items):
        annotated.append(
            {
                "url": url,
                "status": SOURCE_URL_UNVERIFIED_STATUS,
                "label": SOURCE_URL_UNVERIFIED_LABEL,
                "verified": False,
            }
        )
    return annotated


def apply_source_url_policy_to_candidates(
    candidates: Sequence[Mapping[str, Any] | Any] | None,
    *,
    max_urls: int = 5,
) -> list[dict[str, Any]]:
    """Normaliza candidatos de discovery: source_urls saneados + meta no verificada."""

    out: list[dict[str, Any]] = []
    for raw in candidates or []:
        if not isinstance(raw, Mapping):
            continue
        row = dict(raw)
        cleaned = sanitize_source_urls(row.get("source_urls"), max_items=max_urls)
        meta = annotate_source_urls(cleaned, max_items=max_urls)
        row["source_urls"] = cleaned
        row["source_urls_meta"] = meta
        # Alias plano para UI/API sin anidar: misma etiqueta en cada entrada.
        row["source_urls_status"] = SOURCE_URL_UNVERIFIED_STATUS if cleaned else None
        row["source_urls_label"] = SOURCE_URL_UNVERIFIED_LABEL if cleaned else None
        out.append(row)
    return out


def apply_source_url_policy_to_output(output: dict[str, Any]) -> dict[str, Any]:
    """Aplica la política a un output tipo MarketCompetitorDiscoveryOutput."""

    result = dict(output)
    candidates = result.get("candidates")
    if isinstance(candidates, list):
        result["candidates"] = apply_source_url_policy_to_candidates(candidates)
    warnings = list(result["warnings"]) if isinstance(result.get("warnings"), list) else []
    # Aviso de producto: las URLs nunca se verifican con red.
    note = (
        "Las source_urls se validan solo en forma (http/https + host) y se etiquetan "
        f"«{SOURCE_URL_UNVERIFIED_LABEL}»; no se comprueba su contenido en red."
    )
    if note not in warnings:
        # Solo si hay alguna URL en candidatos.
        has_urls = any(
            isinstance(c, dict) and c.get("source_urls") for c in (result.get("candidates") or [])
        )
        if has_urls:
            warnings.append(note)
    result["warnings"] = warnings
    return result
