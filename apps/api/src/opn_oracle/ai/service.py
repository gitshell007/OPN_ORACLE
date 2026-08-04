"""Audited, tenant-safe execution boundary for Oracle AI agents."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from flask import current_app
from sqlalchemy import delete, func, select, text

from opn_oracle.ai.context import (
    BuiltContext,
    build_context,
    validate_evidence,
    validate_opportunity_origin_boundary,
)
from opn_oracle.ai.models import (
    AIArtifact,
    AIAttempt,
    AIContextEvidence,
    AIContextSnapshot,
    AITenantPolicy,
    AIUsageLedger,
)
from opn_oracle.ai.provider import LLMRequest, provider_from_config
from opn_oracle.ai.registry import PromptRegistry
from opn_oracle.ai.schemas import (
    AgentOutput,
    ClaimIssue,
    EvidenceReviewerOutput,
    SignalTriageOutput,
)
from opn_oracle.ai.tender_search_wizard import postvalidate_tender_search_plan
from opn_oracle.extensions import db
from opn_oracle.oracle.jobs import AIAuditLog, BackgroundJob
from opn_oracle.oracle.links import EvidenceDossier
from opn_oracle.oracle.models import DossierSignal, Evidence, Signal
from opn_oracle.oracle.scoring import score_signal
from opn_oracle.platform.audit import append_audit_event
from opn_oracle.tenants.context import require_tenant_id


class AIPolicyDenied(RuntimeError):
    pass


class SignalTriageRejected(RuntimeError):
    """The model output is valid JSON but cannot safely alter the live signal link."""

    pass


class EvidenceReviewError(RuntimeError):
    """The candidate output was generated, but the mandatory evidence review failed."""


class WizardOutputValidationError(RuntimeError):
    """The completion wizard output contradicts the deterministic dossier snapshot."""


def recover_stale_ai_executions(*, now: datetime | None = None) -> int:
    """Release expired reservations; fenced workers can no longer settle them."""
    tenant_id = require_tenant_id()
    current = now or datetime.now(UTC)
    attempts = list(
        db.session.scalars(
            select(AIAttempt)
            .where(
                AIAttempt.tenant_id == tenant_id,
                AIAttempt.status.in_(("reserved", "running")),
                AIAttempt.lease_expires_at < current,
            )
            .with_for_update(skip_locked=True)
        )
    )
    for attempt in attempts:
        revoked_token = uuid.uuid4()
        attempt.status = "abandoned"
        attempt.error_code = "stale_execution"
        attempt.completed_at = current
        attempt.execution_token = revoked_token
        audit = db.session.scalar(
            select(AIAuditLog)
            .where(AIAuditLog.id == attempt.audit_log_id, AIAuditLog.tenant_id == tenant_id)
            .with_for_update()
        )
        if audit is not None and audit.status in {"pending", "running"}:
            audit.status = "failed"
            audit.error_code = "stale_execution"
            audit.completed_at = current
        ledger = db.session.scalar(
            select(AIUsageLedger)
            .where(
                AIUsageLedger.audit_log_id == attempt.audit_log_id,
                AIUsageLedger.tenant_id == tenant_id,
                AIUsageLedger.status == "reserved",
            )
            .with_for_update()
        )
        if ledger is not None:
            ledger.status = "released"
            ledger.reserved_cost_micros = 0
            ledger.execution_token = revoked_token
    db.session.commit()
    return len(attempts)


def _canonical(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str).encode()


def _policy(tenant_id: uuid.UUID) -> AITenantPolicy:
    policy = db.session.scalar(
        select(AITenantPolicy).where(AITenantPolicy.tenant_id == tenant_id).with_for_update()
    )
    if policy is None or not policy.enabled or policy.kill_switch:
        raise AIPolicyDenied("La IA está deshabilitada para este tenant.")
    if policy.provider != current_app.config["AI_MODE"]:
        raise AIPolicyDenied("El proveedor configurado no está autorizado.")
    return policy


def _enforce_quota(policy: AITenantPolicy, tenant_id: uuid.UUID, reservation_micros: int) -> bool:
    now = datetime.now(UTC)
    month = now.strftime("%Y-%m")
    calls = (
        db.session.scalar(
            select(func.count(AIUsageLedger.id)).where(
                AIUsageLedger.tenant_id == tenant_id,
                func.date(AIUsageLedger.created_at) == now.date(),
                AIUsageLedger.status.in_(("reserved", "settled")),
            )
        )
        or 0
    )
    cost = (
        db.session.scalar(
            select(
                func.coalesce(
                    func.sum(
                        func.greatest(
                            AIUsageLedger.actual_cost_micros,
                            AIUsageLedger.reserved_cost_micros,
                        )
                    ),
                    0,
                )
            ).where(AIUsageLedger.tenant_id == tenant_id, AIUsageLedger.period == month)
        )
        or 0
    )
    running = (
        db.session.scalar(
            select(func.count(AIAuditLog.id)).where(
                AIAuditLog.tenant_id == tenant_id,
                AIAuditLog.status == "running",
            )
        )
        or 0
    )
    if running >= policy.max_concurrency:
        raise AIPolicyDenied("Límite de concurrencia del agente alcanzado.")
    if policy.daily_call_limit and calls >= policy.daily_call_limit:
        raise AIPolicyDenied("Límite diario de llamadas alcanzado.")
    if (
        policy.monthly_hard_budget_micros
        and cost + reservation_micros > policy.monthly_hard_budget_micros
    ):
        raise AIPolicyDenied("Presupuesto mensual agotado.")
    return bool(policy.monthly_soft_budget_micros and cost >= policy.monthly_soft_budget_micros)


def _short_text(value: Any, *, limit: int = 900) -> str:
    text_value = str(value or "").strip()
    if len(text_value) <= limit:
        return text_value
    return text_value[: limit - 1].rstrip() + "…"


# Tokens too generic to prove that a conclusion is grounded in cited facts.
_CONCLUSION_STOPWORDS = frozenset(
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
        "en",
        "y",
        "o",
        "u",
        "a",
        "al",
        "para",
        "por",
        "con",
        "sin",
        "sobre",
        "entre",
        "que",
        "se",
        "su",
        "sus",
        "lo",
        "le",
        "les",
        "me",
        "te",
        "nos",
        "os",
        "como",
        "más",
        "mas",
        "muy",
        "ya",
        "no",
        "si",
        "sí",
        "the",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "from",
        "as",
        "is",
        "are",
        "be",
        "this",
        "that",
        "an",
        "at",
        "by",
        "its",
        "into",
        "over",
        "under",
        "riesgo",
        "riesgos",
        "oportunidad",
        "oportunidades",
        "análisis",
        "analisis",
        "evaluación",
        "evaluacion",
        "propuesta",
        "candidato",
        "candidata",
        "demo",
        "sv2",
        "prueba",
        "risk",
        "risks",
        "opportunity",
        "opportunities",
        "analysis",
        "proposal",
        "candidate",
        "informe",
        "resumen",
        "summary",
        "título",
        "titulo",
        "title",
        "status",
        "estado",
        "watch",
        "mitigate",
        "investigate",
        "hold",
        "other",
        "high",
        "medium",
        "low",
        "critical",
    }
)

# Top-level prose that is a product conclusion, not a cited fact block.
_CONCLUSION_SCALAR_FIELDS = (
    "title",
    "headline",
    "summary",
    "description",
    "executive_summary",
)

_CONCLUSION_GROUNDING_AGENTS = frozenset(
    {
        "opportunity",
        "risk",
        "actor_partnership",
        "entity_resolution",
        "report_writer",
        "dossier_situation_summary",
    }
)

# Assertion-class stems / exact forms that attribute an outcome or legal fact.
# Token overlap alone measures *topic* (de qué se habla); this layer measures
# *claim predicates* (qué se afirma). A title may reuse tender vocabulary and
# still invent a win, sanction, breach, etc. that no cited fact supports.
#
# Why a closed set is enough *here*: the commercial damage is concrete false
# claims about real firms ("X gana la licitación"), not open-ended rhetoric.
# What it leaves out: paraphrase without these stems ("se alza con", "es la
# elegida", "queda fuera") — residual for a semantic reviewer / product decision.
_ASSERTION_EXACT = frozenset(
    {
        "gana",
        "ganó",
        "gano",
        "ganar",
        "ganando",
        "ganada",
        "ganado",
        "ganadas",
        "ganados",
        "ganador",
        "ganadora",
        "ganadores",
        "ganadoras",
        "vence",
        "venció",
        "vencio",
        "vencer",
        "vencedor",
        "vencedora",
        "vencedores",
        "vencedoras",
        "quiebra",
        "quiebras",
        "quebró",
        "quebro",
        "quebrar",
        "quebrado",
        "quebrada",
        "quebrados",
        "quebradas",
    }
)

# Long enough that accidental topic words (garantía, ganadería…) do not match.
_ASSERTION_STEMS = (
    "adjudic",  # adjudica, adjudicado, adjudicación, adjudicataria…
    "incumpl",  # incumple, incumplimiento…
    "sancion",  # sanciona, sanción → normalizado sin tilde en tokens
    "sanció",  # sanción as content token may keep accent depending on source
    "demandar",
    "demandó",
    "demandad",  # demandado/a/s
    "demandas",  # demandas (lawsuit plural; "demanda" alone is ambiguous)
)


def _content_tokens(text: str) -> set[str]:
    """Meaningful tokens for grounding checks (no stopwords, min length 3)."""

    tokens: set[str] = set()
    for match in re.findall(r"[0-9a-záéíóúüñA-ZÁÉÍÓÚÜÑ]{3,}", str(text or "").lower()):
        if match in _CONCLUSION_STOPWORDS:
            continue
        tokens.add(match)
    return tokens


def _assertion_family(token: str) -> str | None:
    """Return a canonical family id if ``token`` is an assertion-class predicate."""

    if token in _ASSERTION_EXACT:
        if token.startswith("gan"):
            return "gan"
        if token.startswith("venc"):
            return "venc"
        if token.startswith("quiebr") or token.startswith("quebr"):
            return "quebr"
        return token
    for stem in _ASSERTION_STEMS:
        if token.startswith(stem) or token == stem:
            # Collapse closely related stems into one family.
            if stem.startswith("adjudic"):
                return "adjudic"
            if stem.startswith("incumpl"):
                return "incumpl"
            if stem.startswith("sanci"):
                return "sancion"
            if stem.startswith("demand"):
                return "demand"
            if stem.startswith("quebr") or stem.startswith("quiebr"):
                return "quebr"
            return stem
    return None


def _assertion_families(text: str) -> set[str]:
    families: set[str] = set()
    for token in _content_tokens(text):
        family = _assertion_family(token)
        if family is not None:
            families.add(family)
    return families


def _unsupported_assertion_families(text: str, fact_corpus: str) -> set[str]:
    """Assertion families present in ``text`` but absent from the cited fact corpus."""

    title_families = _assertion_families(text)
    if not title_families:
        return set()
    fact_families = _assertion_families(fact_corpus)
    return title_families - fact_families


def _fact_statements(output: dict[str, Any]) -> list[str]:
    statements: list[str] = []
    for fact in output.get("facts") or []:
        if not isinstance(fact, dict):
            continue
        text = fact.get("statement") or fact.get("text")
        if isinstance(text, str) and text.strip():
            statements.append(text.strip())
    # Risk scenarios with evidence also count as grounded material for titles.
    for scenario in output.get("scenarios") or []:
        if not isinstance(scenario, dict) or not scenario.get("evidence_ids"):
            continue
        for key in ("name", "description"):
            text = scenario.get(key)
            if isinstance(text, str) and text.strip():
                statements.append(text.strip())
    return statements


def _declared_fit_statements(output: dict[str, Any]) -> list[str]:
    """Prosa de encaje anclada en material declarado (origin distinto del oficial)."""

    fit = output.get("fit_assessment")
    if not isinstance(fit, dict):
        return []
    if fit.get("origin") not in {None, "declared_by_client"}:
        return []
    if not fit.get("declared_evidence_ids"):
        return []
    text = fit.get("statement")
    if isinstance(text, str) and text.strip():
        return [text.strip()]
    return []


def _grounding_corpus_tokens(output: dict[str, Any], *, agent: str = "") -> set[str]:
    tokens: set[str] = set()
    for statement in _fact_statements(output):
        tokens |= _content_tokens(statement)
    # SV2-PERFIL-EVIDENCIA: el gate de fundamentación puede usar la oferta
    # declarada como fundamento del *encaje*, con origen distinto (fit_assessment).
    # No se mezcla con facts oficiales: los tokens entran etiquetados vía el
    # campo separado, no como si fueran extractos PLACSP.
    if agent == "opportunity":
        for statement in _declared_fit_statements(output):
            tokens |= _content_tokens(statement)
    return tokens


def _conclusion_supported(
    text: str,
    fact_tokens: set[str],
    *,
    min_ratio: float = 0.45,
    fact_corpus: str = "",
    require_assertion_grounding: bool = False,
) -> bool:
    """True when the conclusion is grounded in cited facts.

    Layer 1 — token overlap: enough content words of the conclusion appear in
    facts (topic grounding: *de qué se habla*).

    Layer 2 — assertion predicates (titles/headlines only when requested): verbs
    that attribute an outcome (ganar, adjudicar, sancionar…) must also appear
    in the fact corpus (*qué se afirma*). Overlap alone accepts
    «Nexus gana la licitación PLACSP…» when the fact only describes the tender.
    """

    tokens = _content_tokens(text)
    if not tokens:
        return True
    if not fact_tokens:
        return False
    overlap = tokens & fact_tokens
    if (len(overlap) / len(tokens)) < min_ratio:
        return False
    # Layer 2 only for titles/headlines: unsupported assertion predicates fail.
    if not require_assertion_grounding or not fact_corpus:
        return True
    return not _unsupported_assertion_families(text, fact_corpus)


def _honest_title_from_facts(facts: list[str], *, agent: str) -> str:
    """Prefer a poor honest title over a flashy unfounded one."""

    if not facts:
        if agent == "risk":
            return "Riesgo sin hechos citados"
        if agent == "opportunity":
            return "Oportunidad sin hechos citados"
        return "Análisis sin hechos citados"
    core = _short_text(facts[0], limit=140)
    # Surface the gap when the only grounded material is a procurement fact
    # without competition data — typical residual of the local model demo.
    lower = core.lower()
    if agent == "risk" and not any(
        token in lower for token in ("compet", "rival", "adversar", "amenaza")
    ):
        short = _short_text(core, limit=100)
        return f"{short}: sin datos de competencia" if len(short) < 110 else short
    return core


def _honest_prose_from_facts(facts: list[str], *, limit: int = 800) -> str:
    if not facts:
        return "No hay hechos citados que sostengan una conclusión."
    body = " ".join(_short_text(item, limit=260) for item in facts[:3])
    return _short_text(
        f"{body} Conclusión limitada a los hechos citados; no se afirma más de lo "
        "que la evidencia permite.",
        limit=limit,
    )


def _ground_conclusions_to_facts(
    output: dict[str, Any],
    *,
    agent: str,
) -> dict[str, Any]:
    """Make title/summary/description answer for the cited facts.

    Design hole closed here (not only model quality): the evidence reviewer
    historically audited claim blocks with ``evidence_ids``, while the product
    title/recommendation/summary could invent a theme the facts never support.
    This gate is deterministic, always runs for conclusion agents, and degrades
    unfounded prose instead of failing the job (agents stay ``succeeded``).
    """

    if agent not in _CONCLUSION_GROUNDING_AGENTS:
        return output

    facts = _fact_statements(output)
    declared_fit = _declared_fit_statements(output)
    # Corpus de fundamentación: facts oficiales + (solo opportunity) encaje declarado.
    grounding_statements = [*facts, *declared_fit]
    fact_tokens = _grounding_corpus_tokens(output, agent=agent)
    fact_corpus = " ".join(grounding_statements)
    result = dict(output)
    warnings = list(result["warnings"]) if isinstance(result.get("warnings"), list) else []
    degraded: list[str] = []

    for field in _CONCLUSION_SCALAR_FIELDS:
        value = result.get(field)
        if not isinstance(value, str) or not value.strip():
            continue
        # Titles are judged more strictly: every flashy orphan word is product damage.
        # They also require assertion-predicate grounding (SV2-TITULO-FALSO).
        is_title = field in {"title", "headline"}
        ratio = 0.5 if is_title else 0.35
        if _conclusion_supported(
            value,
            fact_tokens,
            min_ratio=ratio,
            fact_corpus=fact_corpus,
            require_assertion_grounding=is_title,
        ):
            continue
        if is_title:
            honest = _honest_title_from_facts(grounding_statements or facts, agent=agent)
        else:
            honest = _honest_prose_from_facts(
                grounding_statements or facts, limit=800 if field != "summary" else 600
            )
        degraded.append(
            f"{field} («{_short_text(value, limit=72)}» → «{_short_text(honest, limit=72)}»)"
        )
        result[field] = honest

    nba = result.get("next_best_action")
    if isinstance(nba, dict):
        updated = dict(nba)
        for field in ("action", "rationale"):
            value = updated.get(field)
            if not isinstance(value, str) or not value.strip():
                continue
            if _conclusion_supported(value, fact_tokens, min_ratio=0.35):
                continue
            seed = grounding_statements or facts
            if seed:
                updated[field] = _short_text(
                    f"Revisar a la luz de: {_short_text(seed[0], limit=220)}",
                    limit=500 if field == "action" else 800,
                )
            else:
                updated[field] = "Sin hechos citados; se requiere revisión humana."
            degraded.append(f"next_best_action.{field}")
        result["next_best_action"] = updated

    if degraded:
        warnings.append(
            "Conclusión no fundada en hechos citados: se degradó "
            + "; ".join(degraded)
            + ". Se publica un título/resumen honesto en lugar de uno vistoso sin base."
        )
        result["warnings"] = warnings
        if isinstance(result.get("confidence"), int):
            result["confidence"] = min(int(result["confidence"]), 45)

    return result


def _conclusion_review_claims(output: dict[str, Any]) -> list[dict[str, Any]]:
    """Surface title/summary/etc. as reviewable claims (they lack evidence_ids)."""

    claims: list[dict[str, Any]] = []
    for field in _CONCLUSION_SCALAR_FIELDS:
        value = output.get(field)
        if not isinstance(value, str) or not value.strip():
            continue
        claims.append(
            {
                "path": f"$.{field}",
                "kind": "conclusion",
                "confidence": output.get("confidence"),
                "evidence_ids": [],
                "claim": _short_text(value, limit=900),
                "grounding_note": (
                    "Conclusión de producto: debe sostenerse en los facts citados "
                    "(candidate_claims con evidence_ids) o marcarse unsupported."
                ),
            }
        )
    recommendation = output.get("recommendation")
    if isinstance(recommendation, str) and recommendation.strip():
        claims.append(
            {
                "path": "$.recommendation",
                "kind": "conclusion",
                "confidence": output.get("confidence"),
                "evidence_ids": [],
                "claim": f"recommendation={recommendation.strip()}",
                "grounding_note": (
                    "La recomendación debe ser coherente con los facts citados; "
                    "no inventes urgencia o go/no_go sin base."
                ),
            }
        )
    recommended_status = output.get("recommended_status")
    if isinstance(recommended_status, str) and recommended_status.strip():
        claims.append(
            {
                "path": "$.recommended_status",
                "kind": "conclusion",
                "confidence": output.get("confidence"),
                "evidence_ids": [],
                "claim": f"recommended_status={recommended_status.strip()}",
                "grounding_note": (
                    "El estado recomendado debe ser coherente con los facts citados."
                ),
            }
        )
    return claims


def _review_candidate_claims(value: Any, *, path: str = "$") -> list[dict[str, Any]]:
    """Extract reviewable material claims without sending the whole generated artifact.

    The reviewer only needs compact claims, their classification and cited evidence. Long report
    paragraphs are capped here; if the cap ever hides relevant unsupported content, the remedy is a
    stronger claim extractor, not sending procurement aggregates and full prose back to the model.
    """

    claims: list[dict[str, Any]] = []
    if isinstance(value, dict):
        evidence_ids = value.get("evidence_ids")
        if isinstance(evidence_ids, list):
            text_parts: list[str] = []
            for key in (
                "text",
                "statement",
                "action",
                "rationale",
                "reasoning_summary",
                "reason",
                "change",
                "relevance",
                "decision",
            ):
                text = value.get(key)
                if isinstance(text, str) and text.strip():
                    text_parts.append(text)
            claims.append(
                {
                    "path": path,
                    "kind": value.get("kind") or value.get("priority") or value.get("importance"),
                    "confidence": value.get("confidence"),
                    "evidence_ids": [str(item) for item in evidence_ids],
                    "claim": _short_text(" ".join(text_parts), limit=900),
                }
            )
        for key, child in value.items():
            claims.extend(_review_candidate_claims(child, path=f"{path}.{key}"))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            claims.extend(_review_candidate_claims(child, path=f"{path}[{index}]"))
    return claims


def _review_candidate_outline(output: dict[str, Any]) -> dict[str, Any]:
    outline: dict[str, Any] = {}
    for key in (
        "title",
        "headline",
        "executive_summary",
        "coverage_summary",
        "situation_status",
        "confidence",
    ):
        if key in output:
            value = output[key]
            outline[key] = _short_text(value, limit=1_200) if isinstance(value, str) else value
    for key in (
        "top_opportunities",
        "top_risks",
        "recommended_actions",
        "decisions_required",
        "open_questions",
        "warnings",
    ):
        value = output.get(key)
        if isinstance(value, list):
            outline[key] = [_short_text(item, limit=500) for item in value[:8]]
    sections = output.get("sections")
    if isinstance(sections, list):
        outline["sections"] = [
            {
                "index": index,
                "heading": _short_text(section.get("heading"), limit=180),
                "paragraph_count": len(section.get("paragraphs", []))
                if isinstance(section, dict) and isinstance(section.get("paragraphs"), list)
                else 0,
            }
            for index, section in enumerate(sections[:20])
            if isinstance(section, dict)
        ]
    return outline


def _review_evidence_index(context: BuiltContext) -> list[dict[str, Any]]:
    allowed_ids = {str(item) for item in context.manifest.get("evidence_ids", [])}
    items: list[dict[str, Any]] = []
    for row in context.evidence:
        if str(row.id) not in allowed_ids:
            continue
        items.append(
            {
                "id": str(row.id),
                "source_kind": row.source_kind,
                "classification": row.classification,
                "locator": row.locator,
                "extract": _short_text(row.extract, limit=1_200),
            }
        )
    # Evidencia declarada (perfil): visible para el revisor con source_kind propio.
    manifest = context.manifest if isinstance(getattr(context, "manifest", None), dict) else {}
    declared_ids = {str(item) for item in (manifest.get("declared_evidence_ids") or [])}
    payload = getattr(context, "payload", None)
    declared_items = payload.get("declared_evidence") if isinstance(payload, dict) else None
    for raw in declared_items or []:
        if not isinstance(raw, dict):
            continue
        rid = str(raw.get("id") or "")
        if not rid or (declared_ids and rid not in declared_ids):
            continue
        items.append(
            {
                "id": rid,
                "source_kind": str(raw.get("source_kind") or "declared"),
                "classification": str(raw.get("classification") or "internal"),
                "locator": raw.get("locator") if isinstance(raw.get("locator"), dict) else {},
                "extract": _short_text(raw.get("extract"), limit=1_200),
                "origin": "declared_by_client",
                "label": raw.get("label") or "Declarado por el cliente",
            }
        )
    return items


def _reviewer_context(
    *,
    agent: str,
    prompt: Any,
    context: BuiltContext,
    output: dict[str, Any],
) -> dict[str, Any]:
    # Material claims (with evidence_ids) plus product conclusions (title/summary/…).
    # Without the latter the reviewer cannot judge a flashy unfounded title even when
    # the outline already carries it — the old instruction told it to ignore outline.
    claims = [*_review_candidate_claims(output), *_conclusion_review_claims(output)]
    return {
        "review_task": {
            "candidate_agent": agent,
            "candidate_schema": prompt.output_schema_name,
            "instruction": (
                "Revisa claims compactos (con evidence_ids) y conclusiones de producto "
                "(kind=conclusion: title, summary, description, recommendation). "
                "Cada conclusión debe sostenerse en los facts citados: si el título o el "
                "resumen inventan un tema ausente en los facts (p. ej. 'competencia en "
                "software' con facts solo de impermeabilización), márcalo en "
                "unsupported_claims con path $.title / $.summary. "
                "No reescribas el informe y no repitas claims válidos."
            ),
        },
        "allowed_evidence_ids": [str(item) for item in context.manifest.get("evidence_ids", [])],
        "candidate_outline": _review_candidate_outline(output),
        "candidate_claims": claims,
        "evidence": _review_evidence_index(context),
        "security": {
            "context_classification": context.classification,
            "redaction_summary": context.redaction_summary,
            "injection_indicators": list(context.injection_indicators),
        },
    }


def _reviewer_output_budget(
    *,
    reviewer_prompt_tokens: int,
    policy_tokens: int,
    claim_count: int,
) -> int:
    # The reviewer emits only issues and corrections. This measured envelope scales with the
    # number of reviewable claims but stays well below the 16k ceiling used for long reports.
    desired = max(reviewer_prompt_tokens, min(4_000, 1_200 + claim_count * 90))
    return min(desired, policy_tokens)


def _is_conclusion_path(path: str) -> bool:
    """True when the reviewer is pointing at a product conclusion (title/summary/…)."""

    normalized = str(path or "").strip()
    if not normalized:
        return False
    conclusion_fields = (
        *_CONCLUSION_SCALAR_FIELDS,
        "recommendation",
        "recommended_status",
        "rationale",
        "decision",
    )
    for field in conclusion_fields:
        if normalized in {field, f"$.{field}", f"candidate_outline.{field}"}:
            return True
        if normalized.endswith(f".{field}") or normalized.endswith(f"['{field}']"):
            return True
    return False


def _strip_reviewer_rejected_claims(
    output: dict[str, Any],
    reviewer: EvidenceReviewerOutput,
    *,
    lenient: bool = False,
) -> dict[str, Any]:
    """Remove only claim blocks that a failed reviewer identifies unambiguously.

    Signal has returned both original JSON paths and paths invented over the compact reviewer
    package. A direct path is trusted only when it names a claim Oracle actually sent and carries
    the same text. Otherwise an exact, unique text match recovers the original output path.

    Objection classes (never mixed):

    * **Quality** (``confidence_issues``, ``classification_errors``): with ``lenient=True``
      (report_writer, opportunity, risk) degrade to visible warnings so a successful generate
      still yields a proposal for the human gate. Strict mode stays fail-closed.
    * **Security** (``privacy_or_security_issues``, ``prompt_injection_indicators``): always
      fail-closed. Open-source ingestion must not publish when the reviewer suspects injection
      or a privacy/security issue, even for lenient agents.
    * **Scoped claims** that the reviewer flags but cannot be uniquely anchored: fail-closed
      always. Publishing the claim with a footnote would leave content the reviewer rejected.
      Fuzzy path/text matching is the recovery path; if it fails, refuse to publish.
    * **Conclusion fields** (title/summary/…): never stripped here. They are degraded by
      ``_ground_conclusions_to_facts`` so an unfounded title becomes honest instead of killing
      the job.
    """

    scoped_issues: list[ClaimIssue] = [
        issue
        for issue in (
            *reviewer.unsupported_claims,
            *reviewer.misused_evidence,
            *reviewer.missing_evidence,
        )
        if not _is_conclusion_path(issue.path)
    ]
    conclusion_issues: list[ClaimIssue] = [
        issue
        for issue in (
            *reviewer.unsupported_claims,
            *reviewer.misused_evidence,
            *reviewer.missing_evidence,
        )
        if _is_conclusion_path(issue.path)
    ]
    quality_issues: list[str] = [
        *reviewer.classification_errors,
        *reviewer.confidence_issues,
    ]
    security_issues: list[str] = [
        *reviewer.privacy_or_security_issues,
        *reviewer.prompt_injection_indicators,
    ]
    unanchored: list[ClaimIssue] = []

    if security_issues:
        detail = "; ".join(
            _short_text(str(sec_note), limit=200) for sec_note in security_issues[:6]
        )
        raise EvidenceReviewError(
            "El revisor rechazó el output por objeciones de seguridad "
            f"(privacidad o inyección de prompt): {detail}"
        )

    if not scoped_issues:
        # Solo calidad, conclusiones de producto, o fail vacío: en lenient publicar con
        # advertencia (las conclusiones las degrada _ground_conclusions_to_facts). Estricto falla
        # salvo cuando las únicas objeciones scoped eran conclusiones (path $.title etc.).
        if lenient or conclusion_issues:
            warnings = output.get("warnings")
            if not isinstance(warnings, list):
                raise EvidenceReviewError("El informe no permite declarar el recorte del revisor.")
            warnings = list(warnings)
            if quality_issues:
                warnings.append(
                    "Revisión de evidencia: el revisor objetó con motivos de calidad no "
                    f"retirables por claim ({len(quality_issues)}); la propuesta se publica "
                    "con advertencia."
                )
                for quality_note in quality_issues[:12]:
                    warnings.append(
                        f"Objeción de calidad: {_short_text(str(quality_note), limit=800)}"
                    )
            if conclusion_issues:
                warnings.append(
                    "Revisión de evidencia: el revisor objetó conclusiones de producto "
                    f"({len(conclusion_issues)}); se degradarán al fundarse en hechos citados."
                )
                for conclusion_issue in conclusion_issues[:8]:
                    warnings.append(
                        "Conclusión objetada: "
                        f"{_short_text(conclusion_issue.claim, limit=400)} "
                        f"Motivo: {_short_text(conclusion_issue.reason, limit=400)}"
                    )
            if not quality_issues and not conclusion_issues:
                warnings.append(
                    "Revisión de evidencia: veredicto fail sin claims anclables ni objeciones "
                    "de seguridad; la propuesta se publica con advertencia."
                )
            return {**output, "warnings": warnings}
        raise EvidenceReviewError(
            "El revisor rechazó el resumen con objeciones que no se pueden retirar por claim."
        )
    if quality_issues and not lenient:
        raise EvidenceReviewError(
            "El revisor rechazó el resumen con objeciones de calidad que no se pueden retirar "
            "por claim."
        )

    candidates = _review_candidate_claims(output)
    resolved: dict[str, ClaimIssue] = {}
    for claim_issue in scoped_issues:
        direct = [
            candidate
            for candidate in candidates
            if candidate["path"] == claim_issue.path and candidate["claim"] == claim_issue.claim
        ]
        exact_text = [
            candidate for candidate in candidates if candidate["claim"] == claim_issue.claim
        ]
        # Reviewer paths over the compact package often miss the original JSON path; fall back
        # to a unique path suffix or unique substring match before giving up.
        path_suffix = [
            candidate
            for candidate in candidates
            if claim_issue.path
            and (
                str(candidate["path"]).endswith(claim_issue.path)
                or claim_issue.path.endswith(str(candidate["path"]))
            )
            and (
                candidate["claim"] == claim_issue.claim
                or claim_issue.claim in str(candidate["claim"])
                or str(candidate["claim"]) in claim_issue.claim
            )
        ]
        fuzzy_text = [
            candidate
            for candidate in candidates
            if claim_issue.claim
            and (
                claim_issue.claim in str(candidate["claim"])
                or str(candidate["claim"]) in claim_issue.claim
            )
        ]
        matches = direct or exact_text or path_suffix
        if not matches and len({str(c["path"]) for c in fuzzy_text}) == 1:
            matches = fuzzy_text
        unique_paths = {str(candidate["path"]) for candidate in matches}
        if len(unique_paths) != 1 or "$" in unique_paths:
            # Claim señalada y no anclable: fail-closed siempre (también en indulgente).
            # Publicar la afirmación con una nota al pie no es defendible.
            unanchored.append(claim_issue)
            continue
        resolved[next(iter(unique_paths))] = claim_issue

    if unanchored:
        sample = unanchored[0]
        raise EvidenceReviewError(
            "El revisor rechazó el resumen, pero su claim no se pudo anclar de forma única "
            f"({len(unanchored)} objeción(es) sin ancla). No se publica el contenido objetado. "
            f"Ejemplo: {_short_text(sample.claim, limit=300)}"
        )

    if not resolved:
        raise EvidenceReviewError(
            "El revisor rechazó el resumen, pero su claim no se pudo anclar de forma única."
        )

    dropped = object()

    def clean(value: Any, *, path: str = "$") -> Any:
        if path in resolved:
            return dropped
        if isinstance(value, dict):
            cleaned: dict[str, Any] = {}
            for key, child in value.items():
                candidate = clean(child, path=f"{path}.{key}")
                if candidate is not dropped:
                    cleaned[key] = candidate
            return cleaned
        if isinstance(value, list):
            cleaned_items = [
                clean(child, path=f"{path}[{index}]") for index, child in enumerate(value)
            ]
            return [item for item in cleaned_items if item is not dropped]
        return value

    cleaned_output = clean(output)
    if not isinstance(cleaned_output, dict):
        raise EvidenceReviewError("El revisor objetó el resumen completo; no se puede publicar.")
    warnings = cleaned_output.get("warnings")
    if not isinstance(warnings, list):
        raise EvidenceReviewError("El resumen no permite declarar el recorte del revisor.")
    warnings = list(warnings)
    cleaned_output = {**cleaned_output, "warnings": warnings}
    count = len(resolved)
    if count:
        label = "afirmación objetada" if count == 1 else "afirmaciones objetadas"
        warnings.append(f"Revisión de evidencia: se retiraron {count} {label} antes de publicar.")
    for resolved_issue in resolved.values():
        warnings.append(
            "Afirmación retirada: "
            f"{_short_text(resolved_issue.claim, limit=500)} "
            f"Motivo: {_short_text(resolved_issue.reason, limit=500)}"
        )
    # Calidad residual junto a claims anclados: en indulgente se documenta; no bloquea el recorte.
    if quality_issues and lenient:
        warnings.append(
            "Revisión de evidencia: además se conservan "
            f"{len(quality_issues)} objeción(es) de calidad como advertencia."
        )
        for quality_note in quality_issues[:12]:
            warnings.append(f"Objeción de calidad: {_short_text(str(quality_note), limit=800)}")
    if conclusion_issues:
        warnings.append(
            "Revisión de evidencia: el revisor objetó conclusiones de producto "
            f"({len(conclusion_issues)}); se degradarán al fundarse en hechos citados."
        )
        for conclusion_issue in conclusion_issues[:8]:
            warnings.append(
                "Conclusión objetada: "
                f"{_short_text(conclusion_issue.claim, limit=400)} "
                f"Motivo: {_short_text(conclusion_issue.reason, limit=400)}"
            )
    return cleaned_output


_WIZARD_SECTION_COUNTS = {
    "signals": "signals",
    "procurement": "procurement_items",
    "opportunities": "opportunities",
    "risks": "risks",
    "actors": "actors",
    "hypotheses": "hypotheses",
}

_WIZARD_PREFILL_REQUIREMENTS: dict[str, tuple[str, ...]] = {
    "create_signal_monitor": ("name", "query"),
    "pin_procurement": ("procurement_query", "procurement_kind"),
    "create_opportunity": ("title", "description"),
    "create_risk": ("title", "description"),
    "create_actor": ("title", "actor_type"),
}


def validate_dossier_completion_output(output: dict[str, Any], context: BuiltContext) -> None:
    """Reject objectively false or unusable wizard guidance before it becomes an artifact."""

    if context.manifest.get("snapshot_kind") != "dossier_completion_wizard":
        raise WizardOutputValidationError(
            "El contexto del wizard no es un snapshot de completitud."
        )
    snapshot = context.payload.get("completion_snapshot")
    if not isinstance(snapshot, dict):
        raise WizardOutputValidationError("Falta el snapshot determinista de completitud.")
    counts = snapshot.get("counts")
    if not isinstance(counts, dict):
        raise WizardOutputValidationError("Faltan los recuentos deterministas del expediente.")
    diagnostics = output.get("section_diagnostics")
    if not isinstance(diagnostics, list):
        raise WizardOutputValidationError("El diagnóstico del wizard no es una lista válida.")
    seen_sections: set[str] = set()
    for item in diagnostics:
        if not isinstance(item, dict):
            raise WizardOutputValidationError("El diagnóstico contiene un elemento inválido.")
        section = str(item.get("section") or "")
        status = str(item.get("status") or "")
        seen_sections.add(section)
        count_key = _WIZARD_SECTION_COUNTS.get(section)
        if count_key and status == "empty" and int(counts.get(count_key) or 0) > 0:
            raise WizardOutputValidationError(
                f"El wizard declaró {section}: empty, pero el expediente tiene datos."
            )
        if section == "goal" and status == "empty":
            dossier = snapshot.get("dossier")
            if isinstance(dossier, dict) and str(dossier.get("strategic_goal") or "").strip():
                raise WizardOutputValidationError(
                    "El wizard declaró goal: empty, pero el expediente tiene objetivo."
                )
    required_sections = set(_WIZARD_SECTION_COUNTS) | {"goal"}
    missing = required_sections - seen_sections
    if missing:
        raise WizardOutputValidationError(
            "El diagnóstico del wizard no cubre secciones obligatorias: "
            + ", ".join(sorted(missing))
        )
    questions = output.get("questions")
    if not isinstance(questions, list):
        raise WizardOutputValidationError("Las preguntas del wizard no son una lista válida.")
    if int(counts.get("actors") or 0) > 0:
        for question in questions:
            if not isinstance(question, dict):
                raise WizardOutputValidationError("El wizard devolvió una pregunta inválida.")
            haystack = " ".join(
                str(question.get(key) or "").casefold()
                for key in ("id", "question", "why_it_matters", "expected_input")
            )
            if "actor" in haystack and any(
                marker in haystack
                for marker in ("no hay", "ningún", "ningun", "falta actor", "sin actor")
            ):
                raise WizardOutputValidationError(
                    "El wizard pregunta por una ausencia de actores que no existe."
                )
    actions = output.get("recommended_actions")
    if not isinstance(actions, list):
        raise WizardOutputValidationError("Las acciones recomendadas no son una lista válida.")
    for action in actions:
        if not isinstance(action, dict):
            raise WizardOutputValidationError("El wizard devolvió una acción inválida.")
        kind = str(action.get("kind") or "")
        required = _WIZARD_PREFILL_REQUIREMENTS.get(kind, ())
        prefill = action.get("prefill")
        if required and not isinstance(prefill, dict):
            raise WizardOutputValidationError(
                f"La acción {kind} no incluye un prefill estructurado."
            )
        missing_fields = [
            field
            for field in required
            if not str(cast(dict[str, Any], prefill).get(field) or "").strip()
        ]
        if missing_fields:
            raise WizardOutputValidationError(
                f"La acción {kind} no incluye prefill suficiente: {', '.join(missing_fields)}."
            )


def execute_agent(
    *,
    agent: str,
    dossier_id: uuid.UUID | None,
    job: BackgroundJob,
    supplemental_context: dict[str, Any] | None = None,
    context_override: BuiltContext | None = None,
    context_factory: Callable[[int], BuiltContext] | None = None,
    target_type: str = "dossier",
    target_id: uuid.UUID | None = None,
) -> dict[str, Any]:
    tenant_id = require_tenant_id()
    if dossier_id is None and agent != "tender_search_wizard":
        raise AIPolicyDenied("Solo el wizard de licitaciones admite ejecución sin expediente.")
    if dossier_id is None and context_override is None and context_factory is None:
        raise AIPolicyDenied("La ejecución sin expediente requiere contexto tenant-scoped.")
    # Serialize the idempotency slot before policy/quota reservation. The lock is
    # transaction-scoped and never held across a provider call.
    slot = f"{tenant_id}:{job.id}:{agent}"
    db.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:slot, 0))"), {"slot": slot}
    )
    succeeded = db.session.scalar(
        select(AIAuditLog)
        .join(AIArtifact, AIArtifact.audit_log_id == AIAuditLog.id)
        .where(
            AIAuditLog.tenant_id == tenant_id,
            AIAuditLog.background_job_id == job.id,
            AIAuditLog.agent == agent,
            AIAuditLog.status == "succeeded",
        )
        .order_by(AIAuditLog.started_at.desc(), AIAuditLog.created_at.desc())
    )
    if succeeded is not None:
        artifact = db.session.scalar(
            select(AIArtifact).where(AIArtifact.audit_log_id == succeeded.id)
        )
        if artifact is not None:
            db.session.rollback()
            return {
                "artifact_id": str(artifact.id),
                "audit_log_id": str(succeeded.id),
                "status": artifact.status,
            }
    active = db.session.scalar(
        select(AIAuditLog)
        .where(
            AIAuditLog.tenant_id == tenant_id,
            AIAuditLog.background_job_id == job.id,
            AIAuditLog.agent == agent,
            AIAuditLog.status.in_(("pending", "running")),
        )
        .order_by(AIAuditLog.started_at.desc(), AIAuditLog.created_at.desc())
    )
    if active is not None:
        db.session.rollback()
        raise AIPolicyDenied("La ejecución IA de este job ya está en curso.")
    policy = _policy(tenant_id)
    reservation_micros = 2 * (policy.max_context_tokens + policy.max_output_tokens)
    soft_budget_warning = (
        False
        if agent == "tender_search_wizard"
        else _enforce_quota(policy, tenant_id, reservation_micros)
    )
    prompt = PromptRegistry(current_app.config["AI_DEFAULT_MODEL"]).get(agent)
    if policy.allowed_models and prompt.model not in policy.allowed_models:
        raise AIPolicyDenied("Modelo no autorizado por la política del tenant.")
    if context_override is not None and context_factory is not None:
        raise AIPolicyDenied("Solo puede definirse un origen de contexto preconstruido.")
    context = (
        context_override
        or (context_factory(policy.max_context_tokens) if context_factory else None)
        or (
            build_context(dossier_id, max_tokens=policy.max_context_tokens)
            if dossier_id is not None
            else None
        )
    )
    if context is None:
        raise AIPolicyDenied("No se pudo construir el contexto de la ejecución.")
    if context.manifest.get("dossier_id") != (str(dossier_id) if dossier_id is not None else None):
        raise AIPolicyDenied("El contexto preconstruido no pertenece al expediente.")
    if dossier_id is None and context.evidence:
        raise AIPolicyDenied("El contexto tenant-scoped no admite evidencia de expediente.")
    if context.classification == "internal" and policy.max_classification == "public":
        raise AIPolicyDenied("La clasificación del contexto excede la política.")
    effective_payload = dict(context.payload)
    if supplemental_context:
        effective_payload["requested_scope"] = supplemental_context
    effective_context_hash = hashlib.sha256(
        _canonical(
            {
                "base_context_hash": context.context_hash.hex(),
                "requested_scope": supplemental_context or {},
            }
        )
    ).digest()
    input_hash = hashlib.sha256(_canonical(effective_payload)).digest()
    if agent == "tender_search_wizard":
        cached_artifact = db.session.scalar(
            select(AIArtifact)
            .join(AIAuditLog, AIAuditLog.id == AIArtifact.audit_log_id)
            .where(
                AIArtifact.tenant_id == tenant_id,
                AIArtifact.agent == agent,
                AIArtifact.target_type == target_type,
                AIArtifact.target_id == target_id,
                AIAuditLog.tenant_id == tenant_id,
                AIAuditLog.agent == agent,
                AIAuditLog.status == "succeeded",
                AIAuditLog.input_hash == input_hash,
                AIAuditLog.prompt_hash == prompt.sha256,
            )
            .order_by(AIArtifact.created_at.desc(), AIArtifact.id.desc())
            .limit(1)
        )
        if cached_artifact is not None:
            audit_id = cached_artifact.audit_log_id
            db.session.rollback()
            return {
                "artifact_id": str(cached_artifact.id),
                "audit_log_id": str(audit_id),
                "status": cached_artifact.status,
                "cache_hit": True,
            }
        soft_budget_warning = _enforce_quota(policy, tenant_id, reservation_micros)
    now = datetime.now(UTC)
    execution_token = uuid.uuid4()
    lease_seconds = max(30, min(int(current_app.config["CELERY_TASK_TIME_LIMIT"]), 600))
    lease_expires_at = now + timedelta(seconds=lease_seconds)
    source_manifest = context.manifest | {
        "requested_scope_hash": hashlib.sha256(_canonical(supplemental_context or {})).hexdigest(),
        "requires_evidence_review": prompt.requires_evidence_review,
        "evidence_review_failure_policy": prompt.evidence_review_failure_policy,
    }
    audit = db.session.scalar(
        select(AIAuditLog)
        .where(
            AIAuditLog.tenant_id == tenant_id,
            AIAuditLog.background_job_id == job.id,
            AIAuditLog.agent == agent,
            AIAuditLog.status.in_(("failed", "denied")),
        )
        .order_by(AIAuditLog.started_at.desc(), AIAuditLog.created_at.desc())
        .with_for_update()
    )
    if audit is None:
        audit = AIAuditLog(
            tenant_id=tenant_id,
            dossier_id=dossier_id,
            background_job_id=job.id,
            requested_by_user_id=job.requested_by_user_id,
            use_case=agent,
            agent=agent,
            action="generate",
            provider=policy.provider,
            model=prompt.model,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            prompt_hash=prompt.sha256,
            context_hash=effective_context_hash,
            schema_name=prompt.output_schema_name,
            schema_version="v1",
            input_hash=input_hash,
            source_ids=list(context.manifest["evidence_ids"]),
            status="running",
            data_classification=context.classification,
            redaction_applied=bool(context.redaction_summary["matches"]),
            redaction_summary=context.redaction_summary,
            estimated_cost_micros=reservation_micros,
            started_at=now,
        )
        db.session.add(audit)
    else:
        audit.dossier_id = dossier_id
        audit.requested_by_user_id = job.requested_by_user_id
        audit.use_case = agent
        audit.action = "generate"
        audit.provider = policy.provider
        audit.model = prompt.model
        audit.prompt_name = prompt.name
        audit.prompt_version = prompt.version
        audit.prompt_hash = prompt.sha256
        audit.context_hash = effective_context_hash
        audit.schema_name = prompt.output_schema_name
        audit.schema_version = "v1"
        audit.input_hash = input_hash
        audit.output_hash = None
        audit.source_ids = list(context.manifest["evidence_ids"])
        audit.status = "running"
        audit.data_classification = context.classification
        audit.redaction_applied = bool(context.redaction_summary["matches"])
        audit.redaction_summary = context.redaction_summary
        audit.input_tokens = audit.output_tokens = audit.actual_cost_micros = 0
        audit.latency_ms = None
        audit.estimated_cost_micros = reservation_micros
        audit.error_code = None
        audit.started_at = now
        audit.completed_at = None
    db.session.flush()
    snapshot = db.session.scalar(
        select(AIContextSnapshot)
        .where(AIContextSnapshot.audit_log_id == audit.id, AIContextSnapshot.tenant_id == tenant_id)
        .with_for_update()
    )
    if snapshot is None:
        snapshot = AIContextSnapshot(
            tenant_id=tenant_id,
            audit_log_id=audit.id,
            dossier_id=dossier_id,
            context_hash=effective_context_hash,
            source_manifest=source_manifest,
            classification=context.classification,
            redaction_summary=context.redaction_summary,
            estimated_tokens=context.estimated_tokens,
            injection_indicators=list(context.injection_indicators),
        )
        db.session.add(snapshot)
    else:
        snapshot.dossier_id = dossier_id
        snapshot.context_hash = effective_context_hash
        snapshot.source_manifest = source_manifest
        snapshot.classification = context.classification
        snapshot.redaction_summary = context.redaction_summary
        snapshot.estimated_tokens = context.estimated_tokens
        snapshot.injection_indicators = list(context.injection_indicators)
        db.session.execute(
            delete(AIContextEvidence).where(
                AIContextEvidence.tenant_id == tenant_id,
                AIContextEvidence.snapshot_id == snapshot.id,
            )
        )
    db.session.flush()
    for evidence in context.evidence:
        db.session.add(
            AIContextEvidence(
                tenant_id=tenant_id,
                snapshot_id=snapshot.id,
                evidence_id=evidence.id,
                dossier_id=dossier_id,
                evidence_hash=bytes.fromhex(
                    str(context.manifest["evidence_hashes"][str(evidence.id)])
                ),
            )
        )
    request = LLMRequest(
        agent,
        prompt.model,
        prompt.text,
        prompt.purpose,
        effective_payload,
        min(prompt.max_output_tokens, policy.max_output_tokens),
        context.classification,
    )
    next_attempt_number = (
        db.session.scalar(
            select(func.max(AIAttempt.attempt_number)).where(
                AIAttempt.tenant_id == tenant_id,
                AIAttempt.audit_log_id == audit.id,
            )
        )
        or 0
    ) + 1
    attempt = AIAttempt(
        tenant_id=tenant_id,
        audit_log_id=audit.id,
        attempt_number=next_attempt_number,
        kind="generate",
        status="reserved",
        request_hash=input_hash,
        started_at=now,
        execution_token=execution_token,
        lease_expires_at=lease_expires_at,
    )
    db.session.add(attempt)
    db.session.flush()
    usage = db.session.scalar(
        select(AIUsageLedger)
        .where(AIUsageLedger.tenant_id == tenant_id, AIUsageLedger.audit_log_id == audit.id)
        .with_for_update()
    )
    if usage is None:
        usage = AIUsageLedger(
            tenant_id=tenant_id,
            audit_log_id=audit.id,
            period=now.strftime("%Y-%m"),
            provider=policy.provider,
            model=prompt.model,
            input_tokens=0,
            output_tokens=0,
            # Conservative mock-independent reservation. A real adapter must expose its
            # pricing estimator before it can be allowlisted.
            reserved_cost_micros=reservation_micros,
            actual_cost_micros=0,
            status="reserved",
            execution_token=execution_token,
        )
        db.session.add(usage)
    else:
        usage.period = now.strftime("%Y-%m")
        usage.provider = policy.provider
        usage.model = prompt.model
        usage.input_tokens = 0
        usage.output_tokens = 0
        usage.reserved_cost_micros = reservation_micros
        usage.actual_cost_micros = 0
        usage.status = "reserved"
        usage.execution_token = execution_token
    db.session.commit()
    audit_id, attempt_id, usage_id = audit.id, attempt.id, usage.id

    def fail(error: BaseException, *, active_attempt_id: uuid.UUID) -> None:
        """Fenced terminalization in a fresh transaction after any provider failure."""
        db.session.rollback()
        completed = datetime.now(UTC)
        current_attempt = db.session.scalar(
            select(AIAttempt)
            .where(
                AIAttempt.id == active_attempt_id,
                AIAttempt.tenant_id == tenant_id,
                AIAttempt.execution_token == execution_token,
            )
            .with_for_update()
        )
        current_audit = db.session.scalar(
            select(AIAuditLog)
            .where(AIAuditLog.id == audit_id, AIAuditLog.tenant_id == tenant_id)
            .with_for_update()
        )
        current_usage = db.session.scalar(
            select(AIUsageLedger)
            .where(
                AIUsageLedger.id == usage_id,
                AIUsageLedger.tenant_id == tenant_id,
                AIUsageLedger.execution_token == execution_token,
                AIUsageLedger.status == "reserved",
            )
            .with_for_update()
        )
        if current_attempt is None or current_audit is None or current_usage is None:
            db.session.rollback()
            raise AIPolicyDenied("La lease de la ejecución IA ya no está activa.") from error
        code = type(error).__name__[:100]
        if current_attempt.status in {"reserved", "running"}:
            current_attempt.status = "failed"
            current_attempt.error_code = code
            current_attempt.completed_at = completed
        # Roll up metrics from generate/reviewer attempts already persisted under this audit.
        # Without this, a writer that succeeds and a reviewer that fails left usage=0 and
        # provider stuck at the policy label (signal) even when Signal returned ollama.
        sibling_attempts = list(
            db.session.scalars(
                select(AIAttempt).where(
                    AIAttempt.audit_log_id == audit_id,
                    AIAttempt.tenant_id == tenant_id,
                )
            )
        )
        total_input = sum(item.input_tokens for item in sibling_attempts)
        total_output = sum(item.output_tokens for item in sibling_attempts)
        total_cost = sum(item.cost_micros for item in sibling_attempts)
        total_latency = sum(item.latency_ms or 0 for item in sibling_attempts)
        current_audit.status = "failed"
        current_audit.error_code = code
        current_audit.input_tokens = total_input
        current_audit.output_tokens = total_output
        current_audit.actual_cost_micros = total_cost
        if total_latency:
            current_audit.latency_ms = total_latency
        current_audit.attempt_count = max(
            current_audit.attempt_count, current_attempt.attempt_number
        )
        current_audit.completed_at = completed
        current_usage.input_tokens = total_input
        current_usage.output_tokens = total_output
        current_usage.actual_cost_micros = total_cost
        current_usage.reserved_cost_micros = 0
        current_usage.provider = current_audit.provider
        current_usage.model = current_audit.model
        current_usage.status = (
            "settled" if (total_input or total_output or total_cost) else "released"
        )
        db.session.commit()

    try:
        attempt.status = "running"
        db.session.commit()
        provider = provider_from_config(current_app.config)
        result = provider.generate_structured(request, prompt.schema)
        allowed_evidence = {item.id for item in context.evidence}
        # SV2-AUG: dual-memory allowlist lives in supplemental_context, not only
        # build_context oracle evidence rows.
        if agent == "dossier_question_answer" and supplemental_context:
            for raw_id in supplemental_context.get("allowed_evidence_ids") or []:
                try:
                    allowed_evidence.add(uuid.UUID(str(raw_id)))
                except (ValueError, TypeError, AttributeError):
                    continue
        # SV2-PERFIL-EVIDENCIA: primero separar declarado de oficial; si no, un
        # fact que cite UUID declared tumba validate_evidence (solo ORM oficial).
        output = result.output.model_dump(mode="json")
        if agent == "opportunity":
            declared_set: set[uuid.UUID] = set()
            for raw_id in context.manifest.get("declared_evidence_ids") or []:
                try:
                    declared_set.add(uuid.UUID(str(raw_id)))
                except (ValueError, TypeError, AttributeError):
                    continue
            output = validate_opportunity_origin_boundary(
                output,
                official_ids=allowed_evidence,
                declared_ids=declared_set,
            )
            boundary_model = prompt.schema.model_validate_json(json.dumps(output))
            validate_evidence(cast(AgentOutput, boundary_model), allowed_evidence)
            output = boundary_model.model_dump(mode="json")
        else:
            validate_evidence(cast(AgentOutput, result.output), allowed_evidence)
            output = result.output.model_dump(mode="json")
    except Exception as error:
        fail(error, active_attempt_id=attempt_id)
        raise
    # Preserve bilateral trust hash from Signal validated_output (MDEV-06).
    vo_hash = getattr(result, "validated_output_sha256", None)
    if vo_hash:
        output["validated_output_sha256"] = str(vo_hash)
    try:
        if agent == "dossier_completion_wizard":
            validate_dossier_completion_output(output, context)
        elif agent == "tender_search_wizard":
            output = postvalidate_tender_search_plan(
                output,
                enrich_cpvs=True,
                source_text=str(context.payload.get("description") or ""),
            )
    except Exception as error:
        fail(error, active_attempt_id=attempt_id)
        raise
    db.session.rollback()
    checkpoint = datetime.now(UTC)
    checked_attempt = db.session.scalar(
        select(AIAttempt)
        .where(
            AIAttempt.id == attempt_id,
            AIAttempt.tenant_id == tenant_id,
            AIAttempt.execution_token == execution_token,
            AIAttempt.status == "running",
            AIAttempt.lease_expires_at >= checkpoint,
        )
        .with_for_update()
    )
    checked_audit = db.session.scalar(
        select(AIAuditLog)
        .where(
            AIAuditLog.id == audit_id,
            AIAuditLog.tenant_id == tenant_id,
            AIAuditLog.status == "running",
        )
        .with_for_update()
    )
    checked_usage = db.session.scalar(
        select(AIUsageLedger)
        .where(
            AIUsageLedger.id == usage_id,
            AIUsageLedger.tenant_id == tenant_id,
            AIUsageLedger.execution_token == execution_token,
            AIUsageLedger.status == "reserved",
        )
        .with_for_update()
    )
    if checked_attempt is None or checked_audit is None or checked_usage is None:
        db.session.rollback()
        raise AIPolicyDenied("La lease de la ejecución IA expiró.")
    checked_attempt.status = "succeeded"
    checked_attempt.response_hash = hashlib.sha256(_canonical(output)).digest()
    checked_attempt.input_tokens = result.input_tokens
    checked_attempt.output_tokens = result.output_tokens
    checked_attempt.cost_micros = result.cost_micros
    checked_attempt.latency_ms = result.latency_ms
    checked_attempt.completed_at = checkpoint
    # Persist upstream provider/model as soon as generate succeeds so a later reviewer
    # failure still shows ollama vs signal (not only the tenant policy label).
    if result.provider:
        checked_audit.provider = result.provider
    if result.model:
        checked_audit.model = result.model
    total_input, total_output, total_cost = (
        result.input_tokens,
        result.output_tokens,
        result.cost_micros,
    )
    reviewer_attempt_id: uuid.UUID | None = None
    if prompt.requires_evidence_review and not result.safe_fallback_used:
        reviewer_prompt = PromptRegistry(current_app.config["AI_DEFAULT_MODEL"]).get(
            "evidence_reviewer"
        )
        reviewer_context = _reviewer_context(
            agent=agent,
            prompt=prompt,
            context=context,
            output=output,
        )
        reviewer_request = LLMRequest(
            "evidence_reviewer",
            reviewer_prompt.model,
            reviewer_prompt.text,
            reviewer_prompt.purpose,
            reviewer_context,
            _reviewer_output_budget(
                reviewer_prompt_tokens=reviewer_prompt.max_output_tokens,
                policy_tokens=policy.max_output_tokens,
                claim_count=len(reviewer_context["candidate_claims"]),
            ),
            context.classification,
        )
        reviewer_now = datetime.now(UTC)
        reviewer_attempt = AIAttempt(
            tenant_id=tenant_id,
            audit_log_id=audit_id,
            attempt_number=next_attempt_number + 1,
            kind="reviewer",
            status="running",
            request_hash=hashlib.sha256(_canonical(reviewer_request.context)).digest(),
            started_at=reviewer_now,
            execution_token=execution_token,
            lease_expires_at=reviewer_now + timedelta(seconds=lease_seconds),
        )
        db.session.add(reviewer_attempt)
        db.session.commit()
        reviewer_attempt_id = reviewer_attempt.id
        try:
            reviewer_result = provider.generate_structured(reviewer_request, EvidenceReviewerOutput)
            reviewer = cast(EvidenceReviewerOutput, reviewer_result.output)
            validate_evidence(reviewer, {item.id for item in context.evidence})
        except Exception as error:
            fail(error, active_attempt_id=reviewer_attempt_id)
            raise EvidenceReviewError(
                f"La revisión de evidencia falló después de generar el output: {error}"
            ) from error
        total_input += reviewer_result.input_tokens
        total_output += reviewer_result.output_tokens
        total_cost += reviewer_result.cost_micros
        reviewer_output = reviewer.model_dump(mode="json")
        db.session.rollback()
        reviewer_checkpoint = datetime.now(UTC)
        checked_reviewer = db.session.scalar(
            select(AIAttempt)
            .where(
                AIAttempt.id == reviewer_attempt_id,
                AIAttempt.tenant_id == tenant_id,
                AIAttempt.execution_token == execution_token,
                AIAttempt.status == "running",
                AIAttempt.lease_expires_at >= reviewer_checkpoint,
            )
            .with_for_update()
        )
        reviewer_audit = db.session.scalar(
            select(AIAuditLog)
            .where(
                AIAuditLog.id == audit_id,
                AIAuditLog.tenant_id == tenant_id,
                AIAuditLog.status == "running",
            )
            .with_for_update()
        )
        reviewer_usage = db.session.scalar(
            select(AIUsageLedger)
            .where(
                AIUsageLedger.id == usage_id,
                AIUsageLedger.tenant_id == tenant_id,
                AIUsageLedger.execution_token == execution_token,
                AIUsageLedger.status == "reserved",
            )
            .with_for_update()
        )
        if checked_reviewer is None or reviewer_audit is None or reviewer_usage is None:
            db.session.rollback()
            raise AIPolicyDenied("La lease del revisor IA expiró.")
        checked_reviewer.response_hash = hashlib.sha256(_canonical(reviewer_output)).digest()
        checked_reviewer.input_tokens = reviewer_result.input_tokens
        checked_reviewer.output_tokens = reviewer_result.output_tokens
        checked_reviewer.cost_micros = reviewer_result.cost_micros
        checked_reviewer.latency_ms = reviewer_result.latency_ms
        checked_reviewer.completed_at = reviewer_checkpoint
        if reviewer.verdict == "fail":
            if prompt.evidence_review_failure_policy == "strip_claims":
                try:
                    cleaned_output = _strip_reviewer_rejected_claims(
                        output,
                        reviewer,
                        lenient=(
                            agent
                            in {
                                "report_writer",
                                "opportunity",
                                "risk",
                                "actor_partnership",
                                "entity_resolution",
                            }
                        ),
                    )
                    cleaned_model = prompt.schema.model_validate_json(json.dumps(cleaned_output))
                    validate_evidence(
                        cast(AgentOutput, cleaned_model), {item.id for item in context.evidence}
                    )
                    output = cleaned_model.model_dump(mode="json")
                except Exception as error:
                    fail(error, active_attempt_id=reviewer_attempt_id)
                    raise
            else:
                rejection_error = ValueError("El revisor de evidencia rechazó el output.")
                fail(rejection_error, active_attempt_id=reviewer_attempt_id)
                raise rejection_error
        checked_reviewer.status = "succeeded"
    # Conclusiones (título/resumen/recomendación) deben responder de los facts citados.
    # Corre siempre — no solo cuando el revisor falla — porque el revisor puede pasar
    # claims bien citados y dejar un título inventado.
    if agent in _CONCLUSION_GROUNDING_AGENTS:
        output = _ground_conclusions_to_facts(output, agent=agent)
        try:
            grounded_model = prompt.schema.model_validate_json(json.dumps(output))
            validate_evidence(
                cast(AgentOutput, grounded_model), {item.id for item in context.evidence}
            )
            output = grounded_model.model_dump(mode="json")
        except Exception as error:
            fail(error, active_attempt_id=reviewer_attempt_id or attempt_id)
            raise
    if soft_budget_warning:
        output["warnings"] = [
            *output.get("warnings", []),
            "Presupuesto blando mensual alcanzado.",
        ]
    output_hash = hashlib.sha256(_canonical(output)).digest()
    settlement = datetime.now(UTC)
    active_attempt_id = reviewer_attempt_id or attempt_id
    active_attempt = db.session.scalar(
        select(AIAttempt)
        .where(
            AIAttempt.id == active_attempt_id,
            AIAttempt.tenant_id == tenant_id,
            AIAttempt.execution_token == execution_token,
            AIAttempt.status == "succeeded",
            AIAttempt.lease_expires_at >= settlement,
        )
        .with_for_update()
    )
    final_audit = db.session.scalar(
        select(AIAuditLog)
        .where(
            AIAuditLog.id == audit_id,
            AIAuditLog.tenant_id == tenant_id,
            AIAuditLog.status == "running",
        )
        .with_for_update()
    )
    settled_usage = db.session.scalar(
        select(AIUsageLedger)
        .where(
            AIUsageLedger.id == usage_id,
            AIUsageLedger.tenant_id == tenant_id,
            AIUsageLedger.execution_token == execution_token,
            AIUsageLedger.status == "reserved",
        )
        .with_for_update()
    )
    if active_attempt is None or final_audit is None or settled_usage is None:
        db.session.rollback()
        raise AIPolicyDenied("La ejecución IA perdió su fencing antes de persistir.")
    final_audit.status, final_audit.output_hash = "succeeded", output_hash
    final_audit.provider = result.provider or final_audit.provider
    final_audit.model = result.model or final_audit.model
    final_audit.attempt_count = max(final_audit.attempt_count, active_attempt.attempt_number)
    final_audit.input_tokens, final_audit.output_tokens = total_input, total_output
    final_audit.actual_cost_micros, final_audit.latency_ms = total_cost, result.latency_ms
    final_audit.completed_at = settlement
    artifact = AIArtifact(
        tenant_id=tenant_id,
        audit_log_id=final_audit.id,
        dossier_id=dossier_id,
        target_type=target_type,
        target_id=target_id or dossier_id,
        agent=agent,
        schema_name=prompt.output_schema_name,
        schema_version="v1",
        output=output,
        output_hash=output_hash,
        status="candidate",
        version=1,
    )
    db.session.add(artifact)
    settled_usage.provider = final_audit.provider
    settled_usage.model = final_audit.model
    settled_usage.input_tokens = total_input
    settled_usage.output_tokens = total_output
    settled_usage.actual_cost_micros = total_cost
    settled_usage.reserved_cost_micros = 0
    settled_usage.status = "settled"
    try:
        db.session.commit()
    except Exception as error:
        active_id = reviewer_attempt_id or attempt_id
        fail(error, active_attempt_id=active_id)
        raise
    return {
        "artifact_id": str(artifact.id),
        "audit_log_id": str(final_audit.id),
        "status": artifact.status,
    }


def _signal_extract(signal: Signal) -> str:
    """Build the smallest durable evidence record needed for a Signal triage."""

    text = "\n\n".join(part for part in (signal.title.strip(), signal.summary.strip()) if part)
    if not text:
        raise SignalTriageRejected("La señal no contiene contenido analizable.")
    return text[:12_000]


def _ensure_signal_evidence(*, link: DossierSignal, signal: Signal) -> Evidence:
    tenant_id = require_tenant_id()
    existing = db.session.scalar(
        select(Evidence)
        .join(
            EvidenceDossier,
            (EvidenceDossier.tenant_id == Evidence.tenant_id)
            & (EvidenceDossier.evidence_id == Evidence.id),
        )
        .where(
            Evidence.tenant_id == tenant_id,
            Evidence.signal_id == signal.id,
            EvidenceDossier.dossier_id == link.dossier_id,
        )
        .order_by(Evidence.created_at.desc())
    )
    if existing is not None:
        return existing
    extract = _signal_extract(signal)
    evidence = Evidence(
        tenant_id=tenant_id,
        signal_id=signal.id,
        source_kind="signal",
        source_url=signal.source_url,
        extract=extract,
        locator={
            "provider": signal.provider,
            "external_id": signal.external_id,
            "source_name": signal.source_name,
            "published_at": signal.published_at.isoformat() if signal.published_at else None,
        },
        checksum=hashlib.sha256(extract.encode()).digest(),
        classification="public",
        provenance={"created_by": "oracle.signal.triage", "signal_id": str(signal.id)},
    )
    db.session.add(evidence)
    db.session.flush()
    db.session.add(
        EvidenceDossier(
            tenant_id=tenant_id,
            evidence_id=evidence.id,
            dossier_id=link.dossier_id,
        )
    )
    db.session.commit()
    return evidence


def _triage_has_signal_evidence(output: SignalTriageOutput, evidence_id: uuid.UUID) -> bool:
    """Reject uncited claims while allowing a deliberately claim-free cautious triage."""

    if not output.facts and not output.inferences:
        return True
    return any(evidence_id in item.evidence_ids for item in output.facts) or any(
        evidence_id in item.evidence_ids for item in output.inferences
    )


def triage_dossier_signal(*, payload: dict[str, Any], job: BackgroundJob) -> dict[str, Any]:
    """Run the audited AI pipeline, then conservatively project a triage onto one link.

    Model recommendations never dismiss or promote a Signal. A concurrent human review wins and
    leaves the generated artifact available for inspection without overwriting that review.
    """

    tenant_id = require_tenant_id()
    try:
        signal_id = uuid.UUID(str(payload["resource_id"]))
    except (KeyError, TypeError, ValueError) as error:
        raise SignalTriageRejected("La señal del trabajo no es válida.") from error
    link = db.session.scalar(
        select(DossierSignal)
        .where(DossierSignal.tenant_id == tenant_id, DossierSignal.signal_id == signal_id)
        .order_by(DossierSignal.created_at.desc())
        .limit(1)
    )
    if link is None:
        raise SignalTriageRejected("La señal ya no está vinculada a un expediente.")
    requested_dossier = payload.get("dossier_id")
    if requested_dossier is not None and str(link.dossier_id) != str(requested_dossier):
        raise SignalTriageRejected("El expediente del trabajo no coincide con la señal.")
    signal = db.session.scalar(
        select(Signal).where(Signal.id == signal_id, Signal.tenant_id == tenant_id)
    )
    if signal is None:
        raise SignalTriageRejected("La señal ya no está disponible.")
    original_version = link.triage_version
    evidence = _ensure_signal_evidence(link=link, signal=signal)
    execution = execute_agent(
        agent="signal_triage",
        dossier_id=link.dossier_id,
        job=job,
        supplemental_context={
            "signal": {
                "id": str(signal.id),
                "title": signal.title,
                "source_type": signal.source_type,
                "source_url": signal.source_url,
                "evidence_id": str(evidence.id),
            }
        },
        target_type="dossier_signal",
        target_id=link.id,
    )
    artifact = db.session.scalar(
        select(AIArtifact).where(
            AIArtifact.id == uuid.UUID(execution["artifact_id"]),
            AIArtifact.tenant_id == tenant_id,
            AIArtifact.target_id == link.id,
            AIArtifact.agent == "signal_triage",
        )
    )
    if artifact is None:
        raise SignalTriageRejected("No se encontró el resultado auditable del triage.")
    output = SignalTriageOutput.model_validate_json(json.dumps(artifact.output))
    if not _triage_has_signal_evidence(output, evidence.id):
        artifact.status = "rejected"
        artifact.version += 1
        db.session.commit()
        raise SignalTriageRejected("El triage no cita evidencia suficiente de la señal.")
    current = db.session.scalar(
        select(DossierSignal)
        .where(DossierSignal.id == link.id, DossierSignal.tenant_id == tenant_id)
        .with_for_update()
    )
    if current is None:
        raise SignalTriageRejected("La vinculación de la señal ya no está disponible.")
    if current.status != "new" or current.triage_version != original_version:
        return execution | {"applied": False, "reason": "human_review_won"}
    scores = output.scores
    calculated = score_signal(
        {
            "relevance": scores.relevance,
            "novelty": scores.novelty,
            "strategic_impact": scores.strategic_impact,
            "source_credibility": scores.source_credibility,
            "confidence": scores.confidence,
        }
    )
    current.relevance = scores.relevance
    current.novelty = scores.novelty
    current.strategic_impact = scores.strategic_impact
    current.confidence = scores.confidence
    current.overall_score = calculated.score
    current.score_details = calculated.as_dict() | {
        "triage": {
            "artifact_id": str(artifact.id),
            "audit_log_id": execution["audit_log_id"],
            "category": output.category,
            "recommended_status": output.recommended_status,
            "model_overall": scores.overall,
            "evidence_ids": [str(evidence.id)],
            "warnings": output.warnings,
        }
    }
    current.why_it_matters = output.why_it_matters[:5000]
    current.recommended_action = output.recommended_next_action[:5000]
    current.triage_version += 1
    append_audit_event(
        db.session,
        action="signal.triaged",
        resource_type="dossier_signal",
        resource_id=current.id,
        dossier_id=current.dossier_id,
        result="success",
        correlation_id=job.correlation_id,
        metadata={"artifact_id": str(artifact.id), "evidence_id": str(evidence.id)},
    )
    db.session.commit()
    return execution | {
        "applied": True,
        "dossier_signal_id": str(current.id),
        "overall_score": current.overall_score,
        "evidence_id": str(evidence.id),
    }
