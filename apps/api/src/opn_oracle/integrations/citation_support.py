"""G06-CITA-RESPALDO · solapamiento verificable afirmación ↔ fragmento citado.

``validate_citations_allowlist`` solo comprueba que el evidence_id esté permitido.
Este módulo exige que los anclajes materiales de la afirmación (nombres propios,
cifras, fechas, entidades) aparezcan en el span/chunk citado. Si no hay solape:

- afirmaciones de cargo/persona (administrador, apoderado…): se **retiran**
  (inventar un nombre con cita ajena es peor que no citar);
- resto de facts/claims: se **degradan** con aviso visible y sin evidence_ids
  (el lector ve por qué; nada se descarta en silencio).

Determinista, sin red y sin LLM.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal

# Aviso canónico (debe ser legible en API y UI).
CITATION_DOES_NOT_SUPPORT = "cita no respalda la afirmación"

# Cargos / roles de persona natural: inventar un nombre es fallo de producto.
_PERSON_ROLE_MARKERS = (
    "administrador",
    "administradora",
    "admin",
    "apoderado",
    "apoderada",
    "consejero",
    "consejera",
    "director",
    "directora",
    "gerente",
    "ceo",
    "cfo",
    "cto",
    "representante legal",
    "administrador unico",
    "administrador único",
    "administrador solidario",
    "administrador mancomunado",
)

_STOP = frozenset(
    {
        "el",
        "la",
        "los",
        "las",
        "un",
        "una",
        "unos",
        "unas",
        "de",
        "del",
        "al",
        "y",
        "o",
        "u",
        "en",
        "con",
        "por",
        "para",
        "que",
        "se",
        "su",
        "sus",
        "es",
        "son",
        "fue",
        "ser",
        "como",
        "mas",
        "más",
        "no",
        "si",
        "sí",
        "lo",
        "le",
        "les",
        "the",
        "and",
        "of",
        "to",
        "a",
        "an",
        "in",
        "on",
        "for",
        "from",
        "with",
        "this",
        "that",
        "empresa",
        "compañia",
        "compania",
        "company",
        "licitacion",
        "licitación",
        "contrato",
        "expediente",
        "documento",
        "segun",
        "según",
        "evidencia",
        "fuente",
        "cita",
        "afirmacion",
        "afirmación",
        "hecho",
        "dato",
        "valor",
        "importe",
        "cantidad",
        "euros",
        "euro",
        "eur",
        "fecha",
        "plazo",
        "nombre",
        "persona",
        "cargo",
        "rol",
        "role",
    }
)

# Tokens genéricos de rol: no cuentan como anclaje de persona.
_ROLE_TOKENS = frozenset(
    {
        "administrador",
        "administradora",
        "admin",
        "apoderado",
        "apoderada",
        "consejero",
        "consejera",
        "director",
        "directora",
        "gerente",
        "ceo",
        "cfo",
        "cto",
        "representante",
        "legal",
        "unico",
        "único",
        "solidario",
        "mancomunado",
        "titular",
        "responsable",
    }
)

Action = Literal["keep", "degrade", "withdraw"]


@dataclass(frozen=True)
class SupportAnchors:
    """Anclajes materiales extraídos de una afirmación."""

    proper_names: tuple[str, ...] = ()
    numbers: tuple[str, ...] = ()
    dates: tuple[str, ...] = ()
    content_tokens: tuple[str, ...] = ()

    @property
    def critical(self) -> tuple[str, ...]:
        """Anclajes que deben aparecer en la evidencia (nombres, cifras, fechas)."""

        return self.proper_names + self.numbers + self.dates


@dataclass
class SupportIssue:
    path: str
    statement: str
    evidence_ids: list[str]
    missing_anchors: list[str]
    action: Action
    reason: str
    claim_kind: str = "generic"


@dataclass
class SupportEnforcementResult:
    facts: list[dict[str, Any]]
    claims: list[dict[str, Any]]
    warnings: list[str] = field(default_factory=list)
    issues: list[SupportIssue] = field(default_factory=list)
    withdrawn_count: int = 0
    degraded_count: int = 0
    kept_count: int = 0


def _fold(text: str) -> str:
    raw = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(ch for ch in raw if not unicodedata.combining(ch)).casefold()


def _norm_ws(text: str) -> str:
    return " ".join(str(text or "").split())


def is_person_role_claim(statement: str) -> bool:
    folded = _fold(statement)
    return any(marker in folded for marker in _PERSON_ROLE_MARKERS)


def extract_support_anchors(statement: str) -> SupportAnchors:
    """Extrae anclajes materiales de una afirmación (determinista)."""

    text = _norm_ws(statement)
    if not text:
        return SupportAnchors()

    # Cifras: importes, CPV, enteros con separadores.
    numbers: list[str] = []
    for match in re.finditer(
        r"\b\d{1,3}(?:[.\s]\d{3})+(?:,\d+)?\b|\b\d+[.,]\d+\b|\b\d{4,}\b", text
    ):
        digits = re.sub(r"\D", "", match.group(0))
        if digits and digits not in numbers:
            numbers.append(digits)

    # Años sueltos 19xx/20xx (si no capturados ya como número ≥4).
    dates: list[str] = []
    for match in re.finditer(r"\b(?:19|20)\d{2}\b", text):
        year = match.group(0)
        if year not in dates and year not in numbers:
            dates.append(year)
    # Fechas numéricas dd/mm/yyyy o yyyy-mm-dd
    for match in re.finditer(
        r"\b(?:\d{1,2}[/-]\d{1,2}[/-](?:19|20)\d{2}|(?:19|20)\d{2}[-/]\d{1,2}[-/]\d{1,2})\b",
        text,
    ):
        raw = match.group(0)
        if raw not in dates:
            dates.append(raw)

    # Nombres propios: secuencias de 2+ tokens capitalizados (ES/EN).
    proper: list[str] = []
    for match in re.finditer(
        r"\b([A-ZÁÉÍÓÚÜÑ][\wÁÉÍÓÚÜÑáéíóúüñ'-]{1,}"
        r"(?:\s+[A-ZÁÉÍÓÚÜÑ][\wÁÉÍÓÚÜÑáéíóúüñ'-]{1,})+)\b",
        text,
    ):
        name = _norm_ws(match.group(1))
        # Filtrar si todos los tokens son roles genéricos.
        tokens = [t for t in re.split(r"\s+", name) if t]
        if tokens and all(_fold(t) in _ROLE_TOKENS or _fold(t) in _STOP for t in tokens):
            continue
        if name not in proper:
            proper.append(name)

    # Tokens de contenido (≥3, sin stopwords) para solape de respaldo.
    content: list[str] = []
    for match in re.findall(r"[0-9a-záéíóúüñA-ZÁÉÍÓÚÜÑ]{3,}", text):
        folded = _fold(match)
        if folded in _STOP or folded in _ROLE_TOKENS:
            continue
        if folded not in content:
            content.append(folded)

    return SupportAnchors(
        proper_names=tuple(proper),
        numbers=tuple(numbers),
        dates=tuple(dates),
        content_tokens=tuple(content),
    )


def _anchor_in_corpus(anchor: str, corpus_fold: str, corpus_digits: str) -> bool:
    """True si el anclaje aparece en el corpus (texto o dígitos)."""

    a = _norm_ws(anchor)
    if not a:
        return True
    # Cifras: comparar solo dígitos.
    if re.fullmatch(r"\d+", a):
        return a in corpus_digits
    # Nombre multi-palabra: todos los tokens significativos deben aparecer.
    # Tras quitar stopwords (El/La/…), un solo token restante se busca solo.
    tokens = [t for t in re.split(r"\s+", a) if t and _fold(t) not in _STOP]
    if len(tokens) >= 2:
        return all(_fold(t) in corpus_fold for t in tokens)
    if len(tokens) == 1:
        return _fold(tokens[0]) in corpus_fold
    return _fold(a) in corpus_fold


def claim_supported_by_evidence(
    statement: str,
    evidence_texts: Sequence[str],
    *,
    min_content_ratio: float = 0.35,
) -> tuple[bool, list[str]]:
    """Devuelve (soportada, anclajes_faltantes).

    1) Si hay anclajes críticos (nombres/cifras/fechas): todos deben estar en el corpus.
    2) Si no hay críticos: basta solape de tokens de contenido ≥ min_content_ratio.
    3) Corpus vacío → no soportada cuando la afirmación tiene anclajes o tokens.
    """

    anchors = extract_support_anchors(statement)
    corpus = " ".join(_norm_ws(t) for t in evidence_texts if _norm_ws(t))
    corpus_fold = _fold(corpus)
    corpus_digits = re.sub(r"\D", "", corpus)

    if not corpus_fold:
        missing = list(anchors.critical) or list(anchors.content_tokens[:5]) or ["<sin_evidencia>"]
        return False, missing

    if anchors.critical:
        missing = [
            a for a in anchors.critical if not _anchor_in_corpus(a, corpus_fold, corpus_digits)
        ]
        return (not missing), missing

    # Sin anclajes críticos: solape de tokens de contenido.
    if not anchors.content_tokens:
        return True, []
    present = sum(1 for t in anchors.content_tokens if t in corpus_fold)
    ratio = present / len(anchors.content_tokens)
    if ratio >= min_content_ratio:
        return True, []
    missing = [t for t in anchors.content_tokens if t not in corpus_fold][:8]
    return False, missing


def build_evidence_text_index(
    *,
    memory_items: Sequence[Any] | None = None,
    signal_factual: Mapping[str, Any] | None = None,
    oracle_authority: Mapping[str, Any] | None = None,
    citations: Sequence[Any] | None = None,
) -> dict[str, str]:
    """Mapa evidence_id → texto citable (extractos + quotes del modelo)."""

    index: dict[str, list[str]] = {}

    def _add(eid: Any, text: Any) -> None:
        key = str(eid or "").strip()
        bit = _norm_ws(str(text or ""))
        if not key or not bit:
            return
        index.setdefault(key, []).append(bit)

    for raw in memory_items or []:
        if not isinstance(raw, Mapping):
            continue
        _add(raw.get("evidence_id") or raw.get("id"), raw.get("text") or raw.get("extract"))

    for raw in list((signal_factual or {}).get("items") or []):
        if not isinstance(raw, Mapping):
            continue
        _add(raw.get("evidence_id") or raw.get("id"), raw.get("text") or raw.get("extract"))

    for raw in list((oracle_authority or {}).get("oracle_evidence") or []):
        if not isinstance(raw, Mapping):
            continue
        _add(raw.get("id") or raw.get("evidence_id"), raw.get("extract") or raw.get("text"))

    for raw in citations or []:
        if not isinstance(raw, Mapping):
            continue
        _add(raw.get("evidence_id"), raw.get("quote") or raw.get("text"))

    return {eid: "\n".join(parts) for eid, parts in index.items()}


def _item_statement(raw: Mapping[str, Any]) -> str:
    for key in ("statement", "text", "claim"):
        value = raw.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def _item_evidence_ids(raw: Mapping[str, Any]) -> list[str]:
    eids = raw.get("evidence_ids")
    if eids is None and raw.get("evidence_id") is not None:
        eids = [raw.get("evidence_id")]
    if not isinstance(eids, list):
        return []
    return [str(x).strip() for x in eids if str(x or "").strip()]


def _texts_for_ids(eids: Sequence[str], evidence_text_by_id: Mapping[str, str]) -> list[str]:
    return [evidence_text_by_id[e] for e in eids if e in evidence_text_by_id]


def evaluate_material_support(
    item: Mapping[str, Any],
    evidence_text_by_id: Mapping[str, str],
    *,
    path: str,
) -> SupportIssue | None:
    """Evalúa un fact/claim; None si la cita respalda la afirmación."""

    statement = _item_statement(item)
    eids = _item_evidence_ids(item)
    if not statement or not eids:
        # Sin citas: no es el fallo G-06 (cita que no respalda); otros gates lo cubren.
        return None
    texts = _texts_for_ids(eids, evidence_text_by_id)
    ok, missing = claim_supported_by_evidence(statement, texts)
    if ok:
        return None
    person_role = is_person_role_claim(statement)
    # Justificación de acción:
    # - cargo/persona: retirar siempre (inventar un nombre con cita ajena es daño de producto).
    # - resto: también se retira del listado de hechos/claims (no se degrada in-place con
    #   evidence_ids vacíos: tumbaría el allowlist material). El aviso legible y
    #   ``citation_support.issues`` conservan statement + motivo (nada silencioso).
    action: Action = "withdraw"
    missing_s = ", ".join(missing[:6]) if missing else "solape insuficiente"
    if person_role:
        reason = (
            f"{CITATION_DOES_NOT_SUPPORT}: faltan en el fragmento citado [{missing_s}] "
            "(afirmación de cargo/persona retirada)"
        )
    else:
        reason = (
            f"{CITATION_DOES_NOT_SUPPORT}: faltan en el fragmento citado [{missing_s}] "
            "(afirmación retirada; no se publica con cita que no la sostiene)"
        )
    return SupportIssue(
        path=path,
        statement=statement[:500],
        evidence_ids=list(eids),
        missing_anchors=list(missing[:12]),
        action=action,
        reason=reason,
        claim_kind="person_role" if person_role else "generic",
    )


def enforce_citation_support(
    *,
    facts: Sequence[Mapping[str, Any]] | Sequence[Any] | None,
    claims: Sequence[Mapping[str, Any]] | Sequence[Any] | None,
    evidence_text_by_id: Mapping[str, str],
) -> SupportEnforcementResult:
    """Aplica la política keep/withdraw a facts y claims (avisos siempre visibles)."""

    kept_facts: list[dict[str, Any]] = []
    kept_claims: list[dict[str, Any]] = []
    warnings: list[str] = []
    issues: list[SupportIssue] = []
    withdrawn = 0
    degraded = 0
    kept = 0

    def _handle(
        raw: Any,
        *,
        kind: str,
        index: int,
        out: list[dict[str, Any]],
    ) -> None:
        nonlocal withdrawn, degraded, kept
        if not isinstance(raw, Mapping):
            return
        row = dict(raw)
        issue = evaluate_material_support(row, evidence_text_by_id, path=f"$.{kind}[{index}]")
        if issue is None:
            out.append(row)
            kept += 1
            return
        issues.append(issue)
        warnings.append(issue.reason)
        # Retirada con motivo registrado (no descarte silencioso tipo 095/G-05).
        if issue.claim_kind == "person_role":
            withdrawn += 1
        else:
            # Genéricas: misma retirada, contador aparte para el gate/demo.
            degraded += 1

    for i, raw in enumerate(list(facts or [])):
        _handle(raw, kind="facts", index=i, out=kept_facts)
    for i, raw in enumerate(list(claims or [])):
        _handle(raw, kind="claims", index=i, out=kept_claims)

    return SupportEnforcementResult(
        facts=kept_facts,
        claims=kept_claims,
        warnings=warnings,
        issues=issues,
        withdrawn_count=withdrawn,
        degraded_count=degraded,
        kept_count=kept,
    )


def format_support_rejection_summary(result: SupportEnforcementResult) -> str | None:
    """Resumen legible para degraded_reason / warnings de cabecera."""

    if not result.issues:
        return None
    total = result.withdrawn_count + result.degraded_count
    parts = [f"{total} afirmación(es) retirada(s) por cita sin respaldo"]
    if result.withdrawn_count:
        parts.append(f"{result.withdrawn_count} de cargo/persona")
    if result.degraded_count:
        parts.append(f"{result.degraded_count} genérica(s)")
    sample = result.issues[0].reason
    return f"{CITATION_DOES_NOT_SUPPORT}: {'; '.join(parts)}. Ejemplo: {sample}"
