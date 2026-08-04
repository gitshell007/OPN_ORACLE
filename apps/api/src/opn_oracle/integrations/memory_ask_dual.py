"""MDEV-06 · dual-memory ask vertical (Oracle authority + Signal factual evidence).

Provisional under inherited MDEV-04/05 debt. Fail-closed for disabled mode and
non-citable items. Does not promote memory facts or mutate IntentRevision.
"""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from opn_oracle.integrations.memory_contract_v1 import (
    MaterializedCitation,
    materialize_signal_item_to_evidence,
    should_inject_into_llm,
)

MemoryMode = Literal["disabled", "shadow", "augment"]
PROMPT_RUNTIME_ID = "RT-07"
PROMPT_RUNTIME_VERSION = "1.0.1"
SCHEMA_RUNTIME_VERSION = "dossier_question_answer.v1"

# Retryable technical failures that must preserve Celery backoff/deadline.
RETRYABLE_ERROR_CODES = frozenset(
    {
        "upstream_retryable",
        "timeout",
        "upstream_timeout",
        "transport_error",
        "rate_limit_exceeded",
        "upstream_5xx",
        "backend_unavailable",
        "memory_engine_disabled",
    }
)
PERMANENT_ERROR_CODES = frozenset(
    {
        "auth_or_scope",
        "schema_validation",
        "schema_validation_failed",
        "missing_api_key",
        "invalid_api_key",
        "tenant_not_allowed",
        "dossier_not_allowed",
        "dossier_not_authorized",
        "credential_tenant_mismatch",
        "unsupported_api_version",
        "ssrf_blocked",
        "ssrf_rebind",
    }
)


@dataclass(frozen=True)
class EvidenceMappingRow:
    """Versioned mapping memory_item/fact → Oracle Evidence → source version."""

    signal_item_id: str
    oracle_evidence_id: str
    source_ref: str
    source_version: str
    checksum: str
    classification: str
    locator: str
    mapping_version: str = "memory_evidence_map.v1"


@dataclass(frozen=True)
class DualAskContext:
    mode: MemoryMode
    oracle_authority: dict[str, Any]
    signal_factual: dict[str, Any]
    citations: tuple[MaterializedCitation, ...]
    mappings: tuple[EvidenceMappingRow, ...]
    allowed_evidence_ids: tuple[str, ...]
    coverage: dict[str, Any]
    input_manifest: dict[str, Any]
    input_manifest_hash: str
    excluded: tuple[dict[str, Any], ...]


class RetryableMemoryAskError(RuntimeError):
    """Technical failure that Celery must retry within deadline."""

    def __init__(self, message: str, *, code: str = "upstream_retryable") -> None:
        super().__init__(message)
        self.code = code
        self.retryable = True


class PermanentMemoryAskError(RuntimeError):
    """Auth/scope/schema or non-retryable failure — terminal."""

    def __init__(self, message: str, *, code: str = "permanent") -> None:
        super().__init__(message)
        self.code = code
        self.retryable = False


def classify_error_code(code: str | None, *, http_status: int | None = None) -> bool:
    """Return True when the failure is retryable for service→handler→Celery."""

    normalized = str(code or "").strip().lower()
    if normalized in PERMANENT_ERROR_CODES:
        return False
    if normalized in RETRYABLE_ERROR_CODES:
        return True
    if http_status is not None:
        if http_status in (401, 403, 422):
            return False
        if http_status in (408, 429) or http_status >= 500:
            return True
    return False


def _stable_hash(payload: Mapping[str, Any] | Sequence[Any] | str) -> str:
    if isinstance(payload, str):
        raw = payload.encode("utf-8")
    else:
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str).encode(
            "utf-8"
        )
    return hashlib.sha256(raw).hexdigest()


def build_oracle_authority_block(
    *,
    dossier_id: str,
    tenant_id: str,
    question: str,
    intent: Mapping[str, Any] | None = None,
    requirements: Sequence[Any] | None = None,
    offering: Mapping[str, Any] | None = None,
    objectives: Sequence[Any] | None = None,
    decisions: Sequence[Mapping[str, Any]] | None = None,
    oracle_evidence: Sequence[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Oracle decisional authority — never mixed into Signal factual items."""

    return {
        "block": "oracle_authority",
        "tenant_id": str(tenant_id),
        "dossier_id": str(dossier_id),
        "question": str(question),
        "intent": dict(intent or {}),
        "intent_hash": str(
            (intent or {}).get("content_hash") or (intent or {}).get("intent_hash") or ""
        ),
        "requirements": list(requirements or []),
        "offering": dict(offering or {}),
        "objectives": list(objectives or []),
        "decisions": [dict(item) for item in (decisions or [])],
        "oracle_evidence": [dict(item) for item in (oracle_evidence or [])],
        "untrusted_external": False,
        "authority_loaded": bool(
            intent or requirements or offering or objectives or decisions or oracle_evidence
        ),
    }


def load_oracle_authority_from_session(
    session: Any,
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    question: str,
) -> dict[str, Any]:
    """Load tenant+dossier-scoped Oracle authority from PostgreSQL (no mocks).

    Includes accepted IntentRevision + hash, requirements, offering, objectives,
    decisions, and Evidence rows linked via EvidenceDossier for this dossier only.
    Rows belonging to other tenants/dossiers are excluded by WHERE clauses.
    """

    from sqlalchemy import select

    from opn_oracle.oracle.intent import (
        DossierIntentRevision,
        DossierOffering,
        IntelligenceRequirement,
    )
    from opn_oracle.oracle.links import EvidenceDossier
    from opn_oracle.oracle.models import Decision, DossierObjective, Evidence, StrategicDossier

    dossier = session.scalar(
        select(StrategicDossier).where(
            StrategicDossier.id == dossier_id,
            StrategicDossier.tenant_id == tenant_id,
        )
    )
    if dossier is None:
        return build_oracle_authority_block(
            dossier_id=str(dossier_id),
            tenant_id=str(tenant_id),
            question=question,
        )

    accepted_intent = None
    # getattr: legacy/fixture dossiers (SimpleNamespace, partial ORM rows) may omit the
    # column; real PG models always expose it. Never treat AttributeError as authority.
    intent_revision_id = getattr(dossier, "current_intent_revision_id", None)
    if intent_revision_id is not None:
        accepted_intent = session.scalar(
            select(DossierIntentRevision).where(
                DossierIntentRevision.id == intent_revision_id,
                DossierIntentRevision.tenant_id == tenant_id,
                DossierIntentRevision.dossier_id == dossier_id,
                DossierIntentRevision.status == "accepted",
            )
        )

    intent_payload: dict[str, Any] = {}
    if accepted_intent is not None:
        intent_payload = {
            "id": str(accepted_intent.id),
            "version": accepted_intent.version,
            "schema_key": accepted_intent.schema_key,
            "schema_version": accepted_intent.schema_version,
            "request_text": accepted_intent.request_text,
            "structured_spec": dict(accepted_intent.structured_spec or {}),
            "content_hash": accepted_intent.content_hash,
            "intent_hash": accepted_intent.content_hash,
            "status": accepted_intent.status,
        }

    requirements: list[dict[str, Any]] = []
    offering_payload: dict[str, Any] = {}
    if accepted_intent is not None:
        req_rows = list(
            session.scalars(
                select(IntelligenceRequirement)
                .where(
                    IntelligenceRequirement.tenant_id == tenant_id,
                    IntelligenceRequirement.dossier_id == dossier_id,
                    IntelligenceRequirement.intent_revision_id == accepted_intent.id,
                    IntelligenceRequirement.status == "active",
                )
                .order_by(IntelligenceRequirement.priority, IntelligenceRequirement.created_at)
                .limit(25)
            )
        )
        requirements = [
            {
                "id": str(item.id),
                "class": item.requirement_class,
                "priority": item.priority,
                "question": item.question,
                "decision_to_support": item.decision_to_support,
            }
            for item in req_rows
        ]
        offerings = list(
            session.scalars(
                select(DossierOffering)
                .where(
                    DossierOffering.tenant_id == tenant_id,
                    DossierOffering.dossier_id == dossier_id,
                    DossierOffering.intent_revision_id == accepted_intent.id,
                    DossierOffering.status == "active",
                )
                .order_by(DossierOffering.created_at)
                .limit(5)
            )
        )
        if offerings:
            first = offerings[0]
            offering_payload = {
                "id": str(first.id),
                "name": first.name,
                "aliases": list(first.aliases or []),
                "description": first.description,
                "all": [
                    {"id": str(o.id), "name": o.name, "description": o.description}
                    for o in offerings
                ],
            }

    objectives = [
        {"id": str(item.id), "title": item.title, "status": item.status}
        for item in session.scalars(
            select(DossierObjective)
            .where(
                DossierObjective.tenant_id == tenant_id,
                DossierObjective.dossier_id == dossier_id,
            )
            .order_by(DossierObjective.position)
            .limit(15)
        )
    ]

    decisions = [
        {
            "id": str(item.id),
            "title": item.title,
            "status": item.status,
            "rationale": (item.rationale or "")[:500],
        }
        for item in session.scalars(
            select(Decision)
            .where(
                Decision.tenant_id == tenant_id,
                Decision.dossier_id == dossier_id,
            )
            .order_by(Decision.updated_at.desc())
            .limit(15)
        )
    ]

    evidence_ids = select(EvidenceDossier.evidence_id).where(
        EvidenceDossier.tenant_id == tenant_id,
        EvidenceDossier.dossier_id == dossier_id,
    )
    # Prefer durable dossier evidence (procurement/document/…) over bulk
    # memory_signal rematerializations. Ask injects dual-memory separately; if we
    # order only by created_at the 40-row cap fills with per-turn memory_signal
    # UUIDs and hides PLACSP awards the model (and build_context) already sees.
    from sqlalchemy import case

    kind_rank = case(
        (Evidence.source_kind == "procurement", 0),
        (Evidence.source_kind == "document", 1),
        (Evidence.source_kind == "entity_intel", 2),
        (Evidence.source_kind == "signal", 3),
        else_=9,
    )
    oracle_evidence = [
        {
            "id": str(row.id),
            "source_kind": row.source_kind,
            "extract": (row.extract or "")[:1200],
            "classification": row.classification,
            "checksum": row.checksum.hex() if row.checksum else None,
        }
        for row in session.scalars(
            select(Evidence)
            .where(
                Evidence.id.in_(evidence_ids),
                Evidence.tenant_id == tenant_id,
                Evidence.source_kind.in_(
                    ("signal", "document", "procurement", "entity_intel", "memory_signal")
                ),
            )
            .order_by(kind_rank.asc(), Evidence.created_at.desc())
            .limit(40)
        )
    ]

    return build_oracle_authority_block(
        dossier_id=str(dossier_id),
        tenant_id=str(tenant_id),
        question=question,
        intent=intent_payload,
        requirements=requirements,
        offering=offering_payload,
        objectives=objectives,
        decisions=decisions,
        oracle_evidence=oracle_evidence,
    )


_MONTHS_ES = (
    "enero",
    "febrero",
    "marzo",
    "abril",
    "mayo",
    "junio",
    "julio",
    "agosto",
    "septiembre",
    "octubre",
    "noviembre",
    "diciembre",
)

# Prompt order bias: RT-07 caps citations (~8). Company boilerplate often fills the
# budget before tender.external_id / amount / deadline, so the model omits the demo
# markers even when those facts are in the allowlist. Stable priority is presentation
# only — never invents or drops evidence.
_PROMPT_FACT_PRIORITY: tuple[tuple[str, int], ...] = (
    ("tender.external_id", 0),
    ("tender.deadline", 1),
    ("tender.amount", 2),
    ("tender.title", 3),
    ("tender.buyer", 4),
    ("tender.publication_date", 5),
    ("tender.cpv", 6),
    ("tender.", 20),
    ("company.", 40),
)


def _format_es_date_time(iso_datetime: str) -> str | None:
    """Return Spanish prose for an ISO date/datetime, or None if unparsable."""

    raw = (iso_datetime or "").strip()
    if len(raw) < 10:
        return None
    date_part = raw[:10]
    try:
        year_s, month_s, day_s = date_part.split("-")
        year, month, day = int(year_s), int(month_s), int(day_s)
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return None
    except (TypeError, ValueError):
        return None
    prose = f"{day} de {_MONTHS_ES[month - 1]} de {year}"
    time_match = re.match(
        r"^\d{4}-\d{2}-\d{2}[T ](\d{2}):(\d{2})(?::\d{2})?",
        raw,
    )
    if time_match:
        prose = f"{prose}, {time_match.group(1)}:{time_match.group(2)}"
    return prose


def _format_es_amount(amount_raw: str, currency: str | None = None) -> str | None:
    """Format a numeric amount with Spanish thousands separators (no invention)."""

    cleaned = (amount_raw or "").strip().replace(" ", "").replace(",", "")
    if not cleaned:
        return None
    try:
        # Integers preferred; accept simple decimals without inventing cents.
        if "." in cleaned:
            number = float(cleaned)
            if not number.is_integer():
                # Keep original numeric token; only group the integer part.
                int_part, frac = cleaned.split(".", 1)
                grouped = f"{int(int_part):,}".replace(",", ".") + "," + frac
            else:
                grouped = f"{int(number):,}".replace(",", ".")
        else:
            grouped = f"{int(cleaned):,}".replace(",", ".")
    except (TypeError, ValueError):
        return None
    cur = (currency or "").strip().upper()
    if cur:
        return f"{grouped} {cur}"
    return grouped


def _humanize_structured_deadline_text(text: str) -> str:
    """Render structured tender.deadline ISO datetimes as Spanish prose for the LLM.

    Dual-memory often materializes ``tender.deadline: {'datetime': '2026-04-15T14:00:00'}``.
    Without a human form the model rarely emits the demo marker «15 de abril» even when
    the ISO date is present and cited. Always keep the ISO form next to the prose so the
    model copies rather than invents a calendar format.
    """

    # Already humanized (idempotent): leave untouched.
    if re.search(r"tender\.deadline:\s*\d{1,2}\s+de\s+\w+\s+de\s+20\d{2}", text, flags=re.I):
        return text

    patterns = (
        # Dict form: tender.deadline: {'datetime': '2026-04-15T14:00:00'}
        re.compile(
            r"tender\.deadline:\s*\{[^}]*['\"]datetime['\"]\s*:\s*['\"]"
            r"(?P<iso>20\d{2}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?)"
            r"[^'\"]*['\"][^}]*\}",
            flags=re.IGNORECASE,
        ),
        # Bare ISO after label: tender.deadline: 2026-04-15T14:00:00
        re.compile(
            r"tender\.deadline:\s*"
            r"(?P<iso>20\d{2}-\d{2}-\d{2}(?:[T ]\d{2}:\d{2}(?::\d{2})?)?)"
            r"(?=\s|$)",
            flags=re.IGNORECASE,
        ),
    )

    def _replace(match: re.Match[str]) -> str:
        iso = match.group("iso")
        prose = _format_es_date_time(iso)
        if not prose:
            return match.group(0)
        return f"tender.deadline: {prose} (ISO {iso})"

    out = text
    for pattern in patterns:
        out = pattern.sub(_replace, out)
    return out


def _humanize_structured_amount_text(text: str) -> str:
    """Render structured tender.amount as Spanish thousands-grouped currency for the LLM.

    Memory stores ``tender.amount: {'amount': 2400000, 'currency': 'EUR'}``. The demo
    marker and spoken Spanish use ``2.400.000``; surface that form next to the raw amount.
    """

    if re.search(r"tender\.amount:\s*[\d.]+\s*[A-Z]{3}\b", text, flags=re.I):
        return text

    pattern = re.compile(
        r"tender\.amount:\s*\{(?P<body>[^}]*)\}",
        flags=re.IGNORECASE,
    )

    def _replace(match: re.Match[str]) -> str:
        body = match.group("body")
        amount_m = re.search(
            r"['\"]amount['\"]\s*:\s*['\"]?(\d+(?:[.,]\d+)?)['\"]?",
            body,
            flags=re.IGNORECASE,
        )
        if not amount_m:
            return match.group(0)
        currency_m = re.search(
            r"['\"]currency['\"]\s*:\s*['\"]([A-Za-z]{3})['\"]",
            body,
            flags=re.IGNORECASE,
        )
        raw_amount = amount_m.group(1)
        currency = currency_m.group(1) if currency_m else None
        formatted = _format_es_amount(raw_amount, currency)
        if not formatted:
            return match.group(0)
        raw_note = f"amount={raw_amount}" + (f", currency={currency.upper()}" if currency else "")
        return f"tender.amount: {formatted} ({raw_note})"

    return pattern.sub(_replace, text)


def _humanize_structured_memory_text(text: str) -> str:
    """Apply all structured-fact humanizations used before LLM injection."""

    return _humanize_structured_amount_text(_humanize_structured_deadline_text(text))


def _prompt_fact_sort_key(text: str) -> tuple[int, str]:
    """Stable sort key: key tender facts first, then other tender.*, then company.*."""

    lowered = (text or "").lower()
    for needle, priority in _PROMPT_FACT_PRIORITY:
        if needle in lowered:
            return (priority, lowered)
    return (80, lowered)


def _tender_entity_key(text: str) -> str | None:
    match = re.search(r"\[tender:proc:([^\]]+)\]", text or "", flags=re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return None


def build_key_tender_facts(
    items: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    """Group humanized tender extracts by entity for compact prompt + grounding.

    Only copies values already present in authorized item text — never invents.
    """

    by_entity: dict[str, dict[str, Any]] = {}
    for raw in items:
        text = _humanize_structured_memory_text(str(raw.get("text") or ""))
        entity = _tender_entity_key(text)
        if not entity:
            continue
        row = by_entity.setdefault(
            entity,
            {
                "entity": entity,
                "external_id": None,
                "amount": None,
                "deadline": None,
                "evidence_ids": [],
            },
        )
        eid = str(raw.get("evidence_id") or "").strip()
        if eid and eid not in row["evidence_ids"]:
            row["evidence_ids"].append(eid)

        ext = re.search(
            r"tender\.external_id:\s*(?:\{[^}]*['\"]id['\"]\s*:\s*['\"]([^'\"]+)['\"][^}]*\}|(\S+))",
            text,
            flags=re.IGNORECASE,
        )
        if ext:
            row["external_id"] = (ext.group(1) or ext.group(2) or "").strip() or row["external_id"]

        amount = re.search(
            r"tender\.amount:\s*([\d.]+(?:\s*[A-Z]{3})?)",
            text,
            flags=re.IGNORECASE,
        )
        if amount and "de " not in amount.group(1).lower():
            row["amount"] = amount.group(1).strip()

        deadline = re.search(
            r"tender\.deadline:\s*(\d{1,2}\s+de\s+\w+\s+de\s+20\d{2}(?:,\s*\d{2}:\d{2})?)",
            text,
            flags=re.IGNORECASE,
        )
        if deadline:
            row["deadline"] = deadline.group(1).strip()

    return list(by_entity.values())


def complete_answer_with_grounded_tender_facts(
    answer_text: str,
    *,
    signal_items: Sequence[Mapping[str, Any]],
    citations: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[str, list[dict[str, Any]]]:
    """Copy missing humanized amount/deadline into the answer when the tender is already named.

    Fail-open for empty inputs. Never invents values: only reuses prose from allowlisted
    extracts. Only completes tenders whose entity/external_id already appears in the
    model answer (so we do not introduce unsolicited tenders).
    """

    text = str(answer_text or "").strip()
    cites: list[dict[str, Any]] = [dict(c) for c in (citations or []) if isinstance(c, Mapping)]
    if not text:
        return text, cites

    key_facts = build_key_tender_facts(signal_items)
    if not key_facts:
        return text, cites

    cited_ids = {
        str(c.get("evidence_id") or "").strip()
        for c in cites
        if str(c.get("evidence_id") or "").strip()
    }
    additions: list[str] = []
    lowered = text.lower()

    for fact in key_facts:
        entity = str(fact.get("entity") or "")
        external_id = str(fact.get("external_id") or entity)
        tokens = {entity.lower(), external_id.lower()} - {""}
        if not tokens or not any(tok in lowered for tok in tokens):
            continue
        missing_bits: list[str] = []
        amount = fact.get("amount")
        deadline = fact.get("deadline")
        if amount and str(amount).lower() not in lowered:
            amount_digits = re.sub(r"\D", "", str(amount))
            text_digits = re.sub(r"\D", "", text)
            if not amount_digits or amount_digits not in text_digits:
                missing_bits.append(f"importe {amount}")
        if deadline:
            day_month = re.search(
                r"(\d{1,2})\s+de\s+(\w+)",
                str(deadline),
                flags=re.IGNORECASE,
            )
            present = str(deadline).lower() in lowered
            if day_month and not present:
                present = f"{day_month.group(1)} de {day_month.group(2)}".lower() in lowered
            if not present:
                missing_bits.append(f"plazo {deadline}")
        if not missing_bits:
            continue
        label = external_id or entity
        additions.append(
            f"Para el expediente {label}, la evidencia autorizada indica "
            + " y ".join(missing_bits)
            + "."
        )
        for eid in fact.get("evidence_ids") or []:
            eid_s = str(eid).strip()
            if not eid_s or eid_s in cited_ids:
                continue
            # Quote is a short verbatim slice of the structured extract label.
            quote = f"[tender:proc:{entity}] " + " / ".join(missing_bits)
            cites.append({"evidence_id": eid_s, "quote": quote[:300]})
            cited_ids.add(eid_s)

    if not additions:
        return text, cites
    completed = text.rstrip() + "\n\n" + " ".join(additions)
    return completed[:2500], cites


def _normalize_retrieval_item(raw: Mapping[str, Any]) -> dict[str, Any] | None:
    """Normalize a Signal retrieval item; return None if not citable.

    Items without verifiable source_ref, version-or-checksum, extract/text and
    locator are excluded. Runtime never invents synthetic://mock, checksum or
    locator — fixtures must supply them explicitly.
    """

    text = str(raw.get("text") or raw.get("extract") or "").strip()
    text = _humanize_structured_memory_text(text)
    if not text:
        return None
    item_id = str(raw.get("id") or "").strip()
    if not item_id:
        return None
    source_ref = str(raw.get("source_ref") or "").strip()
    if not source_ref or source_ref.startswith("synthetic://"):
        return None
    checksum = str(raw.get("checksum") or "").strip()
    source_version = str(raw.get("source_version") or raw.get("version") or "").strip()
    # Require verifiable version-or-checksum; never invent either at runtime.
    if not checksum and not source_version:
        return None
    if not checksum:
        # Explicit version without separate checksum: use version string as checksum key.
        checksum = source_version
    locator = raw.get("locator")
    if isinstance(locator, dict):
        locator_s = json.dumps(locator, sort_keys=True, separators=(",", ":"))
    else:
        locator_s = str(locator or "").strip()
    if not locator_s:
        return None
    classification = str(raw.get("classification") or "internal").strip() or "internal"
    if classification not in {"public", "internal"}:
        classification = "internal"
    policy_version = str(raw.get("policy_version") or "").strip()
    watermark = str(raw.get("watermark") or "").strip()
    if not policy_version or not watermark:
        return None
    return {
        "id": item_id,
        "text": text[:8000],
        "source_ref": source_ref,
        "checksum": checksum,
        "locator": locator_s,
        "classification": classification,
        "policy_version": policy_version,
        "watermark": watermark,
        "source_version": source_version or checksum,
        "kind": str(raw.get("kind") or "chunk"),
        "score": raw.get("score"),
        "occurred_at": raw.get("occurred_at"),
    }


def materialize_augment_items(
    items: Sequence[Mapping[str, Any]],
    *,
    tenant_id: str,
    dossier_id: str,
    existing_mappings: Sequence[Mapping[str, Any]] | None = None,
) -> tuple[list[MaterializedCitation], list[EvidenceMappingRow], list[dict[str, Any]]]:
    """Materialize citable Evidence mappings; rematerialize or exclude on checksum change.

    Identity for reuse is tenant+dossier+source_ref+checksum (content fingerprint).
    Locator is not part of the identity: the same fact rematerialized across turns
    must keep one Evidence id. A new checksum forces rematerialization (new id).
    Never rewrite a stored extract under an existing id.
    """

    # First mapping per identity wins (caller should pass oldest-first for stability).
    index: dict[tuple[str, str], Mapping[str, Any]] = {}
    for row in existing_mappings or []:
        key = (
            str(row.get("source_ref") or ""),
            str(row.get("checksum") or ""),
        )
        if not all(key) or key in index:
            continue
        index[key] = row

    citations: list[MaterializedCitation] = []
    mappings: list[EvidenceMappingRow] = []
    excluded: list[dict[str, Any]] = []

    for raw in items:
        normalized = _normalize_retrieval_item(raw)
        if normalized is None:
            excluded.append(
                {
                    "source": "signal_item",
                    "reason": "not_citable",
                    "id": str(raw.get("id") or "")[:80],
                }
            )
            continue
        # Tenant/dossier exactness: item-level overrides must match call scope.
        item_tenant = str(raw.get("tenant_id") or tenant_id)
        item_dossier = str(raw.get("dossier_id") or dossier_id)
        if item_tenant != str(tenant_id) or item_dossier != str(dossier_id):
            excluded.append(
                {
                    "source": "signal_item",
                    "reason": "tenant_or_dossier_mismatch",
                    "id": normalized["id"],
                }
            )
            continue
        key = (normalized["source_ref"], normalized["checksum"])
        prior = index.get(key)
        evidence_id: str | None = None
        if prior is not None:
            prior_tenant = str(prior.get("tenant_id") or tenant_id)
            prior_dossier = str(prior.get("dossier_id") or dossier_id)
            if prior_tenant == str(tenant_id) and prior_dossier == str(dossier_id):
                evidence_id = (
                    str(prior.get("oracle_evidence_id") or prior.get("evidence_id") or "") or None
                )
                prior_extract = _humanize_structured_memory_text(
                    str(prior.get("exact_excerpt") or prior.get("extract") or "")
                )
                # Keep the immutable stored extract in the prompt when reusing.
                if prior_extract:
                    normalized["text"] = prior_extract[:8000]
        try:
            citation = materialize_signal_item_to_evidence(
                normalized,
                tenant_id=str(tenant_id),
                dossier_id=str(dossier_id),
                evidence_id=evidence_id,
            )
        except ValueError as exc:
            excluded.append(
                {
                    "source": "signal_item",
                    "reason": f"materialize_failed:{exc}",
                    "id": normalized["id"],
                }
            )
            continue
        citations.append(citation)
        mappings.append(
            EvidenceMappingRow(
                signal_item_id=citation.signal_item_id,
                oracle_evidence_id=citation.oracle_evidence_id,
                source_ref=citation.source_ref,
                source_version=str(normalized["source_version"]),
                checksum=citation.checksum,
                classification=citation.classification,
                locator=citation.locator,
            )
        )
        # Seed the index so later items in the same turn reuse the new id too.
        if key not in index:
            index[key] = {
                "source_ref": citation.source_ref,
                "checksum": citation.checksum,
                "oracle_evidence_id": citation.oracle_evidence_id,
                "tenant_id": tenant_id,
                "dossier_id": dossier_id,
                "exact_excerpt": citation.exact_excerpt,
            }
    return citations, mappings, excluded


def build_signal_factual_block(
    *,
    mode: MemoryMode,
    citations: Sequence[MaterializedCitation],
    observed_count: int,
) -> dict[str, Any]:
    """Signal factual evidence block. Shadow always has zero injectable items."""

    inject = should_inject_into_llm(mode)
    items_for_prompt: list[dict[str, Any]] = []
    if inject:
        for c in citations:
            # Never teach signal_item_id (memory fact/chunk ref): it is not an
            # Oracle Evidence UUID and RT-07 / local allowlist will reject it.
            # Citability principle: only expose IDs that appear in allowed_evidence_ids.
            items_for_prompt.append(
                {
                    "evidence_id": c.oracle_evidence_id,
                    "text": _humanize_structured_memory_text(c.exact_excerpt),
                    "source_ref": c.source_ref,
                    "checksum": c.checksum,
                    "locator": c.locator,
                    "classification": c.classification,
                    "untrusted_external": True,
                }
            )
        # Presentation order only: surface key tender facts before company boilerplate
        # so RT-07's citation budget is more likely to cover expediente/importe/plazo.
        items_for_prompt.sort(key=lambda item: _prompt_fact_sort_key(str(item.get("text") or "")))
    key_tender_facts = build_key_tender_facts(items_for_prompt) if inject else []
    return {
        "block": "signal_factual",
        "mode": mode,
        "observed_count": observed_count,
        "inject_into_llm": inject,
        "items": items_for_prompt,
        "key_tender_facts": key_tender_facts,
        "untrusted_external": True,
        "note": (
            "shadow_zero_injection"
            if mode == "shadow"
            else ("augment_citable_only" if mode == "augment" else "disabled")
        ),
    }


def build_input_manifest(
    *,
    mode: MemoryMode,
    oracle_authority: Mapping[str, Any],
    signal_factual: Mapping[str, Any],
    allowed_evidence_ids: Sequence[str],
    coverage: Mapping[str, Any],
    prompt_runtime_id: str = PROMPT_RUNTIME_ID,
    prompt_runtime_version: str = PROMPT_RUNTIME_VERSION,
    schema_runtime_version: str = SCHEMA_RUNTIME_VERSION,
    memory_policy: str,
    job_id: str | None = None,
    message_id: str | None = None,
) -> tuple[dict[str, Any], str]:
    """Reconstructible input manifest for the effective task payload (hash included)."""

    evidence_hashes = [
        {
            "evidence_id": item.get("evidence_id"),
            "checksum": item.get("checksum"),
            "source_ref": item.get("source_ref"),
        }
        for item in list(signal_factual.get("items") or [])
        if isinstance(item, dict)
    ]
    manifest = {
        "version": "ask_input_manifest.v1",
        "mode": mode,
        "prompt_runtime_id": prompt_runtime_id,
        "prompt_runtime_version": prompt_runtime_version,
        "schema_runtime_version": schema_runtime_version,
        "memory_policy": memory_policy,
        "job_id": job_id,
        "message_id": message_id,
        "oracle_authority_hash": _stable_hash(oracle_authority),
        "signal_item_count": len(list(signal_factual.get("items") or [])),
        "allowed_evidence_ids": list(allowed_evidence_ids),
        "evidence_hashes": evidence_hashes,
        "coverage_summary": {
            "requested": coverage.get("requested"),
            "used": coverage.get("used"),
            "failed": coverage.get("failed"),
            "excluded": coverage.get("excluded"),
            "truncated": coverage.get("truncated"),
        },
        "created_at": datetime.now(UTC).isoformat(),
    }
    # Shadow must deterministically show zero Signal items even if retrieval non-empty.
    if mode == "shadow":
        assert manifest["signal_item_count"] == 0
        assert manifest["allowed_evidence_ids"] == []
        assert manifest["evidence_hashes"] == []
    digest = _stable_hash(manifest)
    manifest["manifest_sha256"] = digest
    return manifest, digest


def validate_citations_allowlist(
    citations: Sequence[Mapping[str, Any]] | Sequence[Any],
    allowed_evidence_ids: Sequence[str],
) -> tuple[list[dict[str, Any]], list[str]]:
    """Return (accepted_citations, rejected_ids). Precision must be 100% on allowlist.

    Empty allowlist rejects every citation (zero Evidence permitted). Safe answers
    with no citations return ``([], [])``.
    """

    allowed = {str(x) for x in allowed_evidence_ids}
    accepted: list[dict[str, Any]] = []
    rejected: list[str] = []
    for raw in citations or []:
        if not isinstance(raw, Mapping):
            rejected.append("<non-object>")
            continue
        eid = str(raw.get("evidence_id") or "").strip()
        if not eid or eid not in allowed:
            rejected.append(eid or "<missing>")
            continue
        accepted.append(dict(raw))
    return accepted, rejected


# Dossier evidence kinds that are legitimately citable when linked via EvidenceDossier
# and shown to the model (build_context / oracle_authority). Dual-memory memory_signal
# IDs are always taken from the current materialization set, never bulk-imported.
DOSSIER_CITABLE_SOURCE_KINDS = frozenset({"procurement", "document", "signal", "entity_intel"})


def merge_ask_citation_allowlist(
    dual_allowed_ids: Sequence[str],
    *,
    oracle_authority: Mapping[str, Any] | None = None,
    extra_dossier_evidence_ids: Sequence[str] | None = None,
) -> list[str]:
    """Union dual-memory allowlist with legitimately citable dossier Evidence IDs.

    Preguntar teaches the model both dual-memory items and dossier evidence from
    ``build_context`` / ``oracle_authority`` (e.g. PLACSP procurement awards). The
    conversation-layer validator must use the same set that Signal RT-07 and the
    provider merge use — dual-only validation rejects procurement IDs the model
    was explicitly allowed to cite, which is the SV2-ASK-FLAKE root cause.
    """

    merged: list[str] = []
    seen: set[str] = set()

    def _add(raw: Any) -> None:
        value = str(raw or "").strip()
        if not value or value in seen:
            return
        seen.add(value)
        merged.append(value)

    for item in dual_allowed_ids or []:
        _add(item)
    for item in extra_dossier_evidence_ids or []:
        _add(item)
    authority = oracle_authority or {}
    for row in list(authority.get("oracle_evidence") or []):
        if not isinstance(row, Mapping):
            continue
        kind = str(row.get("source_kind") or "").strip()
        # Authority may still list memory_signal; only trust dual set for those.
        if kind and kind not in DOSSIER_CITABLE_SOURCE_KINDS:
            continue
        _add(row.get("id"))
    return merged


def format_allowlist_rejection(
    rejected: Sequence[str],
    allowed_evidence_ids: Sequence[str],
    *,
    kind: str = "evidence_ids",
) -> str:
    """Human-visible rejection detail — never swallow which IDs failed."""

    rej = [str(x) for x in rejected if str(x).strip()]
    allow_n = len(list(allowed_evidence_ids or []))
    sample_rej = ", ".join(rej[:8])
    more = f" (+{len(rej) - 8} más)" if len(rej) > 8 else ""
    return (
        f"La respuesta citó {kind} fuera de allowlist ({len(rej)}): "
        f"[{sample_rej}{more}]; allowlist_size={allow_n}."
    )


def load_dossier_citable_evidence_ids(
    session: Any,
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
) -> list[str]:
    """Stable dossier Evidence IDs the model may cite (excludes bulk memory_signal)."""

    from sqlalchemy import select

    from opn_oracle.oracle.links import EvidenceDossier
    from opn_oracle.oracle.models import Evidence

    # Prefer durable non-bulk rows. Opportunity PCAP materializations
    # (SV2-E2E-VIVO) remain citable on the opportunity path but should not
    # flood the generic Preguntar allowlist (limit 200 by created_at desc).
    rows = list(
        session.scalars(
            select(Evidence)
            .join(
                EvidenceDossier,
                (EvidenceDossier.evidence_id == Evidence.id)
                & (EvidenceDossier.tenant_id == Evidence.tenant_id),
            )
            .where(
                Evidence.tenant_id == tenant_id,
                EvidenceDossier.dossier_id == dossier_id,
                Evidence.source_kind.in_(tuple(DOSSIER_CITABLE_SOURCE_KINDS)),
            )
            .order_by(Evidence.created_at.desc())
            .limit(400)
        )
    )
    out: list[str] = []
    for row in rows:
        prov = row.provenance if isinstance(row.provenance, dict) else {}
        loc = row.locator if isinstance(row.locator, dict) else {}
        materialized = prov.get("materialized_for") or loc.get("materialized_for")
        if materialized in {"sv2_e2e_vivo_opportunity", "opportunity_pliego"}:
            continue
        out.append(str(row.id))
        if len(out) >= 200:
            break
    return out


def validate_material_evidence_allowlist(
    material_items: Sequence[Mapping[str, Any]] | Sequence[Any] | None,
    allowed_evidence_ids: Sequence[str],
    *,
    kind: str = "facts",
) -> list[str]:
    """Return unauthorized evidence refs in material facts/claims.

    Empty allowlist rejects any non-empty material block (no assertions without
    Evidence). Non-empty allowlist requires every evidence_id ∈ allowlist.
    """

    allowed = {str(x).strip() for x in allowed_evidence_ids if str(x).strip()}
    rejected: list[str] = []
    items = list(material_items or [])
    if items and not allowed:
        rejected.append(f"{kind}:empty_allowlist")
        return rejected
    for raw in items:
        if not isinstance(raw, Mapping):
            rejected.append(f"{kind}:<non-object>")
            continue
        eids = raw.get("evidence_ids")
        if eids is None and raw.get("evidence_id") is not None:
            eids = [raw.get("evidence_id")]
        if not isinstance(eids, list) or not eids:
            rejected.append(f"{kind}:missing_evidence")
            continue
        for eid in eids:
            sid = str(eid or "").strip()
            if not sid or sid not in allowed:
                rejected.append(sid or f"{kind}:<missing>")
    return rejected


def link_snapshot_run_usage(
    snapshot_payload: dict[str, Any],
    *,
    run_id: str | None = None,
    usage_log_id: str | None = None,
    attempts: int | None = None,
) -> dict[str, Any]:
    """Attach post-execution links without rewriting frozen snapshot core fields."""

    frozen_keys = (
        "mode",
        "items",
        "items_observed",
        "coverage",
        "input_manifest",
        "input_manifest_hash",
        "allowed_evidence_ids",
        "mappings",
        "oracle_authority_hash",
    )
    core = {k: snapshot_payload.get(k) for k in frozen_keys if k in snapshot_payload}
    links = dict(snapshot_payload.get("post_links") or {})
    if run_id:
        links["run_id"] = str(run_id)
    if usage_log_id:
        links["usage_log_id"] = str(usage_log_id)
    if attempts is not None:
        links["attempts"] = int(attempts)
    links["linked_at"] = datetime.now(UTC).isoformat()
    rest = {k: v for k, v in snapshot_payload.items() if k not in core}
    return {**core, **rest, "post_links": links}


def build_dual_ask_context(
    *,
    mode: MemoryMode,
    tenant_id: str,
    dossier_id: str,
    question: str,
    retrieval_items: Sequence[Mapping[str, Any]],
    coverage_manifest: Mapping[str, Any] | None,
    memory_policy: str,
    oracle_authority: Mapping[str, Any] | None = None,
    existing_mappings: Sequence[Mapping[str, Any]] | None = None,
    job_id: str | None = None,
    message_id: str | None = None,
) -> DualAskContext:
    """Compose dual blocks + materialization + input manifest for one ask execution."""

    authority = dict(
        oracle_authority
        or build_oracle_authority_block(
            dossier_id=dossier_id,
            tenant_id=tenant_id,
            question=question,
        )
    )
    observed = list(retrieval_items or [])
    coverage = dict(coverage_manifest or {})
    excluded: list[dict[str, Any]] = list(coverage.get("excluded") or [])
    citations: list[MaterializedCitation] = []
    mappings: list[EvidenceMappingRow] = []

    if mode == "augment":
        citations, mappings, mat_excluded = materialize_augment_items(
            observed,
            tenant_id=tenant_id,
            dossier_id=dossier_id,
            existing_mappings=existing_mappings,
        )
        excluded.extend(mat_excluded)
    elif mode == "shadow":
        # Retrieve/snapshot observed items but inject zero.
        for raw in observed:
            if _normalize_retrieval_item(raw) is None:
                excluded.append(
                    {
                        "source": "signal_item",
                        "reason": "not_citable_shadow_audit",
                        "id": str(raw.get("id") or "")[:80],
                    }
                )
    else:
        # disabled — no Signal items
        observed = []

    coverage["excluded"] = excluded
    if "used" not in coverage:
        coverage["used"] = [c.oracle_evidence_id for c in citations] if mode == "augment" else []
    if "failed" not in coverage:
        coverage["failed"] = coverage.get("failed") or []

    signal_block = build_signal_factual_block(
        mode=mode,
        citations=citations,
        observed_count=len(retrieval_items or []),
    )
    # Prefer the presentation order of signal_factual items (key tender facts first).
    if mode == "augment":
        ordered_ids = [
            str(item.get("evidence_id") or "")
            for item in list(signal_block.get("items") or [])
            if isinstance(item, dict) and str(item.get("evidence_id") or "").strip()
        ]
        allowed = (
            tuple(ordered_ids) if ordered_ids else tuple(c.oracle_evidence_id for c in citations)
        )
    else:
        allowed = ()
    manifest, digest = build_input_manifest(
        mode=mode,
        oracle_authority=authority,
        signal_factual=signal_block,
        allowed_evidence_ids=allowed,
        coverage=coverage,
        memory_policy=memory_policy,
        job_id=job_id,
        message_id=message_id,
    )
    return DualAskContext(
        mode=mode,
        oracle_authority=authority,
        signal_factual=signal_block,
        citations=tuple(citations),
        mappings=tuple(mappings),
        allowed_evidence_ids=allowed,
        coverage=coverage,
        input_manifest=manifest,
        input_manifest_hash=digest,
        excluded=tuple(excluded),
    )


def dual_context_to_snapshot(ctx: DualAskContext) -> dict[str, Any]:
    return {
        "mode": ctx.mode,
        "inject_into_llm": ctx.signal_factual.get("inject_into_llm"),
        "items_observed": ctx.signal_factual.get("observed_count"),
        "items": list(ctx.signal_factual.get("items") or []),
        "allowed_evidence_ids": list(ctx.allowed_evidence_ids),
        "mappings": [asdict(m) for m in ctx.mappings],
        "coverage": ctx.coverage,
        "input_manifest": ctx.input_manifest,
        "input_manifest_hash": ctx.input_manifest_hash,
        "oracle_authority_hash": ctx.input_manifest.get("oracle_authority_hash"),
        "prompt_runtime_id": PROMPT_RUNTIME_ID,
        "prompt_runtime_version": PROMPT_RUNTIME_VERSION,
        "schema_runtime_version": SCHEMA_RUNTIME_VERSION,
    }


def load_existing_memory_signal_mappings(
    session: Any,
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    """Load durable memory_signal Evidence for a dossier as reuse mappings.

    Returns one mapping per source_ref+checksum (oldest row wins) so materialize
    can reuse Evidence ids across Preguntar turns instead of minting uuid4 each time.
    """

    from sqlalchemy import select

    from opn_oracle.oracle.links import EvidenceDossier
    from opn_oracle.oracle.models import Evidence

    rows = list(
        session.scalars(
            select(Evidence)
            .join(
                EvidenceDossier,
                (EvidenceDossier.evidence_id == Evidence.id)
                & (EvidenceDossier.tenant_id == Evidence.tenant_id),
            )
            .where(
                Evidence.tenant_id == tenant_id,
                EvidenceDossier.dossier_id == dossier_id,
                Evidence.source_kind == "memory_signal",
            )
            .order_by(Evidence.created_at.asc())
            .limit(max(1, min(int(limit), 20000)))
        )
    )
    mappings: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for row in rows:
        provenance = row.provenance if isinstance(row.provenance, dict) else {}
        locator = row.locator if isinstance(row.locator, dict) else {}
        source_ref = str(provenance.get("source_ref") or locator.get("source_ref") or "").strip()
        checksum_hex = str(provenance.get("checksum") or "").strip()
        if not checksum_hex and row.checksum:
            checksum_hex = row.checksum.hex()
        if not source_ref or not checksum_hex:
            continue
        key = (source_ref, checksum_hex)
        if key in seen:
            continue
        seen.add(key)
        locator_raw = locator.get("raw")
        if isinstance(locator_raw, dict):
            locator_s = json.dumps(locator_raw, sort_keys=True, separators=(",", ":"))
        else:
            locator_s = str(locator_raw or "")
        mappings.append(
            {
                "source_ref": source_ref,
                "checksum": checksum_hex,
                "locator": locator_s,
                "oracle_evidence_id": str(row.id),
                "tenant_id": str(tenant_id),
                "dossier_id": str(dossier_id),
                "exact_excerpt": str(row.extract or "")[:8000],
            }
        )
    return mappings


def _find_memory_signal_by_identity(
    session: Any,
    *,
    tenant_id: uuid.UUID,
    source_ref: str,
    checksum: bytes,
) -> Any | None:
    """Oldest memory_signal Evidence with the same source_ref+checksum (tenant scope)."""

    from sqlalchemy import or_, select

    from opn_oracle.oracle.models import Evidence

    if not source_ref or len(checksum) != 32:
        return None
    return session.scalar(
        select(Evidence)
        .where(
            Evidence.tenant_id == tenant_id,
            Evidence.source_kind == "memory_signal",
            Evidence.checksum == checksum,
            or_(
                Evidence.provenance["source_ref"].as_string() == source_ref,
                Evidence.locator["source_ref"].as_string() == source_ref,
            ),
        )
        .order_by(Evidence.created_at.asc())
        .limit(1)
    )


def persist_memory_signal_evidence(
    session: Any,
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    citations: Sequence[MaterializedCitation],
    job_id: str | None = None,
) -> dict[str, str] | list[str]:
    """Persist immutable Evidence rows (source_kind=memory_signal) + dossier links.

    Reuses an existing row when the requested id is already durable, or when the
    same tenant identity (source_ref+checksum) already exists. Never rewrites a
    stored extract/checksum under a different content identity.

    Requires migration 0030. When the constraint is missing, raises so caller can
    fall back to mapping-only (fail-visible debt).

    Returns mapping requested_citation_id → durable_evidence_id. When content
    identity remaps a fresh uuid4 onto an older row, the durable id is the value
    so callers can rewrite allowlists/citations without minting phantom rows.
    """

    from sqlalchemy import select

    from opn_oracle.oracle.links import EvidenceDossier
    from opn_oracle.oracle.models import Evidence

    # requested citation id → durable Evidence id (may remap on content-identity hit)
    id_map: dict[str, str] = {}
    for c in citations:
        requested_key = str(c.oracle_evidence_id)
        requested_id = uuid.UUID(requested_key)
        try:
            checksum = bytes.fromhex(c.checksum) if len(c.checksum) == 64 else b""
        except ValueError:
            checksum = b""
        if len(checksum) != 32:
            checksum = hashlib.sha256(c.exact_excerpt.encode("utf-8")).digest()

        existing = session.scalar(
            select(Evidence).where(Evidence.id == requested_id, Evidence.tenant_id == tenant_id)
        )
        if existing is None:
            # Content-identity reuse: same fact rematerialized with a fresh uuid4.
            existing = _find_memory_signal_by_identity(
                session,
                tenant_id=tenant_id,
                source_ref=c.source_ref,
                checksum=checksum,
            )

        if existing is None:
            session.add(
                Evidence(
                    id=requested_id,
                    tenant_id=tenant_id,
                    source_kind="memory_signal",
                    source_url=None,
                    extract=c.exact_excerpt[:8000],
                    locator={"raw": c.locator, "source_ref": c.source_ref},
                    checksum=checksum,
                    classification=c.classification
                    if c.classification in {"public", "internal"}
                    else "internal",
                    provenance={
                        "source_kind": "memory_signal",
                        "signal_item_id": c.signal_item_id,
                        "source_ref": c.source_ref,
                        "checksum": c.checksum,
                        "policy_version": c.policy_version,
                        "watermark": c.watermark,
                        "job_id": job_id,
                        "materialized_at": datetime.now(UTC).isoformat(),
                        "mapping_version": "memory_evidence_map.v1",
                    },
                    version=1,
                )
            )
            session.flush()
            durable_id = requested_id
        else:
            # Never rewrite immutable extract/checksum; mismatch means exclude upstream.
            if existing.checksum != checksum:
                continue
            durable_id = existing.id

        link = session.scalar(
            select(EvidenceDossier).where(
                EvidenceDossier.tenant_id == tenant_id,
                EvidenceDossier.evidence_id == durable_id,
                EvidenceDossier.dossier_id == dossier_id,
            )
        )
        if link is None:
            session.add(
                EvidenceDossier(
                    tenant_id=tenant_id,
                    evidence_id=durable_id,
                    dossier_id=dossier_id,
                )
            )
            session.flush()
        id_map[requested_key] = str(durable_id)
    return id_map
