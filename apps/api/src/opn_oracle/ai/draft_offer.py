"""Borrador de oferta guiado por el pliego (SV2-BORRADOR).

Motor **determinista** (coste 0) que, cuando existe ``fit_assessment.verdict``,
produce un esqueleto de oferta estructurado por los **criterios de adjudicación**
del PCAP (ponderaciones y umbrales **derivados de la evidencia del pliego**,
oferta económica / técnica) y hereda gaps del veredicto de encaje (F.2 volumen,
F.3 certificados, plazo).

G12-UMBRAL: no se inventan cifras fijas (p. ej. 65/60). Umbrales y ponderaciones
salen de :mod:`opn_oracle.ai.pliego_criteria` con provenance; si faltan o hay
conflicto, la sección lo declara.

Frontera 095: el borrador es material **declarado/generado** — jamás se mezcla
con ``facts[]`` oficiales. Cada sección etiqueta requisito [oficial] vs
respuesta semilla [borrador declarado].

La puerta humana propia es ``draft_requires_human_edit``: el artefacto no es
documento presentable.
"""

from __future__ import annotations

import re
import uuid
from datetime import UTC, date, datetime
from typing import Any, Literal

from opn_oracle.ai.fit_scoring import (
    _all_official_text,
    _official_ids_matching,
    _select_primary_official_evidence,
    _tender_ref,
    declared_fields_from_evidence,
    official_evidence_from_context,
)
from opn_oracle.ai.pliego_criteria import (
    RESOLUTION_CONFLICT,
    RESOLUTION_MISSING,
    RESOLUTION_VERIFIED,
    format_award_weights_hint,
    format_threshold_hint,
    format_threshold_requirement_clause,
    resolve_pliego_criteria,
)

DraftStatus = Literal["pending", "ready", "blocked"]
GapSeverity = Literal["blocking", "important", "info"]

_DRAFT_ENGINE = "sv2_borrador_v1"
_PROSE_ENGINE = "sv2_prosa_v1"
_HUMAN_GATE = "draft_requires_human_edit"
_BANNER = (
    "BORRADOR COMERCIAL — no es documento presentable. "
    "Requiere edición humana antes de cualquier presentación o envío."
)
_RESPONSE_TAG = "[borrador declarado — no es hecho]"
_OFFICIAL_TAG = "[oficial]"


def normalize_gap_statement(text: str) -> str:
    """Clave de deduplicación de gaps: whitespace colapsado + casefold."""

    return " ".join(str(text or "").casefold().split())


def unique_gap_strings(items: list[Any] | None, *, limit: int = 12) -> list[str]:
    """Devuelve gaps de texto únicos por statement normalizado (orden estable)."""

    seen: set[str] = set()
    out: list[str] = []
    for raw in items or []:
        text = str(raw or "").strip()
        if not text:
            continue
        key = normalize_gap_statement(text)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(text[:500])
        if len(out) >= limit:
            break
    return out


def unique_gap_records(gaps: list[Any] | None, *, limit: int = 16) -> list[dict[str, Any]]:
    """Dedup de gaps estructurados por description normalizada (conserva el primero)."""

    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for gap in gaps or []:
        if not isinstance(gap, dict):
            continue
        desc = str(gap.get("description") or "").strip()
        if not desc:
            continue
        key = normalize_gap_statement(desc)
        if not key or key in seen:
            continue
        seen.add(key)
        out.append(gap)
        if len(out) >= limit:
            break
    return out


# Señales de criterios de adjudicación (PCAP / extracto 132).
_CRITERIA_BLOCK = re.compile(
    r"CRITERIOS?\s+DE\s+ADJUDICACI[OÓ]N|adjudicaci[oó]n\s+se\s+realiza|"
    r"mejor\s+relaci[oó]n\s+calidad.?precio",
    re.IGNORECASE,
)
_CRITERIA_ECON = re.compile(
    r"oferta\s+econ[oó]mica|evaluables?\s+mediante\s+f[oó]rmulas|"
    r"criterios?\s+evaluables?\s+mediante\s+f[oó]rmulas",
    re.IGNORECASE,
)
_CRITERIA_TECH = re.compile(
    r"juicio\s+de\s+valor|oferta\s+t[eé]cnica|"
    r"criterios?\s+evaluables?\s+mediante\s+juicio",
    re.IGNORECASE,
)
# Generic points signal (G12: no fixed 65/60). Used only to locate snippets.
_POINTS_ANY = re.compile(r"\d{1,3}\s*puntos(?:\s+porcentuales)?", re.IGNORECASE)
_THRESHOLD_LANG = re.compile(
    r"(?:superior\s+a|superior\s+en|puntuaci[oó]n\s+m[ií]nima|umbral)",
    re.IGNORECASE,
)
_SOLVENCY_F2 = re.compile(
    r"F\.?\s*2|solvencia\s+econ[oó]mica|volumen\s+anual\s+de\s+negocio",
    re.IGNORECASE,
)
_SOLVENCY_F3 = re.compile(
    r"F\.?\s*3|solvencia\s+t[eé]cnica|certificados?\s+de\s+buena\s+ejecuci[oó]n|"
    r"servicios\s+ejecutados",
    re.IGNORECASE,
)
_LOT_LINE = re.compile(
    r"Lote\s*(\d+)\s*[:.\-\u2013\u2014]\s*([^\n;|/]{3,80}?)(?=\s*/\s*Lote\s*\d|\s*\)\s*$|$|\n)",
    re.IGNORECASE,
)
_DEUC = re.compile(r"\bDEUC\b|Documento\s+Europeo\s+[UÚ]nico", re.IGNORECASE)
_DECLARACION = re.compile(
    r"declaraci[oó]n\s+responsable|prohibiciones?\s+de\s+contratar",
    re.IGNORECASE,
)
_SOBRE = re.compile(r"\bsobre\s*[A-C]\b|sobres?\s+de\s+la\s+oferta", re.IGNORECASE)


def _as_of(value: date | datetime | None) -> date:
    if value is None:
        return datetime.now(UTC).date()
    if isinstance(value, datetime):
        return value.date()
    return value


def _snippet(text: str, pattern: re.Pattern[str], *, window: int = 220) -> str | None:
    match = pattern.search(text)
    if not match:
        return None
    start = max(0, match.start() - 40)
    end = min(len(text), match.end() + window)
    chunk = " ".join(text[start:end].split())
    return chunk[:400]


def _lot_hint_from_fit(fit: dict[str, Any], corpus: str) -> str | None:
    """Prefer Lote 2 when fit dimensions recommend it; else first lot in pliego."""

    for dim in fit.get("dimensions") or []:
        if not isinstance(dim, dict):
            continue
        if dim.get("key") != "lots":
            continue
        bag = f"{dim.get('capability') or ''} {dim.get('status_reason') or ''}"
        m = re.search(
            r"Lote\s*2(?:\s*[:.\-\u2013\u2014]\s*|\s*\(\s*)([^\n;.)]{3,80})",
            bag,
            re.IGNORECASE,
        )
        if m:
            return f"Lote 2: {m.group(1).strip()}"[:120]
        m = re.search(r"Lote\s*2\b[^\n;.]{0,60}", bag, re.IGNORECASE)
        if m:
            return m.group(0).strip().split(";")[0].strip()[:120]
    lots = _LOT_LINE.findall(corpus)
    if not lots:
        return None
    # Prefer lote 2 if present (demo canonica Nexus x Baleares).
    for num, title in lots:
        if str(num) == "2":
            return f"Lote {num}: {title.strip()}"[:120]
    num, title = lots[0]
    return f"Lote {num}: {title.strip()}"[:120]


def _gaps_from_verdict(fit: dict[str, Any]) -> list[dict[str, Any]]:
    """Import conditions from fit verdict 133 (F.2, F.3, plazo) as actionable gaps."""

    verdict = fit.get("verdict") if isinstance(fit.get("verdict"), dict) else {}
    conditions = verdict.get("conditions") if isinstance(verdict, dict) else []
    if not isinstance(conditions, list):
        conditions = []

    gaps: list[dict[str, Any]] = []
    seen: set[str] = set()

    def _add(code: str, description: str, severity: GapSeverity) -> None:
        # SV2-PROSA: un gap por statement normalizado (no por code|desc parcial).
        # Evita duplicar el mismo texto "no evaluable…" con codes f2 y f3.
        key = normalize_gap_statement(description)
        if not key or key in seen:
            return
        seen.add(key)
        gaps.append(
            {
                "code": code,
                "description": description[:800],
                "severity": severity,
                "origin": "verdict_condition",
            }
        )

    for cond in conditions:
        text = str(cond).strip()
        if not text:
            continue
        low = text.casefold()
        if "f.2" in low or "1,5" in low or "1.5" in low or "volumen" in low:
            _add("f2_volume", text, "blocking")
        elif "f.3" in low or "certificado" in low or "tres años" in low or "tres anos" in low:
            _add("f3_certificates", text, "blocking")
        elif (
            "deadline" in low
            or "plazo" in low
            or "presentar" in low
            or "reacción" in low
            or "reaccion" in low
        ):
            _add("deadline_capacity", text, "important")
        elif "cpv" in low:
            _add("cpv_confirm", text, "info")
        elif "lote" in low or "ute" in low:
            _add("lot_ute", text, "important")
        else:
            _add("condition", text, "important")

    # Dimensiones not_evaluable refuerzan gaps aunque el veredicto sea escueto.
    for dim in fit.get("dimensions") or []:
        if not isinstance(dim, dict):
            continue
        if dim.get("status") != "not_evaluable":
            continue
        key = str(dim.get("key") or "other")
        reason = str(dim.get("status_reason") or "").strip()
        if key == "solvency":
            if "F.2" in reason or "volumen" in reason.casefold():
                _add(
                    "f2_volume",
                    reason or "F.2: volumen anual no declarado / no evaluable.",
                    "blocking",
                )
            if (
                "F.3" in reason
                or "certific" in reason.casefold()
                or "servicios" in reason.casefold()
            ):
                _add(
                    "f3_certificates",
                    reason or "F.3: servicios/certificados no declarados / no evaluable.",
                    "blocking",
                )
            if not any(g["code"].startswith("f") for g in gaps):
                _add("solvency", reason or "Solvencia no evaluable con lo declarado.", "blocking")
        elif key == "deadline":
            _add(
                "deadline_capacity",
                reason or "Capacidad de reacción al plazo no evaluable.",
                "important",
            )

    return gaps[:16]


def _seed_response(
    *,
    section_key: str,
    profile: dict[str, Any],
    lot_hint: str | None,
    gaps: list[dict[str, Any]],
) -> str:
    """Párrafo semilla determinista desde el perfil declarado (no LLM, coste 0).

    Etiquetado siempre como borrador; jamás como hecho oficial.
    """

    own = str(profile.get("own_offer") or "").strip()
    cpv = profile.get("cpv") or []
    cpv_txt = ", ".join(str(c) for c in cpv[:6]) if isinstance(cpv, list) else ""
    barriers = profile.get("barriers") or []
    barrier_txt = ""
    if isinstance(barriers, list) and barriers:
        barrier_txt = "; ".join(str(b) for b in barriers[:3])

    lot = lot_hint or "el lote al que se opte"
    gap_codes = {g.get("code") for g in gaps}

    if section_key == "award_economic":
        body = (
            f"Semilla de oferta económica para {lot}. Partir del valor estimado del "
            f"pliego y de la fórmula de puntuación publicada; la cifra final y el "
            f"desglose son responsabilidad del equipo comercial (no generados aquí)."
        )
        if "f2_volume" in gap_codes:
            body += (
                " Gap heredado: sin volumen anual acreditado el precio competitivo "
                "no sustituye la solvencia F.2."
            )
    elif section_key == "award_technical":
        offer_bit = (
            f"Oferta propia declarada: «{own[:280]}»."
            if own
            else "El perfil no aporta descripción de oferta propia; completar."
        )
        cpv_bit = f" CPV de interés declarados: {cpv_txt}." if cpv_txt else ""
        body = (
            f"Semilla de memoria técnica / juicio de valor orientada a {lot}. "
            f"{offer_bit}{cpv_bit} Desarrollar arquitectura, agentes, integración, "
            f"gobernanza y plan de implantación con evidencias propias (este texto "
            f"no es memoria técnica)."
        )
    elif section_key == "award_thresholds":
        body = (
            "Semilla sobre umbrales del PCAP (solo los verificados en pliego_criteria): "
            "la estrategia de puntuación técnica vs económica debe validarse con el "
            "equipo de ofertas. No se asume superación automática de umbrales ni se "
            "inventan cifras fijas."
        )
    elif section_key == "solvency_accreditation":
        body = (
            "Semilla de bloque de solvencia: la oferta propia declarada **no es** "
            "acreditación de F.2/F.3. Adjuntar volumen anual (año de mayor volumen "
            "de los tres últimos) y relación de servicios con certificados, o "
            "clasificación / UTE si procede."
        )
        if barrier_txt:
            body += f" Barreras declaradas a mitigar: {barrier_txt}."
    elif section_key == "lot_object":
        body = (
            f"Semilla de alineación al objeto y a {lot}. "
            + (
                f"Base declarada: «{own[:220]}»."
                if own
                else "Completar con la propuesta de valor del licitador."
            )
            + " Confirmar alcance por lote y exclusiones del PPT."
        )
    else:
        body = f"Semilla genérica de respuesta para la sección «{section_key}». " + (
            f"Oferta declarada: «{own[:200]}»." if own else "Completar con material del perfil."
        )

    return f"{_RESPONSE_TAG} {body} Edición humana obligatoria antes de presentar."[:2000]


def _extract_award_sections(
    *,
    corpus: str,
    official_evidence: list[dict[str, Any]],
    profile: dict[str, Any],
    declared_by_field: dict[str, str],
    lot_hint: str | None,
    gaps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Build draft sections from PCAP award criteria (+ solvencia/lote de apoyo)."""

    sections: list[dict[str, Any]] = []
    criteria_resolution = resolve_pliego_criteria(official_evidence)
    weight_hint = format_award_weights_hint(criteria_resolution)
    threshold_hint = format_threshold_hint(criteria_resolution)
    threshold_clause = format_threshold_requirement_clause(criteria_resolution)

    criteria_ids = _official_ids_matching(
        official_evidence,
        re.compile(
            r"CRITERIOS?\s+DE\s+ADJUDIC|\d{1,3}\s*puntos|\d{1,3}\s*%|"
            r"ponderaci[oó]n|juicio\s+de\s+valor|oferta\s+econ[oó]mica|f[oó]rmulas",
            re.IGNORECASE,
        ),
    )
    if not criteria_ids:
        criteria_ids = [str(item.get("id")) for item in official_evidence if item.get("id")][:4]

    solvency_ids = (
        _official_ids_matching(
            official_evidence, re.compile(r"F\.?\s*[23]|solvencia", re.IGNORECASE)
        )
        or criteria_ids
    )
    lot_ids = (
        _official_ids_matching(official_evidence, re.compile(r"Lote\s*\d+", re.IGNORECASE))
        or criteria_ids
    )

    declared_ids = [
        eid for field in ("own_offer", "cpv", "barriers") if (eid := declared_by_field.get(field))
    ]

    has_criteria = bool(
        _CRITERIA_BLOCK.search(corpus)
        or _CRITERIA_ECON.search(corpus)
        or _CRITERIA_TECH.search(corpus)
        or criteria_resolution.has_criteria_block
        or criteria_resolution.award_weights_status == RESOLUTION_VERIFIED
        or criteria_resolution.min_thresholds_status == RESOLUTION_VERIFIED
        or _POINTS_ANY.search(corpus)
    )

    # --- 1. Oferta económica (fórmulas) ---
    econ_snip = _snippet(corpus, _CRITERIA_ECON) or _snippet(corpus, _POINTS_ANY)
    if has_criteria or econ_snip:
        req = f"{_OFFICIAL_TAG} Criterios evaluables mediante fórmulas (oferta económica). " + (
            f"Extracto: «{econ_snip}»." if econ_snip else "Ver PCAP de adjudicación."
        )
        # Only attach threshold language when verified from pliego (never invent 65/60).
        if criteria_resolution.min_thresholds_status in {
            RESOLUTION_VERIFIED,
            RESOLUTION_CONFLICT,
        }:
            req += threshold_clause
        elif criteria_resolution.min_thresholds_status == RESOLUTION_MISSING and has_criteria:
            req += (
                " Umbral mínimo de puntuación: desconocido/no verificable en el extracto "
                "(no se asume cifra fija)."
            )
        gap_msgs = unique_gap_strings(
            [g["description"] for g in gaps if g.get("code") in {"f2_volume", "deadline_capacity"}],
            limit=6,
        )
        econ_hint_bits = ["criterio económico"]
        if criteria_resolution.award_weights_status == RESOLUTION_VERIFIED:
            econ_hint_bits.append(weight_hint)
        if criteria_resolution.min_thresholds_status == RESOLUTION_VERIFIED:
            econ_hint_bits.append(threshold_hint)
        sections.append(
            {
                "key": "award_economic",
                "title": "Oferta económica (fórmulas)",
                "points_hint": " · ".join(econ_hint_bits),
                "requirement": req[:2000],
                "requirement_origin": "official",
                "official_evidence_ids": criteria_ids[:8],
                "our_response_draft": _seed_response(
                    section_key="award_economic",
                    profile=profile,
                    lot_hint=lot_hint,
                    gaps=gaps,
                ),
                "response_origin": "declared_generated",
                "declared_evidence_ids": declared_ids[:8],
                "gaps": gap_msgs,
            }
        )

    # --- 2. Oferta técnica (juicio de valor) ---
    tech_snip = _snippet(corpus, _CRITERIA_TECH) or _snippet(corpus, _CRITERIA_BLOCK)
    if has_criteria or tech_snip:
        req = (
            f"{_OFFICIAL_TAG} Criterios evaluables mediante juicio de valor (oferta técnica). "
            + (f"Extracto: «{tech_snip}»." if tech_snip else "Ver PCAP de adjudicación.")
        )
        if criteria_resolution.award_weights_status == RESOLUTION_VERIFIED:
            req += f" Ponderación verificada en pliego: {weight_hint}."
        elif criteria_resolution.award_weights_status == RESOLUTION_CONFLICT:
            req += " Ponderación en conflicto entre documentos; no se elige un reparto."
        gap_msgs = unique_gap_strings(
            [
                g["description"]
                for g in gaps
                if g.get("code") in {"f3_certificates", "lot_ute", "cpv_confirm"}
            ],
            limit=6,
        )
        tech_hint = "criterio técnico · juicio de valor"
        if criteria_resolution.award_weights_status == RESOLUTION_VERIFIED:
            tech_hint = f"{tech_hint} · {weight_hint}"
        sections.append(
            {
                "key": "award_technical",
                "title": "Oferta técnica (juicio de valor)",
                "points_hint": tech_hint,
                "requirement": req[:2000],
                "requirement_origin": "official",
                "official_evidence_ids": criteria_ids[:8],
                "our_response_draft": _seed_response(
                    section_key="award_technical",
                    profile=profile,
                    lot_hint=lot_hint,
                    gaps=gaps,
                ),
                "response_origin": "declared_generated",
                "declared_evidence_ids": declared_ids[:8],
                "gaps": gap_msgs,
            }
        )

    # --- 3. Umbrales mínimos (separados de ponderación; G12) ---
    has_threshold_signal = bool(
        criteria_resolution.min_thresholds_status
        in {RESOLUTION_VERIFIED, RESOLUTION_CONFLICT, RESOLUTION_MISSING}
        and (
            criteria_resolution.min_thresholds_status != RESOLUTION_MISSING
            or _THRESHOLD_LANG.search(corpus)
            or has_criteria
        )
    )
    if has_threshold_signal:
        thr_snip = _snippet(corpus, _THRESHOLD_LANG, window=280) or _snippet(
            corpus, _POINTS_ANY, window=280
        )
        if criteria_resolution.min_thresholds_status == RESOLUTION_VERIFIED:
            title = "Umbrales mínimos de puntuación (pliego)"
            req = (
                f"{_OFFICIAL_TAG} Umbrales mínimos del PCAP (distintos de la ponderación). "
                + threshold_clause.lstrip()
                + (f" Extracto: «{thr_snip}»." if thr_snip else "")
            )
            thr_hint = threshold_hint
        elif criteria_resolution.min_thresholds_status == RESOLUTION_CONFLICT:
            title = "Umbrales mínimos de puntuación (conflicto)"
            req = (
                f"{_OFFICIAL_TAG} Umbrales del PCAP en conflicto entre evidencias; "
                "no se afirma un valor único."
                + (f" Extracto: «{thr_snip}»." if thr_snip else "")
            )
            thr_hint = threshold_hint
        else:
            title = "Umbrales mínimos de puntuación (no verificable)"
            req = (
                f"{_OFFICIAL_TAG} Umbral mínimo de puntuación: desconocido/no verificable "
                "en el extracto del pliego. No se inventa ninguna cifra fija de demo."
                + (f" Contexto: «{thr_snip}»." if thr_snip else "")
            )
            thr_hint = "umbral mínimo no verificable en el pliego"
        sections.append(
            {
                "key": "award_thresholds",
                "title": title,
                "points_hint": thr_hint,
                "requirement": req[:2000],
                "requirement_origin": "official",
                "official_evidence_ids": criteria_ids[:8],
                "our_response_draft": _seed_response(
                    section_key="award_thresholds",
                    profile=profile,
                    lot_hint=lot_hint,
                    gaps=gaps,
                ),
                "response_origin": "declared_generated",
                "declared_evidence_ids": declared_ids[:4],
                "gaps": [
                    (
                        "Validar con el equipo si la estrategia de puntos "
                        "tecnicos supera umbrales del PCAP (solo los verificados)."
                    )
                ],
            }
        )

    # --- 4. Solvencia (siempre si hay F.2/F.3 o gaps de solvencia) ---
    has_solv = bool(_SOLVENCY_F2.search(corpus) or _SOLVENCY_F3.search(corpus))
    solv_gaps = [g for g in gaps if str(g.get("code", "")).startswith(("f2", "f3", "solv"))]
    if has_solv or solv_gaps:
        f2 = _snippet(corpus, _SOLVENCY_F2, window=200)
        f3 = _snippet(corpus, _SOLVENCY_F3, window=200)
        parts = [f"{_OFFICIAL_TAG} Solvencia del pliego (habilitación / F.2 / F.3)."]
        if f2:
            parts.append(f"F.2: «{f2}».")
        if f3:
            parts.append(f"F.3: «{f3}».")
        if not f2 and not f3:
            parts.append("Acreditar según PCAP (clasificación o requisitos F.2/F.3).")
        sections.append(
            {
                "key": "solvency_accreditation",
                "title": "Acreditación de solvencia (F.2 / F.3)",
                "points_hint": "habilitación · no es criterio de puntos pero bloquea",
                "requirement": " ".join(parts)[:2000],
                "requirement_origin": "official",
                "official_evidence_ids": solvency_ids[:8],
                "our_response_draft": _seed_response(
                    section_key="solvency_accreditation",
                    profile=profile,
                    lot_hint=lot_hint,
                    gaps=gaps,
                ),
                "response_origin": "declared_generated",
                "declared_evidence_ids": declared_ids[:8],
                "gaps": unique_gap_strings(
                    [g["description"] for g in solv_gaps]
                    or [
                        g["description"]
                        for g in gaps
                        if g.get("code") in {"f2_volume", "f3_certificates"}
                    ],
                    limit=6,
                ),
            }
        )

    # --- 5. Lote / objeto ---
    if lot_hint or _LOT_LINE.search(corpus):
        lot_snip = _snippet(corpus, _LOT_LINE) or lot_hint
        req = (
            f"{_OFFICIAL_TAG} Objeto y lotes del expediente. "
            + (f"Extracto: «{lot_snip}»." if lot_snip else "")
            + (f" Recomendación de encaje: {lot_hint}." if lot_hint else "")
        )
        sections.append(
            {
                "key": "lot_object",
                "title": "Objeto y lote de presentación",
                "points_hint": lot_hint,
                "requirement": req[:2000],
                "requirement_origin": "official",
                "official_evidence_ids": lot_ids[:8],
                "our_response_draft": _seed_response(
                    section_key="lot_object",
                    profile=profile,
                    lot_hint=lot_hint,
                    gaps=gaps,
                ),
                "response_origin": "declared_generated",
                "declared_evidence_ids": declared_ids[:4],
                "gaps": unique_gap_strings(
                    [g["description"] for g in gaps if g.get("code") in {"lot_ute", "cpv_confirm"}],
                    limit=4,
                ),
            }
        )

    # Fallback mínimo si el extracto no trae criterios literales: 3 secciones
    # genéricas ancladas al pliego primario para no devolver esqueleto vacío.
    if len(sections) < 3 and official_evidence:
        generic_ids = (
            criteria_ids
            or [str(item.get("id")) for item in official_evidence if item.get("id")][:4]
        )
        for key, title, hint in (
            (
                "award_economic",
                "Oferta económica (fórmulas)",
                "criterio económico",
            ),
            (
                "award_technical",
                "Oferta técnica (juicio de valor)",
                "criterio técnico",
            ),
            (
                "award_thresholds",
                "Umbrales y ponderación del PCAP",
                "umbrales/ponderación no verificables en el extracto",
            ),
        ):
            if any(s["key"] == key for s in sections):
                continue
            sections.append(
                {
                    "key": key,
                    "title": title,
                    "points_hint": hint,
                    "requirement": (
                        f"{_OFFICIAL_TAG} Completar con el apartado de criterios "
                        "de adjudicación del PCAP (no localizado con detalle en el extracto; "
                        "no inventar ponderaciones ni umbrales)."
                    ),
                    "requirement_origin": "official",
                    "official_evidence_ids": generic_ids[:8],
                    "our_response_draft": _seed_response(
                        section_key=key,
                        profile=profile,
                        lot_hint=lot_hint,
                        gaps=gaps,
                    ),
                    "response_origin": "declared_generated",
                    "declared_evidence_ids": declared_ids[:4],
                    "gaps": unique_gap_strings([g["description"] for g in gaps], limit=4),
                }
            )
            if len(sections) >= 3:
                break

    # SV2-PROSA: re-dedup por si un builder intermedio repite statements.
    for sec in sections:
        sec["gaps"] = unique_gap_strings(sec.get("gaps") or [], limit=12)
    return sections


def _admin_checklist(
    *,
    corpus: str,
    gaps: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Sobres/anexos exigibles: lista accionable con status pending/blocked."""

    gap_codes = {g.get("code") for g in gaps}

    def item(
        key: str,
        label: str,
        description: str,
        *,
        status: DraftStatus = "pending",
        source: str = "pliego",
    ) -> dict[str, Any]:
        return {
            "key": key,
            "label": label,
            "description": description[:500],
            "status": status,
            "source": source,
        }

    items = [
        item(
            "deuc",
            "DEUC / Documento Europeo Único de Contratación",
            "Cumplimentar DEUC (o documento equivalente del pliego) y firmar."
            if not _DEUC.search(corpus)
            else "DEUC citado en el pliego: cumplimentar y adjuntar en el sobre administrativo.",
        ),
        item(
            "declaracion_responsable",
            "Declaración responsable",
            "Declaración de no estar incurso en prohibiciones de contratar y resto de "
            "declaraciones del PCAP."
            if not _DECLARACION.search(corpus)
            else "Declaración responsable exigida por el pliego.",
        ),
        item(
            "solvencia_f2",
            "Acreditación solvencia económica (F.2)",
            (
                "Volumen anual de negocio >= 1,5x valor estimado "
                "(ano de mayor volumen de los tres ultimos)."
            ),
            status="blocked" if "f2_volume" in gap_codes else "pending",
        ),
        item(
            "solvencia_f3",
            "Acreditación solvencia técnica (F.3)",
            "Relación de servicios de los últimos 3 años con certificados de buena ejecución "
            "(o clasificación en subgrupos).",
            status="blocked" if "f3_certificates" in gap_codes else "pending",
        ),
        item(
            "sobre_economico",
            "Sobre / archivo de oferta económica",
            "Oferta económica según fórmulas del PCAP"
            + (" (sobres A/B/C si el pliego los define)." if _SOBRE.search(corpus) else "."),
        ),
        item(
            "sobre_tecnico",
            "Sobre / archivo de oferta técnica",
            "Memoria técnica y documentación de juicio de valor.",
        ),
        item(
            "plazo_presentacion",
            "Presentación antes del deadline",
            "Registro electrónico / plataforma antes del cierre oficial.",
            status="blocked" if "deadline_capacity" in gap_codes else "pending",
        ),
    ]
    return items


def _build_statement(
    *,
    tender_ref: str | None,
    lot_hint: str | None,
    sections: list[dict[str, Any]],
    gaps: list[dict[str, Any]],
    verdict_rec: str | None,
) -> str:
    ref = tender_ref or "la licitación"
    lot = lot_hint or "lote a confirmar"
    lines = [
        f"Borrador de oferta (esqueleto) para {ref} · {lot}.",
        f"Base: veredicto de encaje «{verdict_rec or 'n/d'}» con puerta humana de borrador "
        f"«{_HUMAN_GATE}».",
        f"Secciones desde criterios del PCAP: {len(sections)} "
        f"({', '.join(s['title'] for s in sections[:6])}).",
        f"Gaps heredados del veredicto: {len(gaps)} (F.2/F.3/plazo u otros).",
        _BANNER,
        "Origen: semilla desde perfil declarado + requisitos oficiales del pliego. "
        "No contamina facts oficiales del análisis (frontera 095).",
    ]
    return "\n".join(lines)[:4000]


def build_draft_offer(
    *,
    fit_assessment: dict[str, Any],
    profile: dict[str, Any],
    declared_by_field: dict[str, str],
    official_evidence: list[dict[str, Any]],
    as_of: date | datetime | None = None,
) -> dict[str, Any] | None:
    """Generate draft_offer dict or None if fit verdict is missing.

    Requires ``fit_assessment.verdict`` (puerta humana del 133 heredada).
    """

    verdict = fit_assessment.get("verdict")
    if not isinstance(verdict, dict):
        return None
    rec = str(verdict.get("recommendation") or "").strip()
    if rec not in {"go", "no_go", "go_conditioned"}:
        return None

    today = _as_of(as_of)
    primary = _select_primary_official_evidence(official_evidence)
    corpus = _all_official_text(primary) or _all_official_text(official_evidence)
    tender_ref = (
        fit_assessment.get("tender_ref")
        or _tender_ref(corpus)
        or _tender_ref(_all_official_text(official_evidence))
    )
    tender_ref = tender_ref.strip() or None if isinstance(tender_ref, str) else None

    lot_hint = _lot_hint_from_fit(fit_assessment, corpus)
    gaps = unique_gap_records(_gaps_from_verdict(fit_assessment), limit=16)
    sections = _extract_award_sections(
        corpus=corpus,
        official_evidence=primary or official_evidence,
        profile=profile if isinstance(profile, dict) else {},
        declared_by_field=declared_by_field,
        lot_hint=lot_hint,
        gaps=gaps,
    )
    if not sections:
        return None

    checklist = _admin_checklist(corpus=corpus, gaps=gaps)
    statement = _build_statement(
        tender_ref=tender_ref,
        lot_hint=lot_hint,
        sections=sections,
        gaps=gaps,
        verdict_rec=rec,
    )

    # Collect official ids used in sections (for audit; not facts).
    official_ids: list[str] = []
    declared_ids: list[str] = []
    for sec in sections:
        # Conservar semilla original para pulido / demo antes-después.
        seed = str(sec.get("our_response_draft") or "")
        if seed and not sec.get("our_response_seed"):
            sec["our_response_seed"] = seed
        sec.setdefault("prose_polished", False)
        for eid in sec.get("official_evidence_ids") or []:
            if eid and eid not in official_ids:
                official_ids.append(str(eid))
        for eid in sec.get("declared_evidence_ids") or []:
            if eid and eid not in declared_ids:
                declared_ids.append(str(eid))

    gaps_summary = unique_gap_strings([g["description"] for g in gaps], limit=12)

    return {
        "banner": _BANNER,
        "human_gate": _HUMAN_GATE,
        "statement": statement,
        "tender_ref": tender_ref,
        "lot_hint": lot_hint,
        "sections": sections,
        "administrative_checklist": checklist,
        "gaps_summary": gaps_summary,
        "gaps": gaps,
        "draft_engine": _DRAFT_ENGINE,
        "prose_engine": _PROSE_ENGINE,
        "drafted_as_of": today.isoformat(),
        "origin": "declared_draft",
        "based_on_verdict": rec,
        "official_evidence_ids": official_ids,
        "declared_evidence_ids": declared_ids,
    }


def enrich_opportunity_draft_offer(
    output: dict[str, Any],
    *,
    context_payload: dict[str, Any],
    as_of: date | datetime | None = None,
) -> dict[str, Any]:
    """Attach ``draft_offer`` when ``fit_assessment.verdict`` exists (cost 0)."""

    result = dict(output)
    fit = result.get("fit_assessment")
    if not isinstance(fit, dict) or not isinstance(fit.get("verdict"), dict):
        # Sin veredicto de encaje no hay borrador (puerta humana del 133).
        return result

    dossier = context_payload.get("dossier") if isinstance(context_payload, dict) else {}
    profile: dict[str, Any] = {}
    if isinstance(dossier, dict):
        raw = dossier.get("profile")
        if isinstance(raw, dict):
            profile = raw
        elif isinstance(dossier.get("profile_config"), dict):
            profile = dossier["profile_config"]

    declared_list = context_payload.get("declared_evidence") or []
    if not isinstance(declared_list, list):
        declared_list = []
    declared_by_field = declared_fields_from_evidence(declared_list)

    # Completar perfil fino desde declared extracts (mismo patrón que fit_scoring).
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

    official = official_evidence_from_context(context_payload)
    draft = build_draft_offer(
        fit_assessment=fit,
        profile=profile,
        declared_by_field=declared_by_field,
        official_evidence=official,
        as_of=as_of,
    )
    if draft is None:
        return result

    # Solo IDs oficiales del allowlist del contexto.
    allow = {
        str(x)
        for x in (context_payload.get("allowed_evidence_ids") or [])
        if isinstance(x, str) and x
    }
    if allow:
        draft["official_evidence_ids"] = [
            x for x in (draft.get("official_evidence_ids") or []) if x in allow
        ]
        for sec in draft.get("sections") or []:
            sec["official_evidence_ids"] = [
                x for x in (sec.get("official_evidence_ids") or []) if x in allow
            ]

    result["draft_offer"] = draft

    warnings = list(result["warnings"]) if isinstance(result.get("warnings"), list) else []
    msg = (
        "Borrador de oferta (esqueleto) generado desde criterios del PCAP; "
        f"puerta humana {_HUMAN_GATE}. No es documento presentable."
    )
    if not any("borrador de oferta" in str(w).casefold() for w in warnings):
        warnings.append(msg)
    result["warnings"] = warnings
    return result


def draft_offer_pollutes_official_facts(output: dict[str, Any]) -> bool:
    """True if any fact statement looks like draft_offer content (frontera 095)."""

    draft = output.get("draft_offer")
    if not isinstance(draft, dict):
        return False
    markers = [
        str(draft.get("banner") or ""),
        _RESPONSE_TAG,
        _HUMAN_GATE,
        str(draft.get("draft_engine") or ""),
    ]
    markers = [m for m in markers if m and len(m) > 12]
    for fact in output.get("facts") or []:
        if not isinstance(fact, dict):
            continue
        stmt = str(fact.get("statement") or "")
        for m in markers:
            if m in stmt:
                return True
        # Semillas de sección no deben colarse en facts.
        for sec in draft.get("sections") or []:
            seed = str((sec or {}).get("our_response_draft") or "")
            if seed and len(seed) > 40 and seed[:80] in stmt:
                return True
    return False


def strip_draft_from_official_facts(output: dict[str, Any]) -> dict[str, Any]:
    """Remove facts that clearly contain draft_offer prose (safety net)."""

    result = dict(output)
    draft = result.get("draft_offer")
    if not isinstance(draft, dict):
        return result
    seeds = [
        str(sec.get("our_response_draft") or "")[:80]
        for sec in (draft.get("sections") or [])
        if isinstance(sec, dict) and sec.get("our_response_draft")
    ]
    banner = str(draft.get("banner") or "")
    cleaned: list[dict[str, Any]] = []
    stripped = 0
    for fact in result.get("facts") or []:
        if not isinstance(fact, dict):
            continue
        stmt = str(fact.get("statement") or "")
        if banner and banner[:40] in stmt:
            stripped += 1
            continue
        if _RESPONSE_TAG in stmt or _HUMAN_GATE in stmt:
            stripped += 1
            continue
        if any(s and s in stmt for s in seeds):
            stripped += 1
            continue
        cleaned.append(fact)
    result["facts"] = cleaned
    if stripped:
        warnings = list(result["warnings"]) if isinstance(result.get("warnings"), list) else []
        warnings.append(
            f"Se retiraron {stripped} fact(s) que contenían prosa de borrador de oferta "
            "(frontera 095: el draft no contamina facts oficiales)."
        )
        result["warnings"] = warnings
    return result


def new_draft_section_id() -> str:
    """Helper for tests / demos."""

    return str(uuid.uuid4())
