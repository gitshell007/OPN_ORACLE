"""Puntuación de encaje perfil declarado ↔ pliego/licitación (SV2-ENCAJE).

Motor determinista (coste 0) que produce las dimensiones de ``fit_assessment``
con citas duales:

- **oficial**: requisito del pliego / evidencia procurement / documento
- **declarado**: capacidad del perfil del expediente (``source_kind=declared``)

«No evaluable con lo declarado» es un resultado válido: no inventa volumen
anual, certificaciones ni capacidad de reacción no declarada.

El veredicto es **propuesta** con puerta humana (nunca decisión automática).
"""

from __future__ import annotations

import re
import uuid
from datetime import date, datetime, timezone
from typing import Any, Literal

from opn_oracle.oracle.cpv_taxonomy import normalize_cpv_code

FitStatus = Literal["fit", "partial", "no_fit", "not_evaluable"]
FitVerdictRec = Literal["go", "no_go", "go_conditioned"]
DimensionKey = Literal["cpv", "solvency", "lots", "deadline"]

_NOT_EVALUABLE = "no evaluable con lo declarado"
_HUMAN_GATE = "awaiting_user_confirmation"

# Prefijos CPV habituales de software / servicios TI / IA (división 72 / 48).
_IT_CPV_PREFIXES = ("72", "48", "722", "720", "7221", "7222", "7226", "480")

_CPV_IN_TEXT = re.compile(r"\b(\d{8})(?:-\d)?\b")
_DEADLINE_ISO = re.compile(
    r"(?:deadline|plazo|presentaci[oó]n|cierre|fecha.?l[ií]mite)[^\d]{0,40}"
    r"(\d{4}-\d{2}-\d{2})",
    re.IGNORECASE,
)
_DEADLINE_ES = re.compile(
    r"(?:deadline|plazo|presentaci[oó]n|cierre)[^\d]{0,40}"
    r"(\d{1,2})[/-](\d{1,2})[/-](\d{4})",
    re.IGNORECASE,
)
_AMOUNT = re.compile(
    r"(?:importe|valor estimado|presupuesto|amount)[^\d]{0,40}"
    r"(\d{1,3}(?:[.\s]\d{3})*(?:,\d+)?|\d+(?:[.,]\d+)?)\s*(?:EUR|€|euros?)?",
    re.IGNORECASE,
)
# Título de lote: corta ante otro «Lote N», barra de listado compacto o cierre ).
_LOT_LINE = re.compile(
    r"Lote\s*(\d+)\s*[:.\-–—]\s*([^\n;|/]{3,80}?)(?=\s*/\s*Lote\s*\d|\s*\)\s*$|$|\n)",
    re.IGNORECASE,
)
_SOLVENCY_ECON = re.compile(
    r"(F\.?\s*2|solvencia\s+econ[oó]mica|volumen\s+anual\s+de\s+negocio|"
    r"una\s+vez\s+y\s+media|1[,.]5\s*×|1[,.]5\s*x)",
    re.IGNORECASE,
)
_SOLVENCY_TECH = re.compile(
    r"(F\.?\s*3|solvencia\s+t[eé]cnica|servicios\s+ejecutados|"
    r"ultimos\s+tres\s+a[nñ]os|últimos\s+tres\s+a[nñ]os|"
    r"tres\s+últimos\s+a[nñ]os|certificados?\s+de\s+buena\s+ejecuci[oó]n)",
    re.IGNORECASE,
)
_AI_SOFTWARE_HINTS = re.compile(
    r"\b(software|inteligencia\s+artificial|\bIA\b|agentes?\s+inteligentes?|"
    r"plataformas?|servicios?\s+(?:de\s+)?TI|tecnolog[ií]a|"
    r"digitalizaci[oó]n|ciberseguridad|modernizaci[oó]n)\b",
    re.IGNORECASE,
)


def _as_of(value: date | datetime | None) -> date:
    if value is None:
        return datetime.now(timezone.utc).date()
    if isinstance(value, datetime):
        return value.date()
    return value


def _parse_amount(text: str) -> float | None:
    match = _AMOUNT.search(text)
    if not match:
        return None
    raw = match.group(1).replace(" ", "").replace(".", "").replace(",", ".")
    try:
        return float(raw)
    except ValueError:
        return None


def _parse_deadline(text: str) -> date | None:
    iso = _DEADLINE_ISO.search(text)
    if iso:
        try:
            return date.fromisoformat(iso.group(1))
        except ValueError:
            pass
    es = _DEADLINE_ES.search(text)
    if es:
        d, m, y = int(es.group(1)), int(es.group(2)), int(es.group(3))
        try:
            return date(y, m, d)
        except ValueError:
            return None
    # ISO suelto cerca de "2026-08-06" con contexto de licitación
    loose = re.search(
        r"(?:deadline|plazo|presentaci[oó]n|cierre)[^\n]{0,80}?(\d{4}-\d{2}-\d{2})",
        text,
        re.IGNORECASE,
    )
    if loose:
        try:
            return date.fromisoformat(loose.group(1))
        except ValueError:
            return None
    return None


def _extract_cpvs(text: str) -> list[str]:
    found: list[str] = []
    for match in _CPV_IN_TEXT.finditer(text):
        code = normalize_cpv_code(match.group(1)) or match.group(1)
        if code and code not in found:
            found.append(code)
    return found[:20]


def _cpv_related(profile_codes: list[str], tender_codes: list[str]) -> tuple[bool, bool]:
    """Return (any_overlap_prefix2, any_overlap_prefix4)."""

    if not profile_codes or not tender_codes:
        return False, False
    p2 = {c[:2] for c in profile_codes if len(c) >= 2}
    t2 = {c[:2] for c in tender_codes if len(c) >= 2}
    p4 = {c[:4] for c in profile_codes if len(c) >= 4}
    t4 = {c[:4] for c in tender_codes if len(c) >= 4}
    return bool(p2 & t2), bool(p4 & t4)


def _profile_cpvs(profile: dict[str, Any]) -> list[str]:
    raw = profile.get("cpv") or []
    out: list[str] = []
    if not isinstance(raw, list):
        return out
    for item in raw:
        code = normalize_cpv_code(str(item).strip()) or str(item).strip()
        if code and code not in out:
            out.append(code)
    return out[:20]


def _declared_field_id(
    declared_by_field: dict[str, str], field: str
) -> list[str]:
    eid = declared_by_field.get(field)
    return [eid] if eid else []


def _official_ids_matching(
    official_evidence: list[dict[str, Any]], pattern: re.Pattern[str]
) -> list[str]:
    ids: list[str] = []
    for item in official_evidence:
        extract = str(item.get("extract") or "")
        if pattern.search(extract):
            eid = str(item.get("id") or "").strip()
            if eid and eid not in ids:
                ids.append(eid)
    return ids[:8]


def _all_official_text(official_evidence: list[dict[str, Any]]) -> str:
    parts = [str(item.get("extract") or "") for item in official_evidence]
    return "\n".join(parts)


def _tender_ref(text: str, profile_hint: str | None = None) -> str | None:
    match = re.search(r"CONTR\s*\d{4}\s*\d+", text, re.IGNORECASE)
    if match:
        return re.sub(r"\s+", " ", match.group(0).upper())
    if profile_hint:
        match = re.search(r"CONTR\s*\d{4}\s*\d+", profile_hint, re.IGNORECASE)
        if match:
            return re.sub(r"\s+", " ", match.group(0).upper())
    return None


def _dimension(
    *,
    key: DimensionKey,
    label: str,
    requirement: str,
    official_evidence_ids: list[str],
    capability: str,
    declared_evidence_ids: list[str],
    status: FitStatus,
    status_reason: str,
) -> dict[str, Any]:
    return {
        "key": key,
        "label": label,
        "requirement": requirement,
        "requirement_origin": "official",
        "official_evidence_ids": official_evidence_ids,
        "capability": capability,
        "capability_origin": "declared_by_client",
        "declared_evidence_ids": declared_evidence_ids,
        "status": status,
        "status_reason": status_reason,
    }


def score_cpv_dimension(
    *,
    profile: dict[str, Any],
    declared_by_field: dict[str, str],
    official_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    corpus = _all_official_text(official_evidence)
    tender_cpvs: list[str] = []
    for item in official_evidence:
        tender_cpvs.extend(_extract_cpvs(str(item.get("extract") or "")))
        # provenance / locator a veces trae CPV
        for bag in (item.get("locator"), item.get("provenance")):
            if isinstance(bag, dict):
                for key in ("cpv", "cpv_codes", "main_cpv", "primary_cpv"):
                    val = bag.get(key)
                    if isinstance(val, str):
                        code = normalize_cpv_code(val) or val.strip()
                        if code and code not in tender_cpvs:
                            tender_cpvs.append(code)
                    elif isinstance(val, list):
                        for v in val:
                            code = normalize_cpv_code(str(v)) or str(v).strip()
                            if code and code not in tender_cpvs:
                                tender_cpvs.append(code)
    # dedupe preserve order
    seen: set[str] = set()
    deduped: list[str] = []
    for code in tender_cpvs:
        if code not in seen:
            seen.add(code)
            deduped.append(code)
    tender_cpvs = deduped

    profile_cpvs = _profile_cpvs(profile)
    own_offer = str(profile.get("own_offer") or "")
    declared_ids = _declared_field_id(declared_by_field, "cpv") or _declared_field_id(
        declared_by_field, "own_offer"
    )
    official_ids = _official_ids_matching(official_evidence, _CPV_IN_TEXT)
    if not official_ids:
        official_ids = _official_ids_matching(official_evidence, _AI_SOFTWARE_HINTS)

    if tender_cpvs and profile_cpvs:
        prefix2, prefix4 = _cpv_related(profile_cpvs, tender_cpvs)
        req = (
            f"[oficial] CPV del pliego/licitación: {', '.join(tender_cpvs[:8])}."
        )
        cap = (
            f"[declarado] CPV de interés del perfil: {', '.join(profile_cpvs[:8])}."
        )
        if prefix4 or set(profile_cpvs) & set(tender_cpvs):
            return _dimension(
                key="cpv",
                label="CPV",
                requirement=req,
                official_evidence_ids=official_ids,
                capability=cap,
                declared_evidence_ids=declared_ids,
                status="fit",
                status_reason="Solapamiento de CPV (código o prefijo de 4 dígitos).",
            )
        if prefix2:
            return _dimension(
                key="cpv",
                label="CPV",
                requirement=req,
                official_evidence_ids=official_ids,
                capability=cap,
                declared_evidence_ids=declared_ids,
                status="partial",
                status_reason="Misma división CPV (2 dígitos), sin solape fino.",
            )
        return _dimension(
            key="cpv",
            label="CPV",
            requirement=req,
            official_evidence_ids=official_ids,
            capability=cap,
            declared_evidence_ids=declared_ids,
            status="no_fit",
            status_reason="CPV del perfil y del pliego no se solapan.",
        )

    # Sin CPV oficial numérico: heurística por objeto + familia IT del perfil.
    object_is_it = bool(_AI_SOFTWARE_HINTS.search(corpus))
    profile_is_it = any(c.startswith(_IT_CPV_PREFIXES) for c in profile_cpvs) or bool(
        _AI_SOFTWARE_HINTS.search(own_offer)
    )
    req = (
        "[oficial] El extracto no expone CPV numérico; objeto/descripción de la "
        "licitación se usa como señal de ámbito."
        if not tender_cpvs
        else f"[oficial] CPV: {', '.join(tender_cpvs[:8])}."
    )
    if object_is_it and not tender_cpvs:
        # Citar un fragmento del objeto si existe.
        m = re.search(
            r"(objeto|servicio de|red de agentes|software)[^\n.]{5,160}",
            corpus,
            re.IGNORECASE,
        )
        if m:
            req = f"[oficial] Ámbito del pliego (sin CPV numérico en extracto): «{m.group(0).strip()}»."

    cap = (
        f"[declarado] CPV de interés: {', '.join(profile_cpvs[:8])}."
        if profile_cpvs
        else "[declarado] El perfil no declara CPV de interés."
    )
    if not profile_cpvs and not own_offer:
        return _dimension(
            key="cpv",
            label="CPV",
            requirement=req,
            official_evidence_ids=official_ids,
            capability=cap,
            declared_evidence_ids=declared_ids,
            status="not_evaluable",
            status_reason=_NOT_EVALUABLE + ": el perfil no declara CPV ni oferta.",
        )
    if object_is_it and profile_is_it:
        return _dimension(
            key="cpv",
            label="CPV",
            requirement=req,
            official_evidence_ids=official_ids,
            capability=cap
            + (
                f" Oferta propia: {own_offer[:200]}."
                if own_offer
                else ""
            ),
            declared_evidence_ids=declared_ids
            or _declared_field_id(declared_by_field, "own_offer"),
            status="partial",
            status_reason=(
                "Ámbito TI/IA del pliego alineado con CPV/oferta declarados; "
                "sin CPV numérico oficial para solape exacto."
            ),
        )
    if not object_is_it and not tender_cpvs:
        return _dimension(
            key="cpv",
            label="CPV",
            requirement=req,
            official_evidence_ids=official_ids,
            capability=cap,
            declared_evidence_ids=declared_ids,
            status="not_evaluable",
            status_reason=_NOT_EVALUABLE
            + ": no hay CPV oficial ni señal de ámbito comparable.",
        )
    return _dimension(
        key="cpv",
        label="CPV",
        requirement=req,
        official_evidence_ids=official_ids,
        capability=cap,
        declared_evidence_ids=declared_ids,
        status="no_fit",
        status_reason="Ámbito del pliego y perfil declarado no se alinean.",
    )


def score_solvency_dimension(
    *,
    profile: dict[str, Any],
    declared_by_field: dict[str, str],
    official_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    corpus = _all_official_text(official_evidence)
    has_f2 = bool(_SOLVENCY_ECON.search(corpus))
    has_f3 = bool(_SOLVENCY_TECH.search(corpus))
    amount = _parse_amount(corpus)
    official_ids = _official_ids_matching(
        official_evidence, re.compile(r"F\.?\s*[23]|solvencia", re.IGNORECASE)
    )

    # Datos declarables de solvencia (campos opcionales; Nexus demo no los tiene).
    annual_volume = profile.get("annual_turnover") or profile.get("annual_volume")
    if annual_volume is None:
        annual_volume = profile.get("volumen_anual_negocio")
    past_services = profile.get("past_services") or profile.get("technical_references")
    if past_services is None:
        past_services = profile.get("servicios_ultimos_tres_anos")

    req_parts: list[str] = []
    if has_f2:
        if amount is not None:
            threshold = amount * 1.5
            req_parts.append(
                f"[oficial] F.2 solvencia económica: volumen anual de negocio "
                f"≥ 1,5× valor estimado ({amount:,.2f} EUR → umbral ≈ {threshold:,.2f} EUR)."
            )
        else:
            req_parts.append(
                "[oficial] F.2 solvencia económica: volumen anual de negocio "
                "≥ 1,5× el valor estimado del contrato (o del lote)."
            )
    if has_f3:
        req_parts.append(
            "[oficial] F.3 solvencia técnica: servicios ejecutados en los últimos "
            "tres años avalados por certificados de buena ejecución "
            "(o clasificación en subgrupos correspondientes)."
        )
    if not req_parts:
        req_parts.append(
            "[oficial] No se ha localizado en la evidencia el bloque F.2/F.3 de solvencia."
        )
    requirement = " ".join(req_parts)

    # Capacidad declarada
    cap_parts: list[str] = []
    declared_ids: list[str] = []
    if annual_volume is not None and str(annual_volume).strip():
        cap_parts.append(
            f"[declarado] Volumen anual declarado: {annual_volume}."
        )
        declared_ids.extend(
            _declared_field_id(declared_by_field, "annual_turnover")
            or _declared_field_id(declared_by_field, "annual_volume")
        )
    else:
        cap_parts.append(
            "[declarado] El perfil **no** declara volumen anual de negocio."
        )
    if past_services is not None and str(past_services).strip():
        cap_parts.append(
            f"[declarado] Referencias técnicas declaradas: {str(past_services)[:300]}."
        )
    else:
        cap_parts.append(
            "[declarado] El perfil **no** declara servicios de los últimos tres años "
            "ni certificados de buena ejecución."
        )
    # own_offer / barriers como contexto, no como acreditación
    own = str(profile.get("own_offer") or "").strip()
    if own:
        cap_parts.append(
            f"[declarado] Oferta propia (no es acreditación de solvencia): {own[:220]}."
        )
        declared_ids.extend(_declared_field_id(declared_by_field, "own_offer"))
    barriers = profile.get("barriers") or []
    if isinstance(barriers, list) and any(
        "solvencia" in str(b).casefold() or "homolog" in str(b).casefold() for b in barriers
    ):
        cap_parts.append(
            "[declarado] El perfil reconoce barreras de homologación/solvencia en AAPP."
        )
        declared_ids.extend(_declared_field_id(declared_by_field, "barriers"))
    declared_ids = list(dict.fromkeys(declared_ids))
    capability = " ".join(cap_parts)

    if not has_f2 and not has_f3:
        return _dimension(
            key="solvency",
            label="Solvencia (F.2 / F.3)",
            requirement=requirement,
            official_evidence_ids=official_ids,
            capability=capability,
            declared_evidence_ids=declared_ids,
            status="not_evaluable",
            status_reason=_NOT_EVALUABLE
            + ": no hay requisito de solvencia en la evidencia oficial cargada.",
        )

    can_eval_econ = annual_volume is not None and str(annual_volume).strip() != ""
    can_eval_tech = past_services is not None and str(past_services).strip() != ""

    if has_f2 and not can_eval_econ and has_f3 and not can_eval_tech:
        return _dimension(
            key="solvency",
            label="Solvencia (F.2 / F.3)",
            requirement=requirement,
            official_evidence_ids=official_ids,
            capability=capability,
            declared_evidence_ids=declared_ids,
            status="not_evaluable",
            status_reason=(
                f"{_NOT_EVALUABLE}: F.2 exige volumen ≥1,5× y F.3 servicios de 3 años; "
                "el perfil no aporta ninguno de esos datos."
            ),
        )
    if has_f2 and not can_eval_econ:
        return _dimension(
            key="solvency",
            label="Solvencia (F.2 / F.3)",
            requirement=requirement,
            official_evidence_ids=official_ids,
            capability=capability,
            declared_evidence_ids=declared_ids,
            status="not_evaluable",
            status_reason=(
                f"{_NOT_EVALUABLE}: no hay volumen anual declarado para contrastar F.2."
            ),
        )
    if has_f3 and not can_eval_tech:
        return _dimension(
            key="solvency",
            label="Solvencia (F.2 / F.3)",
            requirement=requirement,
            official_evidence_ids=official_ids,
            capability=capability,
            declared_evidence_ids=declared_ids,
            status="not_evaluable",
            status_reason=(
                f"{_NOT_EVALUABLE}: no hay servicios de 3 años declarados para F.3."
            ),
        )

    # Ambos evaluables: comparación simple
    status: FitStatus = "fit"
    reason = "Los datos declarados cubren los umbrales F.2/F.3 localizados."
    if can_eval_econ and amount is not None:
        try:
            vol = float(str(annual_volume).replace(",", ".").replace(" ", ""))
            if vol < amount * 1.5:
                status = "no_fit"
                reason = (
                    f"Volumen declarado ({vol:,.0f}) < 1,5× valor estimado "
                    f"({amount * 1.5:,.0f})."
                )
        except ValueError:
            status = "not_evaluable"
            reason = f"{_NOT_EVALUABLE}: volumen anual no numérico."
    return _dimension(
        key="solvency",
        label="Solvencia (F.2 / F.3)",
        requirement=requirement,
        official_evidence_ids=official_ids,
        capability=capability,
        declared_evidence_ids=declared_ids,
        status=status,
        status_reason=reason,
    )


def score_lots_dimension(
    *,
    profile: dict[str, Any],
    declared_by_field: dict[str, str],
    official_evidence: list[dict[str, Any]],
) -> dict[str, Any]:
    corpus = _all_official_text(official_evidence)
    lots = [
        (m.group(1), m.group(2).strip().rstrip(").,; ").strip())
        for m in _LOT_LINE.finditer(corpus)
    ]
    # dedupe by number
    seen: set[str] = set()
    unique_lots: list[tuple[str, str]] = []
    for num, title in lots:
        if num not in seen and title:
            seen.add(num)
            unique_lots.append((num, title))

    official_ids = _official_ids_matching(
        official_evidence, re.compile(r"Lote\s*\d+", re.IGNORECASE)
    )
    own = str(profile.get("own_offer") or "").strip()
    declared_ids = _declared_field_id(declared_by_field, "own_offer")

    if not unique_lots:
        # ¿menciona lotes sin detalle?
        if re.search(r"\blotes?\b", corpus, re.IGNORECASE):
            req = "[oficial] La licitación menciona lotes, sin detalle parseable en el extracto."
            status: FitStatus = "not_evaluable"
            reason = (
                _NOT_EVALUABLE
                + " en el lado oficial: no hay listado de lotes con título."
            )
        else:
            req = "[oficial] No se localizan lotes en la evidencia (licitación posiblemente no lotificada)."
            status = "fit"
            reason = "Sin lotes: la presentación es al expediente completo."
        cap = (
            f"[declarado] Oferta propia: {own[:240]}."
            if own
            else "[declarado] Sin oferta propia declarada para orientar lote."
        )
        return _dimension(
            key="lots",
            label="Lotes",
            requirement=req,
            official_evidence_ids=official_ids,
            capability=cap,
            declared_evidence_ids=declared_ids,
            status=status,
            status_reason=reason,
        )

    lot_list = "; ".join(f"Lote {n}: {t}" for n, t in unique_lots)
    req = f"[oficial] Lotes del pliego: {lot_list}."

    # Recomendación por solape léxico oferta ↔ título de lote
    offer_l = own.casefold()
    scored: list[tuple[int, str, str]] = []
    for num, title in unique_lots:
        title_l = title.casefold()
        score = 0
        for token in re.findall(r"[a-záéíóúñ]{4,}", title_l):
            if token in offer_l:
                score += 2
        if "agente" in title_l and ("agente" in offer_l or "ia" in offer_l or "inteligencia" in offer_l):
            score += 3
        if "gobernanza" in title_l and ("gobernanza" in offer_l or "ia" in offer_l):
            score += 2
        if "software" in offer_l or "plataforma" in offer_l:
            score += 1
        scored.append((score, num, title))
    scored.sort(key=lambda x: (-x[0], x[1]))
    best = scored[0] if scored else None

    if not own:
        return _dimension(
            key="lots",
            label="Lotes",
            requirement=req,
            official_evidence_ids=official_ids,
            capability="[declarado] Sin oferta propia: no se puede recomendar lote.",
            declared_evidence_ids=declared_ids,
            status="not_evaluable",
            status_reason=_NOT_EVALUABLE + ": falta own_offer en el perfil.",
        )

    if best and best[0] > 0:
        recommend = f"Lote {best[1]} ({best[2]})"
        others = [f"Lote {n}" for s, n, _t in scored[1:] if s > 0]
        cap = (
            f"[declarado] Oferta propia orienta a {recommend}"
            + (f"; también afinidad con {', '.join(others)}" if others else "")
            + f". Oferta: {own[:200]}."
        )
        return _dimension(
            key="lots",
            label="Lotes",
            requirement=req,
            official_evidence_ids=official_ids,
            capability=cap,
            declared_evidence_ids=declared_ids,
            status="fit" if best[0] >= 3 else "partial",
            status_reason=f"Recomendación de presentación: {recommend} (propuesta, no decisión).",
        )

    cap = (
        f"[declarado] Oferta propia no tiene solape léxico claro con títulos de lote. "
        f"Oferta: {own[:200]}."
    )
    return _dimension(
        key="lots",
        label="Lotes",
        requirement=req,
        official_evidence_ids=official_ids,
        capability=cap,
        declared_evidence_ids=declared_ids,
        status="partial",
        status_reason="Lotes localizados; afinidad oferta↔lote débil — revisar con el equipo.",
    )


def score_deadline_dimension(
    *,
    profile: dict[str, Any],
    declared_by_field: dict[str, str],
    official_evidence: list[dict[str, Any]],
    as_of: date | None = None,
) -> dict[str, Any]:
    today = _as_of(as_of)
    corpus = _all_official_text(official_evidence)
    deadline = _parse_deadline(corpus)
    # También buscar ISO genérico de "Deadline presentación ofertas: 2026-08-06"
    if deadline is None:
        m = re.search(
            r"(?:Deadline|plazo|presentaci[oó]n)[^\n]{0,60}?(\d{4}-\d{2}-\d{2})",
            corpus,
            re.IGNORECASE,
        )
        if m:
            try:
                deadline = date.fromisoformat(m.group(1))
            except ValueError:
                deadline = None
    if deadline is None:
        # última oportunidad: cualquier fecha ISO en corpus con año actual/próximo
        for m in re.finditer(r"\b(20\d{2}-\d{2}-\d{2})\b", corpus):
            try:
                candidate = date.fromisoformat(m.group(1))
            except ValueError:
                continue
            if candidate >= today.replace(year=today.year - 1):
                deadline = candidate
                break

    official_ids = _official_ids_matching(
        official_evidence,
        re.compile(r"deadline|plazo|presentaci[oó]n|cierre|202\d-\d{2}-\d{2}", re.I),
    )
    barriers = [
        str(b).strip()
        for b in (profile.get("barriers") or [])
        if str(b).strip()
    ]
    plazo_barrier = next(
        (
            b
            for b in barriers
            if "plazo" in b.casefold() or "documentaci" in b.casefold()
        ),
        None,
    )
    declared_ids = _declared_field_id(declared_by_field, "barriers")
    if not declared_ids:
        declared_ids = _declared_field_id(declared_by_field, "own_offer")

    if deadline is None:
        return _dimension(
            key="deadline",
            label="Plazo de presentación",
            requirement="[oficial] No se localiza deadline de presentación en la evidencia.",
            official_evidence_ids=official_ids,
            capability=(
                f"[declarado] Barrera de plazos: {plazo_barrier}."
                if plazo_barrier
                else "[declarado] Sin dato de capacidad de reacción en el perfil."
            ),
            declared_evidence_ids=declared_ids,
            status="not_evaluable",
            status_reason=_NOT_EVALUABLE
            + " en lado oficial: sin fecha de cierre parseable.",
        )

    days = (deadline - today).days
    req = (
        f"[oficial] Deadline de presentación de ofertas: {deadline.isoformat()} "
        f"({days} día(s) desde {today.isoformat()})."
    )
    if plazo_barrier:
        cap = (
            f"[declarado] El perfil advierte: «{plazo_barrier}». "
            "No declara capacidad de reacción (equipo, plantilla de oferta, UTE)."
        )
    else:
        cap = (
            "[declarado] El perfil no declara capacidad de reacción "
            "(tiempo de preparación, equipo de oferta, UTE)."
        )

    if days < 0:
        return _dimension(
            key="deadline",
            label="Plazo de presentación",
            requirement=req,
            official_evidence_ids=official_ids,
            capability=cap,
            declared_evidence_ids=declared_ids,
            status="no_fit",
            status_reason=f"Plazo cerrado hace {-days} día(s).",
        )
    if days <= 3:
        return _dimension(
            key="deadline",
            label="Plazo de presentación",
            requirement=req,
            official_evidence_ids=official_ids,
            capability=cap,
            declared_evidence_ids=declared_ids,
            status="partial",
            status_reason=(
                f"Ventana muy corta ({days} día(s)). "
                f"{_NOT_EVALUABLE} la capacidad real de reaccionar a tiempo."
            ),
        )
    if days <= 14:
        return _dimension(
            key="deadline",
            label="Plazo de presentación",
            requirement=req,
            official_evidence_ids=official_ids,
            capability=cap,
            declared_evidence_ids=declared_ids,
            status="partial",
            status_reason=(
                f"Ventana de {days} día(s): ajustada. "
                f"Capacidad de reacción {_NOT_EVALUABLE}."
            ),
        )
    return _dimension(
        key="deadline",
        label="Plazo de presentación",
        requirement=req,
        official_evidence_ids=official_ids,
        capability=cap,
        declared_evidence_ids=declared_ids,
        status="fit",
        status_reason=f"Ventana de {days} día(s) razonable; confirmar recursos de oferta.",
    )


def _build_verdict(dimensions: list[dict[str, Any]]) -> dict[str, Any]:
    by_key = {str(d.get("key")): d for d in dimensions}
    statuses = {str(d.get("key")): str(d.get("status")) for d in dimensions}
    conditions: list[str] = []

    # Hard no-go
    if statuses.get("deadline") == "no_fit":
        return {
            "recommendation": "no_go",
            "conditions": [],
            "human_gate": _HUMAN_GATE,
            "rationale": (
                "Propuesta no-go: el plazo de presentación ya ha cerrado "
                "(según evidencia oficial). Confirmación humana obligatoria."
            ),
        }
    if statuses.get("cpv") == "no_fit":
        return {
            "recommendation": "no_go",
            "conditions": [],
            "human_gate": _HUMAN_GATE,
            "rationale": (
                "Propuesta no-go: CPV/ámbito del pliego no encaja con el perfil "
                "declarado. Confirmación humana obligatoria."
            ),
        }
    if statuses.get("solvency") == "no_fit":
        return {
            "recommendation": "no_go",
            "conditions": [],
            "human_gate": _HUMAN_GATE,
            "rationale": (
                "Propuesta no-go: la solvencia declarada no alcanza el umbral del pliego. "
                "Confirmación humana obligatoria."
            ),
        }

    # Condiciones
    solv = by_key.get("solvency") or {}
    if statuses.get("solvency") == "not_evaluable":
        conditions.append(
            "Solo si puede acreditar F.2: volumen anual de negocio ≥ 1,5× el valor "
            "estimado del contrato (o del lote) en el año de mayor volumen de los tres últimos."
        )
        conditions.append(
            "Solo si puede acreditar F.3: relación de servicios de los últimos tres años "
            "con certificados de buena ejecución (o clasificación en subgrupos)."
        )
    if statuses.get("deadline") in {"partial", "not_evaluable"}:
        conditions.append(
            "Solo si el equipo de oferta puede preparar y presentar documentación "
            "antes del deadline oficial (capacidad de reacción no evaluable solo con el perfil)."
        )
    if statuses.get("cpv") == "partial":
        conditions.append(
            "Confirmar CPV exacto del anuncio oficial y que la oferta se ajusta al objeto del lote."
        )
    if statuses.get("lots") in {"partial", "fit"}:
        lot_reason = str((by_key.get("lots") or {}).get("status_reason") or "")
        if "Recomendación" in lot_reason or "Lote" in lot_reason:
            conditions.append(
                f"Presentarse al lote recomendado en la dimensión Lotes "
                f"({lot_reason}). Valorar UTE si falta solvencia."
            )

    all_fit = all(s == "fit" for s in statuses.values()) if statuses else False
    if all_fit and not conditions:
        return {
            "recommendation": "go",
            "conditions": [],
            "human_gate": _HUMAN_GATE,
            "rationale": (
                "Propuesta go: dimensiones evaluables en fit. "
                "La decisión final la confirma el usuario (puerta humana)."
            ),
        }

    # go_conditioned es el caso demo Nexus: CPV/lotes razonables, solvencia no evaluable
    if not conditions:
        conditions.append(
            "Revisar con el director comercial los huecos no evaluables antes de pujar."
        )
    return {
        "recommendation": "go_conditioned",
        "conditions": conditions,
        "human_gate": _HUMAN_GATE,
        "rationale": (
            "Propuesta go-condicionado: hay encaje de ámbito/lotes, pero faltan "
            "acreditaciones o la ventana es justa. El usuario debe confirmar "
            "las condiciones — nunca es decisión automática."
        ),
    }


def _build_statement(
    *,
    dimensions: list[dict[str, Any]],
    verdict: dict[str, Any],
    tender_ref: str | None,
) -> str:
    ref = tender_ref or "la licitación analizada"
    rec = verdict.get("recommendation")
    rec_label = {
        "go": "GO",
        "no_go": "NO-GO",
        "go_conditioned": "GO CONDICIONADO",
    }.get(str(rec), str(rec))
    lines = [
        f"Encaje perfil declarado ↔ {ref}: propuesta **{rec_label}** "
        f"(puerta humana: {verdict.get('human_gate')})."
    ]
    for dim in dimensions:
        lines.append(
            f"- {dim.get('label')}: {dim.get('status')} — {dim.get('status_reason')}"
        )
    if verdict.get("conditions"):
        lines.append("Condiciones propuestas:")
        for cond in verdict["conditions"][:6]:
            lines.append(f"  · {cond}")
    lines.append(
        "Origen del perfil: declarado por el cliente. Requisitos: evidencia oficial del pliego."
    )
    return "\n".join(lines)[:4000]


def score_profile_tender_fit(
    *,
    profile: dict[str, Any],
    declared_by_field: dict[str, str],
    official_evidence: list[dict[str, Any]],
    as_of: date | datetime | None = None,
    existing_statement: str | None = None,
    existing_confidence: int | None = None,
) -> dict[str, Any] | None:
    """Compute dimensional fit_assessment or None if there is nothing to score.

    Returns a dict ready to place under ``fit_assessment`` (JSON-serializable).
    """

    if not isinstance(profile, dict) or not profile:
        return None
    # Need at least some declared material
    has_declared = bool(declared_by_field) or bool(
        profile.get("own_offer") or profile.get("cpv") or profile.get("barriers")
    )
    if not has_declared:
        return None

    today = _as_of(as_of)
    dims = [
        score_cpv_dimension(
            profile=profile,
            declared_by_field=declared_by_field,
            official_evidence=official_evidence,
        ),
        score_solvency_dimension(
            profile=profile,
            declared_by_field=declared_by_field,
            official_evidence=official_evidence,
        ),
        score_lots_dimension(
            profile=profile,
            declared_by_field=declared_by_field,
            official_evidence=official_evidence,
        ),
        score_deadline_dimension(
            profile=profile,
            declared_by_field=declared_by_field,
            official_evidence=official_evidence,
            as_of=today,
        ),
    ]
    verdict = _build_verdict(dims)
    corpus = _all_official_text(official_evidence)
    tender_ref = _tender_ref(corpus)

    # Collect ids
    declared_ids: list[str] = []
    official_ids: list[str] = []
    for dim in dims:
        for eid in dim.get("declared_evidence_ids") or []:
            if eid not in declared_ids:
                declared_ids.append(str(eid))
        for eid in dim.get("official_evidence_ids") or []:
            if eid not in official_ids:
                official_ids.append(str(eid))
    # Fallback: any declared field id
    if not declared_ids:
        declared_ids = list(declared_by_field.values())[:5]

    if not declared_ids:
        return None

    statement = (existing_statement or "").strip()
    generated = _build_statement(
        dimensions=dims, verdict=verdict, tender_ref=tender_ref
    )
    # Prefer generated dimensional statement when existing is generic mock
    if not statement or "mock" in statement.casefold() or len(statement) < 40:
        statement = generated
    elif "F.2" not in statement and "Lote" not in statement:
        # Append dimensional summary for commercial director value
        statement = (statement.rstrip() + "\n\n" + generated)[:4000]

    # Confidence: lower when many not_evaluable
    n_ne = sum(1 for d in dims if d.get("status") == "not_evaluable")
    n_fit = sum(1 for d in dims if d.get("status") == "fit")
    base = existing_confidence if isinstance(existing_confidence, int) else 55
    confidence = max(25, min(85, base + 5 * n_fit - 8 * n_ne))

    return {
        "statement": statement,
        "declared_evidence_ids": declared_ids,
        "official_evidence_ids": official_ids,
        "confidence": confidence,
        "origin": "declared_by_client",
        "dimensions": dims,
        "verdict": verdict,
        "tender_ref": tender_ref,
        "scoring_engine": "sv2_encaje_v1",
        "scored_as_of": today.isoformat(),
    }


def declared_fields_from_evidence(
    declared_evidence: list[dict[str, Any]],
) -> dict[str, str]:
    """Map profile field → declared evidence id from context pieces."""

    out: dict[str, str] = {}
    for item in declared_evidence:
        if not isinstance(item, dict):
            continue
        locator = item.get("locator") if isinstance(item.get("locator"), dict) else {}
        field = str(locator.get("field") or "").strip()
        eid = str(item.get("id") or "").strip()
        if field and eid:
            out[field] = eid
    return out


def official_evidence_from_context(payload: dict[str, Any]) -> list[dict[str, Any]]:
    """Normalize official evidence list from opportunity context payload."""

    raw = payload.get("evidence") if isinstance(payload, dict) else None
    if not isinstance(raw, list):
        return []
    out: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        eid = str(item.get("id") or "").strip()
        if not eid:
            continue
        try:
            uuid.UUID(eid)
        except (ValueError, TypeError, AttributeError):
            continue
        out.append(item)
    return out


def enrich_opportunity_fit_assessment(
    output: dict[str, Any],
    *,
    context_payload: dict[str, Any],
    as_of: date | datetime | None = None,
) -> dict[str, Any]:
    """Attach dimensional scoring to opportunity output (post-LLM, cost 0).

    Preserves origin boundary: only uses declared_evidence from context and
    official evidence ids already in allowlist.
    """

    result = dict(output)
    dossier = context_payload.get("dossier") if isinstance(context_payload, dict) else {}
    profile = {}
    if isinstance(dossier, dict):
        profile = dossier.get("profile") if isinstance(dossier.get("profile"), dict) else {}
    # Prefer full profile_config keys if present under dossier
    if not profile and isinstance(dossier, dict):
        profile = dossier.get("profile_config") if isinstance(dossier.get("profile_config"), dict) else {}

    declared_list = context_payload.get("declared_evidence") or []
    if not isinstance(declared_list, list):
        declared_list = []
    declared_by_field = declared_fields_from_evidence(declared_list)
    official = official_evidence_from_context(context_payload)

    existing = result.get("fit_assessment")
    existing_statement = None
    existing_confidence = None
    existing_declared: list[str] = []
    existing_official: list[str] = []
    if isinstance(existing, dict):
        existing_statement = existing.get("statement")
        existing_confidence = existing.get("confidence")
        existing_declared = [str(x) for x in (existing.get("declared_evidence_ids") or [])]
        existing_official = [str(x) for x in (existing.get("official_evidence_ids") or [])]

    # Merge profile fields from declared extracts if profile summary is thin
    if not profile.get("own_offer"):
        for item in declared_list:
            if not isinstance(item, dict):
                continue
            field = str((item.get("locator") or {}).get("field") or "")
            extract = str(item.get("extract") or "")
            if field == "own_offer" and "Oferta propia:" in extract:
                profile = {
                    **profile,
                    "own_offer": extract.split("Oferta propia:", 1)[-1].strip(),
                }
            if field == "cpv" and "CPV" in extract:
                codes = re.findall(r"\b\d{8}\b", extract)
                if codes:
                    profile = {**profile, "cpv": codes}
            if field == "barriers" and "Barreras" in extract:
                rest = extract.split("Barreras declaradas:", 1)[-1]
                profile = {
                    **profile,
                    "barriers": [b.strip() for b in rest.split(";") if b.strip()],
                }

    scored = score_profile_tender_fit(
        profile=profile,
        declared_by_field=declared_by_field,
        official_evidence=official,
        as_of=as_of,
        existing_statement=str(existing_statement) if existing_statement else None,
        existing_confidence=int(existing_confidence)
        if isinstance(existing_confidence, int)
        else None,
    )
    if scored is None:
        return result

    # Prefer union of declared ids (existing LLM citations + scorer)
    merged_declared = list(
        dict.fromkeys([*existing_declared, *scored.get("declared_evidence_ids", [])])
    )
    merged_official = list(
        dict.fromkeys([*existing_official, *scored.get("official_evidence_ids", [])])
    )
    # Only keep official ids present in context allowlist
    allow = {
        str(x)
        for x in (context_payload.get("allowed_evidence_ids") or [])
        if isinstance(x, str) and x
    }
    if allow:
        merged_official = [x for x in merged_official if x in allow]
        for dim in scored.get("dimensions") or []:
            dim["official_evidence_ids"] = [
                x for x in (dim.get("official_evidence_ids") or []) if x in allow
            ]

    if not merged_declared:
        return result

    scored["declared_evidence_ids"] = merged_declared
    scored["official_evidence_ids"] = merged_official
    result["fit_assessment"] = scored

    # Surface human-gate note in warnings without being noisy
    warnings = list(result["warnings"]) if isinstance(result.get("warnings"), list) else []
    gate_msg = (
        "Encaje dimensional listo: veredicto con puerta humana "
        f"({scored['verdict']['recommendation']}); no es decisión automática."
    )
    if not any("puerta humana" in str(w).casefold() for w in warnings):
        warnings.append(gate_msg)
    result["warnings"] = warnings
    return result
