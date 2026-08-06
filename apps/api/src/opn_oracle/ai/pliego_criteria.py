"""G12-UMBRAL · criterios y umbrales del pliego con provenance (sin cifras inventadas).

Separa tres familias que **no** pueden sustituirse en silencio:

1. ``award_weight`` — ponderación de criterios de adjudicación (p. ej. 70/30).
2. ``min_score_threshold`` — umbral mínimo de puntuación / solvencia evaluable
   (p. ej. 65 puntos si un solo licitador; 60 p.p. sobre la media si varios).
3. score/fit interno de Oracle — **fuera de este módulo**; nunca se materializa
   aquí como si fuera del pliego.

Estados de resolución (taxonomía acotada del dominio, sin segunda ontología):

- ``verified`` — valor(es) consistente(s) con al menos una cita en evidence.
- ``missing`` — no hay reparto/umbral verificable en el bag del expediente.
- ``conflict`` — dos o más fuentes citables discrepan; no se elige en silencio.

Nunca completa hasta 100 ni inventa 65/60 u otras cifras de demo.
"""

from __future__ import annotations

import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

ResolutionStatus = Literal["verified", "missing", "conflict"]
CriterionKind = Literal["award_weight", "min_score_threshold"]

RESOLUTION_VERIFIED: ResolutionStatus = "verified"
RESOLUTION_MISSING: ResolutionStatus = "missing"
RESOLUTION_CONFLICT: ResolutionStatus = "conflict"

KIND_AWARD_WEIGHT: CriterionKind = "award_weight"
KIND_MIN_THRESHOLD: CriterionKind = "min_score_threshold"

# ---------------------------------------------------------------------------
# Patterns — generic (no fixed 65/60). Context decides kind.
# ---------------------------------------------------------------------------

_TECH_LABEL = (
    r"(?:oferta\s+t[eé]cnica|criterio\s+t[eé]cnico|juicio\s+de\s+valor|"
    r"criterios?\s+t[eé]cnicos?|calidad(?:\s+t[eé]cnica)?)"
)
_ECON_LABEL = (
    r"(?:oferta\s+econ[oó]mica|criterio\s+econ[oó]mico|precio|"
    r"f[oó]rmulas?|criterios?\s+econ[oó]micos?)"
)

# Optional parenthetical / short filler between label and value (e.g. «(juicio de valor)»).
_GAP = r"(?:\s*\([^)]{0,60}\))?\s*[:.\-]?\s*"

# Ponderación: label + percent (either order). Allow short gap/parenthetical.
_AWARD_WEIGHT_TECH = re.compile(
    rf"(?P<label>{_TECH_LABEL}){_GAP}(?P<value>\d{{1,3}})\s*%"
    rf"|(?P<value2>\d{{1,3}})\s*%\s*(?:a\s+la\s+|para\s+la\s+|de\s+|en\s+)?"
    rf"(?P<label2>{_TECH_LABEL})",
    re.IGNORECASE,
)
_AWARD_WEIGHT_ECON = re.compile(
    rf"(?P<label>{_ECON_LABEL}){_GAP}(?P<value>\d{{1,3}})\s*%"
    rf"|(?P<value2>\d{{1,3}})\s*%\s*(?:a\s+la\s+|para\s+la\s+|de\s+|en\s+)?"
    rf"(?P<label2>{_ECON_LABEL})",
    re.IGNORECASE,
)
# Points that look like award split (not min threshold language).
_AWARD_POINTS_TECH = re.compile(
    rf"(?P<label>{_TECH_LABEL}){_GAP}(?P<value>\d{{1,3}})\s*puntos",
    re.IGNORECASE,
)
_AWARD_POINTS_ECON = re.compile(
    rf"(?P<label>{_ECON_LABEL}){_GAP}(?P<value>\d{{1,3}})\s*puntos",
    re.IGNORECASE,
)

# Umbrales mínimos — lenguaje de exclusión / mínimo, no de reparto.
_MIN_SINGLE = re.compile(
    r"(?:superior\s+a\s+(?:los\s+)?|puntuaci[oó]n\s+m[ií]nima(?:\s+de)?\s+|"
    r"umbral\s+(?:m[ií]nimo\s+)?(?:de\s+)?)"
    r"(?P<value>\d{1,3})\s*puntos"
    r"(?!\s+porcentuales)",
    re.IGNORECASE,
)
_MIN_MULTI_PP = re.compile(
    r"superior\s+en\s+(?P<value>\d{1,3})\s*puntos\s+porcentuales",
    re.IGNORECASE,
)
_MIN_GENERIC = re.compile(
    r"(?:umbral|m[ií]nimo(?:\s+exigible)?|puntuaci[oó]n\s+m[ií]nima)"
    r"[^\n\d]{0,40}?(?P<value>\d{1,3})\s*(?P<unit>puntos|%)",
    re.IGNORECASE,
)

# Block presence (for limitations / draft sectioning) without inventing numbers.
_CRITERIA_BLOCK = re.compile(
    r"CRITERIOS?\s+DE\s+ADJUDICACI[OÓ]N|mejor\s+relaci[oó]n\s+calidad.?precio|"
    r"adjudicaci[oó]n\s+se\s+realiza",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class CriterionHit:
    kind: CriterionKind
    role: str  # e.g. technical, economic, single_bidder, multi_bidder_pp
    value: float
    unit: str  # percent | points | percentage_points
    evidence_id: str
    quote: str
    source_kind: str | None = None


@dataclass
class PliegoCriteriaResolution:
    """Bounded, PII-free resolution of pliego award criteria / thresholds."""

    award_weights_status: ResolutionStatus = RESOLUTION_MISSING
    min_thresholds_status: ResolutionStatus = RESOLUTION_MISSING
    award_weights: list[dict[str, Any]] = field(default_factory=list)
    min_score_thresholds: list[dict[str, Any]] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    provenance: list[dict[str, Any]] = field(default_factory=list)
    has_criteria_block: bool = False

    def to_public(self) -> dict[str, Any]:
        """Payload block for context / prompt (no free-text PII beyond short quotes)."""

        overall = _overall_status(
            self.award_weights_status,
            self.min_thresholds_status,
            has_any=bool(self.award_weights or self.min_score_thresholds),
        )
        return {
            "schema": "pliego_criteria.v1",
            "status": overall,
            "award_weights": {
                "status": self.award_weights_status,
                "kind": KIND_AWARD_WEIGHT,
                "items": list(self.award_weights),
            },
            "min_score_thresholds": {
                "status": self.min_thresholds_status,
                "kind": KIND_MIN_THRESHOLD,
                "items": list(self.min_score_thresholds),
            },
            # Explicit non-substitution: Oracle fit scores are never filled here.
            "oracle_internal_fit": {
                "status": RESOLUTION_MISSING,
                "kind": "oracle_internal_fit",
                "items": [],
                "note": "score/fit interno de Oracle no se deriva del pliego en este bloque",
            },
            "has_criteria_block": self.has_criteria_block,
            "limitations": list(self.limitations),
            "provenance": list(self.provenance),
        }


def _overall_status(
    weights: ResolutionStatus,
    thresholds: ResolutionStatus,
    *,
    has_any: bool,
) -> ResolutionStatus:
    if weights == RESOLUTION_CONFLICT or thresholds == RESOLUTION_CONFLICT:
        return RESOLUTION_CONFLICT
    if weights == RESOLUTION_VERIFIED or thresholds == RESOLUTION_VERIFIED:
        return RESOLUTION_VERIFIED
    if has_any:
        return RESOLUTION_VERIFIED
    return RESOLUTION_MISSING


def _clip_quote(text: str, start: int, end: int, *, window: int = 120) -> str:
    lo = max(0, start - 20)
    hi = min(len(text), end + window)
    snippet = " ".join(text[lo:hi].split())
    if len(snippet) > 220:
        snippet = snippet[:217] + "…"
    return snippet


def _percent_or_points_value(raw: str) -> float | None:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    if value < 0 or value > 100:
        return None
    return value


def _scan_weights(extract: str, evidence_id: str, source_kind: str | None) -> list[CriterionHit]:
    hits: list[CriterionHit] = []
    for pattern, role, unit in (
        (_AWARD_WEIGHT_TECH, "technical", "percent"),
        (_AWARD_WEIGHT_ECON, "economic", "percent"),
        (_AWARD_POINTS_TECH, "technical", "points"),
        (_AWARD_POINTS_ECON, "economic", "points"),
    ):
        for match in pattern.finditer(extract):
            raw = match.groupdict().get("value") or match.groupdict().get("value2")
            if raw is None:
                continue
            value = _percent_or_points_value(raw)
            if value is None:
                continue
            hits.append(
                CriterionHit(
                    kind=KIND_AWARD_WEIGHT,
                    role=role,
                    value=value,
                    unit=unit,
                    evidence_id=evidence_id,
                    quote=_clip_quote(extract, match.start(), match.end()),
                    source_kind=source_kind,
                )
            )
    return hits


def _scan_thresholds(extract: str, evidence_id: str, source_kind: str | None) -> list[CriterionHit]:
    hits: list[CriterionHit] = []
    covered_spans: list[tuple[int, int]] = []

    def _add(match: re.Match[str], role: str, unit: str) -> None:
        raw = match.group("value")
        value = _percent_or_points_value(raw)
        if value is None:
            return
        span = (match.start(), match.end())
        # Skip if this span is already covered by a more specific pattern.
        for lo, hi in covered_spans:
            if span[0] >= lo and span[1] <= hi:
                return
            if lo >= span[0] and hi <= span[1]:
                return
        covered_spans.append(span)
        hits.append(
            CriterionHit(
                kind=KIND_MIN_THRESHOLD,
                role=role,
                value=value,
                unit=unit,
                evidence_id=evidence_id,
                quote=_clip_quote(extract, match.start(), match.end()),
                source_kind=source_kind,
            )
        )

    # Specific language first (single-bidder min points, multi-bidder p.p.).
    for match in _MIN_SINGLE.finditer(extract):
        _add(match, "single_bidder_min_points", "points")
    for match in _MIN_MULTI_PP.finditer(extract):
        _add(match, "multi_bidder_pp_above_mean", "percentage_points")
    # Generic only for residual "umbral/mínimo … N" not already captured.
    for match in _MIN_GENERIC.finditer(extract):
        unit = "percent" if match.group("unit") == "%" else "points"
        _add(match, "minimum_score", unit)
    return hits


def _dedupe_hits(hits: Sequence[CriterionHit]) -> list[CriterionHit]:
    seen: set[tuple[str, str, float, str, str]] = set()
    out: list[CriterionHit] = []
    for hit in hits:
        key = (hit.kind, hit.role, hit.value, hit.unit, hit.evidence_id)
        if key in seen:
            continue
        seen.add(key)
        out.append(hit)
    return out


def _resolve_role_group(
    hits: Sequence[CriterionHit],
) -> tuple[ResolutionStatus, list[dict[str, Any]], list[dict[str, Any]], list[str]]:
    """Group by role; conflict if same role has distinct values across evidence."""

    if not hits:
        return RESOLUTION_MISSING, [], [], []

    by_role: dict[str, list[CriterionHit]] = {}
    for hit in hits:
        by_role.setdefault(hit.role, []).append(hit)

    items: list[dict[str, Any]] = []
    provenance: list[dict[str, Any]] = []
    limitations: list[str] = []
    status: ResolutionStatus = RESOLUTION_VERIFIED

    for role, group in sorted(by_role.items()):
        values = {(h.value, h.unit) for h in group}
        if len(values) > 1:
            status = RESOLUTION_CONFLICT
            limitations.append(
                f"Conflicto en {group[0].kind}/{role}: valores {[f'{v}{u}' for v, u in values]} "
                "sin autoridad de desempate; no se elige en silencio."
            )
            for h in group:
                provenance.append(
                    {
                        "kind": h.kind,
                        "role": role,
                        "field": f"{h.kind}.{role}",
                        "value": h.value,
                        "unit": h.unit,
                        "evidence_id": h.evidence_id,
                        "source_kind": h.source_kind,
                        "quote": h.quote,
                        "status": RESOLUTION_CONFLICT,
                    }
                )
            # Expose conflicting candidates without picking a winner.
            items.append(
                {
                    "role": role,
                    "status": RESOLUTION_CONFLICT,
                    "candidates": [
                        {
                            "value": h.value,
                            "unit": h.unit,
                            "evidence_id": h.evidence_id,
                            "quote": h.quote,
                        }
                        for h in group
                    ],
                }
            )
            continue

        # Consistent value (possibly repeated across docs → verified with multi-cite).
        primary = group[0]
        evidence_ids = sorted({h.evidence_id for h in group if h.evidence_id})
        items.append(
            {
                "role": role,
                "status": RESOLUTION_VERIFIED,
                "value": primary.value,
                "unit": primary.unit,
                "evidence_ids": evidence_ids,
                "quote": primary.quote,
            }
        )
        for h in group:
            provenance.append(
                {
                    "kind": h.kind,
                    "role": role,
                    "field": f"{h.kind}.{role}",
                    "value": h.value,
                    "unit": h.unit,
                    "evidence_id": h.evidence_id,
                    "source_kind": h.source_kind,
                    "quote": h.quote,
                    "status": RESOLUTION_VERIFIED,
                }
            )

    return status, items, provenance, limitations


def resolve_pliego_criteria(
    evidence_items: Sequence[Mapping[str, Any]] | None,
    *,
    allowed_evidence_ids: Sequence[str] | None = None,
) -> PliegoCriteriaResolution:
    """Resolve award weights + min thresholds from citable evidence only.

    ``allowed_evidence_ids`` when provided acts as allowlist (tenant/dossier bag).
    Empty/None evidence → missing (never invent).
    """

    allow: set[str] | None = None
    if allowed_evidence_ids is not None:
        allow = {str(x) for x in allowed_evidence_ids if x}

    weight_hits: list[CriterionHit] = []
    threshold_hits: list[CriterionHit] = []
    has_block = False

    for raw in evidence_items or ():
        if not isinstance(raw, Mapping):
            continue
        eid = str(raw.get("id") or "").strip()
        if not eid:
            continue
        if allow is not None and eid not in allow:
            continue
        extract = str(raw.get("extract") or "")
        if not extract.strip():
            continue
        source_kind = str(raw.get("source_kind") or "") or None
        if _CRITERIA_BLOCK.search(extract):
            has_block = True
        weight_hits.extend(_scan_weights(extract, eid, source_kind))
        threshold_hits.extend(_scan_thresholds(extract, eid, source_kind))

    weight_hits = _dedupe_hits(weight_hits)
    threshold_hits = _dedupe_hits(threshold_hits)

    w_status, w_items, w_prov, w_lim = _resolve_role_group(weight_hits)
    t_status, t_items, t_prov, t_lim = _resolve_role_group(threshold_hits)

    limitations = list(w_lim) + list(t_lim)
    if w_status == RESOLUTION_MISSING:
        limitations.append(
            "Ponderación de criterios de adjudicación: desconocido/no verificable en el "
            "pliego del expediente (no se inventan porcentajes ni se completa a 100)."
        )
    if t_status == RESOLUTION_MISSING:
        limitations.append(
            "Umbral mínimo de puntuación: desconocido/no verificable en el pliego del "
            "expediente (no se confunde con ponderación ni con score/fit de Oracle)."
        )
    if has_block and w_status == RESOLUTION_MISSING and t_status == RESOLUTION_MISSING:
        limitations.append(
            "Hay bloque de criterios de adjudicación en evidencia, pero sin cifras "
            "verificables de reparto ni umbral; declarar limitación al responder."
        )

    return PliegoCriteriaResolution(
        award_weights_status=w_status,
        min_thresholds_status=t_status,
        award_weights=w_items,
        min_score_thresholds=t_items,
        limitations=limitations,
        provenance=w_prov + t_prov,
        has_criteria_block=has_block,
    )


def format_criteria_security_clause(resolution: PliegoCriteriaResolution | Mapping[str, Any]) -> str:
    """Short clause for security_instruction — never hardcodes 65/60."""

    public = (
        resolution.to_public()
        if isinstance(resolution, PliegoCriteriaResolution)
        else dict(resolution)
    )
    status = str(public.get("status") or RESOLUTION_MISSING)
    weights = public.get("award_weights") if isinstance(public.get("award_weights"), dict) else {}
    thresholds = (
        public.get("min_score_thresholds")
        if isinstance(public.get("min_score_thresholds"), dict)
        else {}
    )
    w_status = str(weights.get("status") or RESOLUTION_MISSING)
    t_status = str(thresholds.get("status") or RESOLUTION_MISSING)

    parts = [
        "Criterios del pliego: usa solo el bloque pliego_criteria (schema pliego_criteria.v1) "
        "y los extractos citados. Separa ponderación (award_weights), umbral mínimo "
        "(min_score_thresholds) y score/fit interno de Oracle; no los sustituyas.",
        f"Estado global pliego_criteria={status}; ponderación={w_status}; umbrales={t_status}.",
    ]
    if w_status == RESOLUTION_MISSING or t_status == RESOLUTION_MISSING or status == RESOLUTION_MISSING:
        parts.append(
            "Si falta reparto o umbral verificable, responde desconocido/no verificable; "
            "no inventes ni completes porcentajes."
        )
    if status == RESOLUTION_CONFLICT or w_status == RESOLUTION_CONFLICT or t_status == RESOLUTION_CONFLICT:
        parts.append(
            "Hay conflicto entre documentos/versiones: no elijas un valor en silencio; "
            "expón el conflicto y las citas."
        )
    return " ".join(parts)


def format_award_weights_hint(resolution: PliegoCriteriaResolution) -> str:
    """Human-readable points_hint for draft sections (evidence-backed only)."""

    if resolution.award_weights_status == RESOLUTION_CONFLICT:
        return "ponderación en conflicto · ver pliego_criteria"
    if resolution.award_weights_status != RESOLUTION_VERIFIED or not resolution.award_weights:
        return "ponderación no verificable en el pliego"
    bits: list[str] = []
    for item in resolution.award_weights:
        if item.get("status") != RESOLUTION_VERIFIED:
            continue
        role = str(item.get("role") or "")
        value = item.get("value")
        unit = str(item.get("unit") or "")
        unit_s = "%" if unit == "percent" else (" pts" if unit == "points" else f" {unit}")
        label = {
            "technical": "técnica",
            "economic": "económica",
        }.get(role, role)
        bits.append(f"{label} {value}{unit_s}")
    return " · ".join(bits) if bits else "ponderación no verificable en el pliego"


def format_threshold_hint(resolution: PliegoCriteriaResolution) -> str:
    if resolution.min_thresholds_status == RESOLUTION_CONFLICT:
        return "umbrales en conflicto · ver pliego_criteria"
    if resolution.min_thresholds_status != RESOLUTION_VERIFIED or not resolution.min_score_thresholds:
        return "umbral mínimo no verificable en el pliego"
    bits: list[str] = []
    for item in resolution.min_score_thresholds:
        if item.get("status") != RESOLUTION_VERIFIED:
            continue
        role = str(item.get("role") or "")
        value = item.get("value")
        unit = str(item.get("unit") or "")
        if role == "single_bidder_min_points":
            bits.append(f"único licitador ≥ {value} pts")
        elif role == "multi_bidder_pp_above_mean":
            bits.append(f"varios: +{value} p.p. sobre media")
        else:
            unit_s = "%" if unit == "percent" else (
                " pts" if unit == "points" else (
                    " p.p." if unit == "percentage_points" else f" {unit}"
                )
            )
            bits.append(f"{role} {value}{unit_s}")
    return " · ".join(bits) if bits else "umbral mínimo no verificable en el pliego"


def format_threshold_requirement_clause(resolution: PliegoCriteriaResolution) -> str:
    """Official requirement appendix only when thresholds are verified (quoted)."""

    if resolution.min_thresholds_status == RESOLUTION_CONFLICT:
        return (
            " Umbrales de puntuación en **conflicto** entre evidencias del expediente; "
            "no se afirma un valor único. Ver pliego_criteria.min_score_thresholds."
        )
    if resolution.min_thresholds_status != RESOLUTION_VERIFIED:
        return (
            " Umbral mínimo de puntuación: desconocido/no verificable en el extracto "
            "del pliego (no se asume ningún valor fijo de demo)."
        )
    clauses: list[str] = []
    for item in resolution.min_score_thresholds:
        if item.get("status") != RESOLUTION_VERIFIED:
            continue
        quote = str(item.get("quote") or "").strip()
        value = item.get("value")
        role = str(item.get("role") or "")
        if role == "single_bidder_min_points":
            clauses.append(
                f"umbral único licitador = {value} puntos"
                + (f" («{quote}»)" if quote else "")
            )
        elif role == "multi_bidder_pp_above_mean":
            clauses.append(
                f"umbral varios licitadores = {value} puntos porcentuales sobre la media"
                + (f" («{quote}»)" if quote else "")
            )
        else:
            unit = str(item.get("unit") or "")
            unit_s = "%" if unit == "percent" else (
                " puntos" if unit == "points" else (
                    " puntos porcentuales" if unit == "percentage_points" else f" {unit}"
                )
            )
            clauses.append(
                f"{role}={value}{unit_s}" + (f" («{quote}»)" if quote else "")
            )
    if not clauses:
        return (
            " Umbral mínimo de puntuación: desconocido/no verificable en el extracto "
            "del pliego (no se asume ningún valor fijo de demo)."
        )
    return " El PCAP fija: " + "; ".join(clauses) + "."
