"""Async AI report for a Signal entity dossier before it is attached to a dossier."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from flask import current_app
from sqlalchemy import func, select, text

from opn_oracle.ai.models import AIArtifact, AIAttempt, AIUsageLedger
from opn_oracle.ai.provider import LLMRequest, provider_from_config
from opn_oracle.ai.registry import PromptRegistry
from opn_oracle.ai.schemas import ReportOutput
from opn_oracle.ai.service import AIPolicyDenied, _enforce_quota, _policy
from opn_oracle.extensions import db
from opn_oracle.integrations.entity_intel import (
    entity_intel_client_from_config,
    resolve_signal_external_tenant_id_for_tenant,
)
from opn_oracle.jobs.service import publish_job, serialize_job, stage_job
from opn_oracle.oracle.jobs import AIAuditLog, BackgroundJob
from opn_oracle.oracle.links import EvidenceDossier, ReportEvidence
from opn_oracle.oracle.models import Evidence, Report, StrategicDossier
from opn_oracle.oracle.policy import dossier_accessible
from opn_oracle.oracle.service import create_dossier_actor
from opn_oracle.platform.audit import append_audit_event
from opn_oracle.reporting.models import ReportRevision, ReportSnapshotEvidence
from opn_oracle.reporting.registry import ReportTemplateRegistry
from opn_oracle.reporting.service import (
    ReportWorkflowError,
    _authoritative_source_index,
    _render_revision_artifacts,
    _sha256,
)
from opn_oracle.tenants.context import require_tenant_id

ENTITY_DOSSIER_AGENT = "entity_dossier_intelligence"
ENTITY_DOSSIER_REPORT_JOB = "oracle.entity_dossier_report.generate"
ENTITY_DOSSIER_REPORT_TEMPLATE = "entity_intelligence"
ENTITY_DOSSIER_SCHEMA = "entity_dossier_intelligence_waiting/v1"
ENTITY_DOSSIER_PENDING_EVIDENCE_SCHEMA = "entity_dossier_pending_evidence/v1"


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")


def _text(value: Any) -> str:
    return str(value).strip() if value is not None else ""


def entity_key(*, name: str, kind: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "-", name.casefold()).strip("-")
    return f"{kind}:{normalized[:160]}"


def _items(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, dict):
        value = value.get("items")
    if not isinstance(value, list):
        return []
    return [dict(item) for item in value if isinstance(item, dict)]


def _section_data(payload: dict[str, Any], key: str) -> dict[str, Any] | None:
    sections = payload.get("sections")
    section = sections.get(key) if isinstance(sections, dict) else None
    if not isinstance(section, dict) or not section.get("ok"):
        return None
    data = section.get("data")
    return dict(data) if isinstance(data, dict) else None


def build_entity_dossier_metrics(payload: dict[str, Any]) -> dict[str, Any]:
    registry = _section_data(payload, "registry") or {}
    graph = _section_data(payload, "graph") or {}
    news = _section_data(payload, "news") or {}
    registry_items = _items(registry)
    raw_nodes = graph.get("nodes")
    raw_edges = graph.get("edges")
    graph_nodes = raw_nodes if isinstance(raw_nodes, list) else []
    graph_edges = raw_edges if isinstance(raw_edges, list) else []
    actions = Counter(_text(item.get("action")).casefold() or "sin_dato" for item in registry_items)
    provinces = sorted(
        {_text(item.get("province")) for item in registry_items if _text(item.get("province"))}
    )
    dated_edges = [
        edge
        for edge in graph_edges
        if isinstance(edge, dict) and (_text(edge.get("date")) or _text(edge.get("start_date")))
    ]
    return {
        "registry": {
            "acts": len(registry_items),
            "total": registry.get("total") or len(registry_items),
            "status": (registry.get("profile") or {}).get("status")
            if isinstance(registry.get("profile"), dict)
            else None,
            "first_publication_date": (registry.get("profile") or {}).get("first_act_date")
            if isinstance(registry.get("profile"), dict)
            else None,
            "last_publication_date": (registry.get("profile") or {}).get("last_act_date")
            if isinstance(registry.get("profile"), dict)
            else None,
            "actions": dict(actions),
            "provinces": provinces[:30],
        },
        "graph": {
            "nodes": len(graph_nodes),
            "edges": len(graph_edges),
            "dated_edges": len(dated_edges),
            "undated_edges": max(0, len(graph_edges) - len(dated_edges)),
            "truncated": bool(graph.get("truncated")),
        },
        "news": {"items": len(_items(news))},
    }


# Medido en producción sobre ITURRI SA (65 actos), con 16000 tokens de salida:
#   5 actos  -> informe completo, 2 hechos citados, 0 citas inventadas
#   25 actos -> informe completo y más rico (3 hechos, 17 inferencias), 0 inventadas
#   65 actos -> vuelve a truncar ("Invalid JSON: EOF", línea 585)
# El techo está entre 25 y 65, y depende de lo verboso que sea cada acto, así que se
# deja 25 con margen en vez de apurar el borde: un valor que apenas funciona con esta
# entidad fallaría con otra de actos más largos.
REGISTRY_ITEM_LIMIT = 25


def compact_entity_dossier(
    payload: dict[str, Any], *, registry_limit: int = REGISTRY_ITEM_LIMIT
) -> dict[str, Any]:
    """Recorta la ficha a lo que cabe en una llamada al modelo.

    `registry_limit` acota los actos BORME que ve el modelo. No es una optimización
    de coste: cada acto se convierte en una fuente citable que el modelo enumera en
    su índice de fuentes, así que el número de actos fija el suelo de longitud de la
    salida. Con las 65 actas de ITURRI el informe agotaba 16000 tokens enumerando
    fuentes y moría con "Invalid JSON: EOF" antes de cerrar el JSON.
    """

    entity = payload.get("entity") if isinstance(payload.get("entity"), dict) else {}
    registry = _section_data(payload, "registry") or {}
    graph = _section_data(payload, "graph") or {}
    news = _section_data(payload, "news") or {}
    return {
        "entity": entity,
        "registry": {
            "profile": registry.get("profile") if isinstance(registry.get("profile"), dict) else {},
            "total": registry.get("total"),
            "items": _items(registry)[:registry_limit],
            "truncated_by_oracle": len(_items(registry)) > registry_limit,
            "analyzed_acts": min(len(_items(registry)), registry_limit),
        },
        "graph": {
            "center": graph.get("center"),
            "nodes": [node for node in graph.get("nodes", [])[:400] if isinstance(node, dict)]
            if isinstance(graph.get("nodes"), list)
            else [],
            "edges": [edge for edge in graph.get("edges", [])[:600] if isinstance(edge, dict)]
            if isinstance(graph.get("edges"), list)
            else [],
            "truncated_by_signal": bool(graph.get("truncated")),
        },
        "news": {"items": _items(news)[:30], "truncated_by_oracle": len(_items(news)) > 30},
        "section_status": {
            key: {"ok": bool(value.get("ok")), "error": value.get("error")}
            for key, value in (payload.get("sections") or {}).items()
            if isinstance(value, dict)
        },
    }


def _first_text(item: dict[str, Any], *keys: str) -> str:
    for key in keys:
        value = _text(item.get(key))
        if value:
            return value
    return ""


def _pending_evidence_id(
    *, corpus_hash: str, source_kind: str, index: int, source_url: str, label: str
) -> uuid.UUID:
    return uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"opn-oracle:entity-intel:{corpus_hash}:{source_kind}:{index}:{source_url}:{label}",
    )


def _registry_extract(item: dict[str, Any]) -> str:
    parts = [
        f"Acto BORME: {_first_text(item, 'action', 'type') or 'sin acción normalizada'}.",
        f"Fecha de publicación: {_first_text(item, 'date', 'publication_date') or 'sin fecha'}.",
    ]
    company = _first_text(item, "company", "company_name", "entity")
    person = _first_text(item, "person", "person_name", "name")
    role = _first_text(item, "role", "position", "title")
    province = _first_text(item, "province")
    if company:
        parts.append(f"Sociedad: {company}.")
    if person:
        parts.append(f"Persona relacionada: {person}.")
    if role:
        parts.append(f"Cargo/rol: {role}.")
    if province:
        parts.append(f"Provincia: {province}.")
    return " ".join(parts)


def _news_extract(item: dict[str, Any]) -> str:
    title = _first_text(item, "title", "headline", "name") or "Noticia sin título"
    date = _first_text(item, "published_at", "publication_date", "date")
    source = _first_text(item, "source", "source_name", "publisher")
    summary = _first_text(item, "summary", "description", "snippet", "text")
    parts = [f"Noticia/mención externa: {title}."]
    if date:
        parts.append(f"Fecha indicada: {date}.")
    if source:
        parts.append(f"Fuente indicada: {source}.")
    if summary:
        parts.append(f"Resumen disponible: {summary}.")
    return " ".join(parts)


def build_pending_entity_evidence_sources(
    *,
    entity_dossier: dict[str, Any],
    corpus_hash: str,
) -> list[dict[str, Any]]:
    """Reserve stable Evidence IDs for citable entity-intel sources.

    The rows are deliberately not inserted here: the entity report lives in the
    waiting area until the user incorporates it into a dossier. These IDs let
    the LLM cite a closed set now, while real Evidence rows are materialized
    only if there is a dossier to attach them to.
    """

    pending: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()

    def add_source(
        *,
        source_kind: str,
        index: int,
        item: dict[str, Any],
        label: str,
        extract: str,
        source_url: str,
        locator: dict[str, Any],
    ) -> None:
        key = (source_kind, source_url, extract)
        if key in seen:
            return
        seen.add(key)
        evidence_id = _pending_evidence_id(
            corpus_hash=corpus_hash,
            source_kind=source_kind,
            index=index,
            source_url=source_url,
            label=label,
        )
        pending.append(
            {
                "id": str(evidence_id),
                "source_kind": source_kind,
                "label": label[:500],
                "source_url": source_url[:1500],
                "extract": extract[:20_000],
                "locator": locator,
                "checksum": hashlib.sha256(extract.encode("utf-8")).hexdigest(),
                "raw_item": item,
            }
        )

    registry = (
        entity_dossier.get("registry") if isinstance(entity_dossier.get("registry"), dict) else {}
    )
    for index, item in enumerate(_items(registry), start=1):
        source_url = _first_text(item, "source_url", "url", "link", "href")
        if not source_url:
            continue
        action = _first_text(item, "action", "type") or "acto"
        date = _first_text(item, "date", "publication_date") or "sin fecha"
        person = _first_text(item, "person", "person_name", "name")
        label_tail = f" · {person}" if person else ""
        add_source(
            source_kind="registry_act",
            index=index,
            item=item,
            label=f"BORME · {date} · {action}{label_tail}",
            extract=_registry_extract(item),
            source_url=source_url,
            locator={
                "kind": "signal_entity_registry_act",
                "publication_date": date,
                "action": action,
                "source_url": source_url,
                "ordinal": index,
            },
        )

    news = entity_dossier.get("news") if isinstance(entity_dossier.get("news"), dict) else {}
    for index, item in enumerate(_items(news), start=1):
        source_url = _first_text(item, "source_url", "url", "link", "href")
        if not source_url:
            continue
        title = _first_text(item, "title", "headline", "name") or "noticia"
        date = _first_text(item, "published_at", "publication_date", "date") or "sin fecha"
        add_source(
            source_kind="news",
            index=index,
            item=item,
            label=f"Noticia · {date} · {title}",
            extract=_news_extract(item),
            source_url=source_url,
            locator={
                "kind": "signal_entity_news",
                "publication_date": date,
                "title": title,
                "source_url": source_url,
                "ordinal": index,
            },
        )

    return pending


def source_limits(entity_dossier: dict[str, Any] | None = None) -> list[str]:
    """Límites de fuente que el modelo debe respetar y el informe debe declarar.

    Si Oracle ha recortado los actos registrales, el recorte se declara aquí: un
    informe que analiza 5 de 65 actos no puede presentarse como si los hubiera visto
    todos, ni concluir ausencia de nada a partir de lo que no se le pasó.
    """

    registry = (entity_dossier or {}).get("registry")
    limits: list[str] = []
    if isinstance(registry, dict) and registry.get("truncated_by_oracle"):
        analyzed = registry.get("analyzed_acts")
        total = registry.get("total")
        limits.append(
            f"Oracle solo ha pasado {analyzed} actos registrales de {total} al análisis: "
            "las conclusiones cubren ese subconjunto y no puede inferirse ausencia de "
            "hechos a partir de los actos no analizados."
        )
    return [
        *limits,
        (
            "Las fechas BORME son fechas de publicación, no necesariamente fechas "
            "registrales efectivas."
        ),
        "Los homónimos no están desambiguados automáticamente.",
        "El grafo de relaciones no incluye capital social ni porcentajes de participación.",
        "Las noticias pueden referirse a menciones no desambiguadas de la entidad consultada.",
        (
            "Los hechos factuales sin evidencia citable deben quedar formulados como "
            "límites o inferencias cautas."
        ),
    ]


def enqueue_entity_dossier_report(
    *,
    name: str,
    kind: str,
    idempotency_key: str,
    requested_by_user_id: uuid.UUID,
    correlation_id: str | None,
    request_id: str | None,
) -> BackgroundJob:
    cleaned_name = " ".join(name.strip().split())
    cleaned_kind = kind if kind in {"company", "person"} else "company"
    payload = {
        "name": cleaned_name,
        "kind": cleaned_kind,
        "entity_key": entity_key(name=cleaned_name, kind=cleaned_kind),
    }
    job = stage_job(
        ENTITY_DOSSIER_REPORT_JOB,
        payload=payload,
        idempotency_key=idempotency_key,
        requested_by_user_id=requested_by_user_id,
        dossier_id=None,
        resource_type="entity_intelligence_report",
        resource_id=None,
        correlation_id=correlation_id,
        request_id=request_id,
        max_attempts=3,
    )
    db.session.commit()
    if job.status == "queued":
        publish_job(job)
    return job


def _checkpoint(job: BackgroundJob, *, progress: int, stage: str) -> None:
    job.progress = progress
    job.stage = stage
    job.heartbeat_at = datetime.now(UTC)
    job.version += 1
    db.session.commit()


def process_entity_dossier_report(payload: dict[str, Any], job: BackgroundJob) -> dict[str, Any]:
    name = _text(payload.get("name"))
    kind = _text(payload.get("kind")) or "company"
    if not name or kind not in {"company", "person"}:
        raise ReportWorkflowError("La entidad solicitada no es válida.")
    _checkpoint(job, progress=15, stage="fetching_entity_dossier")
    client = entity_intel_client_from_config()
    try:
        external_tenant_id = resolve_signal_external_tenant_id_for_tenant(job.tenant_id)
        dossier_payload = client.dossier(
            name=name,
            kind=cast(Any, kind),
            external_tenant_id=external_tenant_id,
        )
    finally:
        client.close()
    metrics = build_entity_dossier_metrics(dossier_payload)
    compact = compact_entity_dossier(
        dossier_payload,
        registry_limit=int(current_app.config["ENTITY_INTEL_MAX_REGISTRY_ACTS"]),
    )
    corpus_hash = hashlib.sha256(_canonical(compact)).hexdigest()
    pending_evidence_sources = build_pending_entity_evidence_sources(
        entity_dossier=compact,
        corpus_hash=corpus_hash,
    )
    _checkpoint(job, progress=45, stage="entity_dossier_ready")
    output, audit = _run_waiting_area_agent(
        job=job,
        entity={"name": name, "type": kind, "key": payload.get("entity_key")},
        entity_dossier=compact,
        computed_metrics=metrics,
        corpus_hash=corpus_hash,
        pending_evidence_sources=pending_evidence_sources,
    )
    result = {
        "kind": "entity_dossier_intelligence_report",
        "entity": {"name": name, "type": kind, "key": payload.get("entity_key")},
        "output": output,
        "audit_log_id": str(audit.id),
        "provider": audit.provider,
        "model": audit.model,
        "prompt_name": audit.prompt_name,
        "prompt_version": audit.prompt_version,
        "generated_at": audit.completed_at.isoformat() if audit.completed_at else None,
        "corpus_hash": corpus_hash,
        "source_limits": source_limits(compact),
        "computed_metrics": metrics,
        "pending_evidence_schema": ENTITY_DOSSIER_PENDING_EVIDENCE_SCHEMA,
        "pending_evidence_sources": pending_evidence_sources,
        "incorporated_report_id": None,
        "incorporated_dossier_id": None,
    }
    append_audit_event(
        db.session,
        action="entity_dossier_report.generated",
        resource_type="background_job",
        resource_id=job.id,
        dossier_id=None,
        result="success",
        correlation_id=job.correlation_id,
        metadata={
            "agent": ENTITY_DOSSIER_AGENT,
            "audit_log_id": str(audit.id),
            "entity_key": payload.get("entity_key"),
            "corpus_sha256": corpus_hash,
            "pending_evidence_count": len(pending_evidence_sources),
        },
    )
    return result


def _run_waiting_area_agent(
    *,
    job: BackgroundJob,
    entity: dict[str, Any],
    entity_dossier: dict[str, Any],
    computed_metrics: dict[str, Any],
    corpus_hash: str,
    pending_evidence_sources: list[dict[str, Any]],
) -> tuple[dict[str, Any], AIAuditLog]:
    tenant_id = require_tenant_id()
    slot = f"{tenant_id}:{job.id}:{ENTITY_DOSSIER_AGENT}"
    db.session.execute(
        text("SELECT pg_advisory_xact_lock(hashtextextended(:slot, 0))"),
        {"slot": slot},
    )
    succeeded = db.session.scalar(
        select(AIAuditLog)
        .where(
            AIAuditLog.tenant_id == tenant_id,
            AIAuditLog.background_job_id == job.id,
            AIAuditLog.agent == ENTITY_DOSSIER_AGENT,
            AIAuditLog.status == "succeeded",
        )
        .order_by(AIAuditLog.started_at.desc(), AIAuditLog.created_at.desc())
    )
    if succeeded is not None and job.result_ref.get("output"):
        return cast(dict[str, Any], job.result_ref["output"]), succeeded
    active = db.session.scalar(
        select(AIAuditLog)
        .where(
            AIAuditLog.tenant_id == tenant_id,
            AIAuditLog.background_job_id == job.id,
            AIAuditLog.agent == ENTITY_DOSSIER_AGENT,
            AIAuditLog.status.in_(("pending", "running")),
        )
        .order_by(AIAuditLog.started_at.desc(), AIAuditLog.created_at.desc())
    )
    if active is not None:
        db.session.rollback()
        raise AIPolicyDenied("La ejecución IA de este job ya está en curso.")
    policy = _policy(tenant_id)
    reservation_micros = 2 * (policy.max_context_tokens + policy.max_output_tokens)
    soft_budget_warning = _enforce_quota(policy, tenant_id, reservation_micros)
    prompt = PromptRegistry(current_app.config["AI_DEFAULT_MODEL"]).get(ENTITY_DOSSIER_AGENT)
    allowed_evidence_ids = [str(item["id"]) for item in pending_evidence_sources]
    context = {
        "tenant_id": str(tenant_id),
        "entity": entity,
        "entity_dossier": entity_dossier,
        "citable_evidence": [
            {
                "evidence_id": item["id"],
                "label": item["label"],
                "source_kind": item["source_kind"],
                "source_url": item["source_url"],
                "extract": item["extract"],
                "locator": item["locator"],
            }
            for item in pending_evidence_sources
        ],
        "computed_metrics": computed_metrics,
        "source_limits": source_limits(entity_dossier),
        "corpus_hash": corpus_hash,
        "evidence_policy": {
            "materialization": (
                "Estos IDs están reservados para evidencia de espera y solo se materializan "
                "si el usuario incorpora el informe a un expediente."
            ),
            "citation_rule": (
                "Cita únicamente IDs presentes en allowed_evidence_ids. BORME/noticias con "
                "URL pueden respaldar hechos observables; homónimos y relaciones no "
                "desambiguadas deben permanecer como límites o inferencias."
            ),
        },
        "requested_scope": {
            "required_sections": ReportTemplateRegistry()
            .get(ENTITY_DOSSIER_REPORT_TEMPLATE)
            .sections,
            "arithmetic_policy": (
                "Los conteos y métricas proceden de Python. El modelo no debe recalcular, "
                "estimar ni completar valores ausentes."
            ),
        },
        "allowed_evidence_ids": allowed_evidence_ids,
    }
    input_hash = hashlib.sha256(_canonical(context)).digest()
    context_hash = hashlib.sha256(
        _canonical(
            {
                "schema": ENTITY_DOSSIER_SCHEMA,
                "corpus_hash": corpus_hash,
                "pending_evidence_schema": ENTITY_DOSSIER_PENDING_EVIDENCE_SCHEMA,
                "allowed_evidence_ids": allowed_evidence_ids,
            }
        )
    ).digest()
    now = datetime.now(UTC)
    execution_token = uuid.uuid4()
    lease_seconds = max(30, min(int(current_app.config["CELERY_TASK_TIME_LIMIT"]), 600))
    lease_expires_at = now + timedelta(seconds=lease_seconds)
    audit = db.session.scalar(
        select(AIAuditLog)
        .where(
            AIAuditLog.tenant_id == tenant_id,
            AIAuditLog.background_job_id == job.id,
            AIAuditLog.agent == ENTITY_DOSSIER_AGENT,
            AIAuditLog.status.in_(("failed", "denied")),
        )
        .order_by(AIAuditLog.started_at.desc(), AIAuditLog.created_at.desc())
        .with_for_update()
    )
    if audit is None:
        audit = AIAuditLog(
            tenant_id=tenant_id,
            dossier_id=None,
            background_job_id=job.id,
            requested_by_user_id=job.requested_by_user_id,
            use_case=ENTITY_DOSSIER_AGENT,
            agent=ENTITY_DOSSIER_AGENT,
            action="generate_waiting_entity_report",
            provider=policy.provider,
            model=prompt.model,
            prompt_name=prompt.name,
            prompt_version=prompt.version,
            prompt_hash=prompt.sha256,
            context_hash=context_hash,
            schema_name=prompt.output_schema_name,
            schema_version="v1",
            input_hash=input_hash,
            source_ids=allowed_evidence_ids,
            status="running",
            data_classification="internal",
            redaction_applied=False,
            redaction_summary={},
            estimated_cost_micros=reservation_micros,
            started_at=now,
        )
        db.session.add(audit)
    else:
        audit.dossier_id = None
        audit.requested_by_user_id = job.requested_by_user_id
        audit.provider = policy.provider
        audit.model = prompt.model
        audit.prompt_name = prompt.name
        audit.prompt_version = prompt.version
        audit.prompt_hash = prompt.sha256
        audit.context_hash = context_hash
        audit.schema_name = prompt.output_schema_name
        audit.schema_version = "v1"
        audit.input_hash = input_hash
        audit.output_hash = None
        audit.source_ids = allowed_evidence_ids
        audit.status = "running"
        audit.data_classification = "internal"
        audit.redaction_applied = False
        audit.redaction_summary = {}
        audit.input_tokens = audit.output_tokens = audit.actual_cost_micros = 0
        audit.latency_ms = None
        audit.estimated_cost_micros = reservation_micros
        audit.error_code = None
        audit.started_at = now
        audit.completed_at = None
    db.session.flush()
    attempt_number = (
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
        attempt_number=attempt_number,
        kind="generate",
        status="reserved",
        request_hash=input_hash,
        started_at=now,
        execution_token=execution_token,
        lease_expires_at=lease_expires_at,
    )
    db.session.add(attempt)
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
        usage.input_tokens = usage.output_tokens = 0
        usage.reserved_cost_micros = reservation_micros
        usage.actual_cost_micros = 0
        usage.status = "reserved"
        usage.execution_token = execution_token
    job.progress = 60
    job.stage = "ai_running"
    job.heartbeat_at = now
    job.version += 1
    db.session.commit()
    audit_id, attempt_id, usage_id = audit.id, attempt.id, usage.id

    request = LLMRequest(
        ENTITY_DOSSIER_AGENT,
        prompt.model,
        prompt.text,
        prompt.purpose,
        context,
        min(prompt.max_output_tokens, policy.max_output_tokens),
        "internal",
    )

    def fail(error: BaseException) -> None:
        db.session.rollback()
        completed = datetime.now(UTC)
        current_attempt = db.session.scalar(
            select(AIAttempt)
            .where(
                AIAttempt.id == attempt_id,
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
        if current_attempt is not None:
            current_attempt.status = "failed"
            current_attempt.error_code = type(error).__name__[:100]
            current_attempt.completed_at = completed
        if current_audit is not None:
            current_audit.status = "failed"
            current_audit.error_code = type(error).__name__[:100]
            current_audit.attempt_count = max(current_audit.attempt_count, attempt_number)
            current_audit.completed_at = completed
        if current_usage is not None:
            current_usage.status = "released"
            current_usage.reserved_cost_micros = 0
        db.session.commit()

    try:
        attempt.status = "running"
        db.session.commit()
        result = provider_from_config(current_app.config).generate_structured(
            request, prompt.schema
        )
    except Exception as error:
        fail(error)
        raise
    output = ReportOutput.model_validate(result.output).model_dump(mode="json")
    if soft_budget_warning:
        output["warnings"] = [
            *output.get("warnings", []),
            "Presupuesto blando mensual alcanzado.",
        ]
    output_hash = hashlib.sha256(_canonical(output)).digest()
    settlement = datetime.now(UTC)
    checked_attempt = db.session.scalar(
        select(AIAttempt)
        .where(
            AIAttempt.id == attempt_id,
            AIAttempt.tenant_id == tenant_id,
            AIAttempt.execution_token == execution_token,
            AIAttempt.status == "running",
        )
        .with_for_update()
    )
    checked_audit = db.session.scalar(
        select(AIAuditLog)
        .where(AIAuditLog.id == audit_id, AIAuditLog.tenant_id == tenant_id)
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
        raise AIPolicyDenied("La ejecución IA perdió su fencing antes de persistir.")
    checked_attempt.status = "succeeded"
    checked_attempt.response_hash = output_hash
    checked_attempt.input_tokens = result.input_tokens
    checked_attempt.output_tokens = result.output_tokens
    checked_attempt.cost_micros = result.cost_micros
    checked_attempt.latency_ms = result.latency_ms
    checked_attempt.completed_at = settlement
    checked_audit.status = "succeeded"
    checked_audit.output_hash = output_hash
    checked_audit.provider = result.provider or checked_audit.provider
    checked_audit.model = result.model or checked_audit.model
    checked_audit.input_tokens = result.input_tokens
    checked_audit.output_tokens = result.output_tokens
    checked_audit.actual_cost_micros = result.cost_micros
    checked_audit.latency_ms = result.latency_ms
    checked_audit.attempt_count = max(checked_audit.attempt_count, attempt_number)
    checked_audit.completed_at = settlement
    checked_usage.provider = checked_audit.provider
    checked_usage.model = checked_audit.model
    checked_usage.input_tokens = result.input_tokens
    checked_usage.output_tokens = result.output_tokens
    checked_usage.actual_cost_micros = result.cost_micros
    checked_usage.reserved_cost_micros = 0
    checked_usage.status = "settled"
    job.progress = 90
    job.stage = "ai_output_ready"
    job.heartbeat_at = settlement
    job.version += 1
    db.session.commit()
    return output, checked_audit


def _pending_evidence_sources_from_result(result: dict[str, Any]) -> list[dict[str, Any]]:
    raw_sources = result.get("pending_evidence_sources")
    if not isinstance(raw_sources, list):
        return []
    sources: list[dict[str, Any]] = []
    for raw in raw_sources:
        if not isinstance(raw, dict):
            continue
        try:
            uuid.UUID(str(raw.get("id")))
        except (TypeError, ValueError):
            continue
        extract = _text(raw.get("extract"))
        source_url = _text(raw.get("source_url"))
        label = _text(raw.get("label"))
        raw_locator = raw.get("locator")
        locator: dict[str, Any] = dict(raw_locator) if isinstance(raw_locator, dict) else {}
        if not extract or not source_url or not label:
            continue
        sources.append(
            {
                "id": str(raw["id"]),
                "source_kind": _text(raw.get("source_kind")) or "entity_intel",
                "label": label[:500],
                "source_url": source_url[:1500],
                "extract": extract[:20_000],
                "locator": dict(locator),
                "checksum": _text(raw.get("checksum")),
            }
        )
    return sources


def _materialize_pending_entity_evidence(
    *,
    report: Report,
    result: dict[str, Any],
    entity: dict[str, Any],
    job: BackgroundJob,
    audit: AIAuditLog,
) -> list[ReportSnapshotEvidence]:
    tenant_id = report.tenant_id
    pending_sources = _pending_evidence_sources_from_result(result)
    snapshot_rows: list[ReportSnapshotEvidence] = []
    evidence_metadata: list[dict[str, Any]] = []
    for source in pending_sources:
        evidence_id = uuid.UUID(source["id"])
        extract = source["extract"]
        checksum_hex = source["checksum"]
        try:
            checksum = bytes.fromhex(checksum_hex) if len(checksum_hex) == 64 else b""
        except ValueError:
            checksum = b""
        if not checksum:
            checksum = hashlib.sha256(extract.encode("utf-8")).digest()
        evidence = db.session.scalar(
            select(Evidence).where(Evidence.id == evidence_id, Evidence.tenant_id == tenant_id)
        )
        if evidence is None:
            evidence = Evidence(
                id=evidence_id,
                tenant_id=tenant_id,
                source_kind="entity_intel",
                source_url=source["source_url"],
                extract=extract,
                locator=source["locator"],
                checksum=checksum,
                classification="internal",
                provenance={
                    "source_kind": "entity_intel",
                    "entity_intel_source_kind": source["source_kind"],
                    "entity_name": _text(entity.get("name")),
                    "entity_kind": _text(entity.get("type")),
                    "job_id": str(job.id),
                    "audit_log_id": str(audit.id),
                    "schema": ENTITY_DOSSIER_PENDING_EVIDENCE_SCHEMA,
                    "materialized_at": datetime.now(UTC).isoformat(),
                },
            )
            db.session.add(evidence)
            db.session.flush()
        link = db.session.scalar(
            select(EvidenceDossier).where(
                EvidenceDossier.tenant_id == tenant_id,
                EvidenceDossier.evidence_id == evidence.id,
                EvidenceDossier.dossier_id == report.dossier_id,
            )
        )
        if link is None:
            db.session.add(
                EvidenceDossier(
                    tenant_id=tenant_id,
                    evidence_id=evidence.id,
                    dossier_id=report.dossier_id,
                )
            )
            db.session.flush()
        frozen = {
            "extract": evidence.extract,
            "locator": evidence.locator,
            "classification": evidence.classification,
            "source_label": source["label"],
        }
        snapshot_row = ReportSnapshotEvidence(
            tenant_id=tenant_id,
            report_id=report.id,
            evidence_id=evidence.id,
            dossier_id=report.dossier_id,
            evidence_hash=evidence.checksum,
            extract=evidence.extract,
            locator=evidence.locator,
            classification=evidence.classification,
            source_label=source["label"],
        )
        db.session.add(snapshot_row)
        db.session.add(
            ReportEvidence(tenant_id=tenant_id, report_id=report.id, evidence_id=evidence.id)
        )
        snapshot_rows.append(snapshot_row)
        evidence_metadata.append(
            {
                "id": str(evidence.id),
                "version": evidence.version,
                "checksum": evidence.checksum.hex(),
                "classification": evidence.classification,
                "locator": evidence.locator,
                "source_label": source["label"],
                "snapshot_row_hash": _sha256(frozen).hex(),
            }
        )
    if evidence_metadata:
        source_snapshot = dict(report.source_snapshot)
        source_snapshot["evidence"] = evidence_metadata
        source_snapshot["pending_evidence_schema"] = ENTITY_DOSSIER_PENDING_EVIDENCE_SCHEMA
        report.source_snapshot = source_snapshot
        report.source_snapshot_hash = _sha256(source_snapshot)
    return snapshot_rows


def incorporate_entity_dossier_report(
    *, job_id: uuid.UUID, dossier_id: uuid.UUID, actor_id: uuid.UUID
) -> tuple[Report, BackgroundJob]:
    tenant_id = require_tenant_id()
    job = db.session.scalar(
        select(BackgroundJob)
        .where(
            BackgroundJob.id == job_id,
            BackgroundJob.tenant_id == tenant_id,
            BackgroundJob.job_type == ENTITY_DOSSIER_REPORT_JOB,
        )
        .with_for_update()
    )
    if job is None or job.status != "succeeded":
        raise ReportWorkflowError("El informe de entidad todavía no está listo.")
    existing_report_id = job.result_ref.get("incorporated_report_id")
    if isinstance(existing_report_id, str):
        existing = db.session.scalar(
            select(Report).where(
                Report.id == uuid.UUID(existing_report_id), Report.tenant_id == tenant_id
            )
        )
        if existing is not None:
            return existing, job
    result = dict(job.result_ref)
    output_payload = result.get("output")
    if not isinstance(output_payload, dict):
        raise ReportWorkflowError("El job no conserva una salida de informe válida.")
    output = ReportOutput.model_validate(output_payload)
    dossier = db.session.scalar(
        select(StrategicDossier).where(
            StrategicDossier.id == dossier_id,
            StrategicDossier.tenant_id == tenant_id,
        )
    )
    if dossier is None or not dossier_accessible(db.session(), dossier, actor_id, write=True):
        raise ReportWorkflowError("No puedes incorporar el informe en ese expediente.")
    if dossier.status == "archived":
        raise ReportWorkflowError("Un expediente archivado es de solo lectura.")
    raw_entity = result.get("entity")
    entity: dict[str, Any] = dict(raw_entity) if isinstance(raw_entity, dict) else {}
    entity_name = _text(entity.get("name")) or "Entidad Signal"
    entity_kind = _text(entity.get("type")) or "company"
    create_dossier_actor(
        db.session(),
        dossier_id,
        {
            "actor_type": "person" if entity_kind == "person" else "organization",
            "canonical_name": entity_name,
            "roles": ["Entidad analizada por IA"],
            "tags": ["signal", "entity-intel", "entity-report"],
            "provenance": {
                "source": "signal_entity_intel",
                "source_kind": "entity_dossier_report",
                "entity_kind": entity_kind,
                "source_name": entity_name,
                "job_id": str(job.id),
                "audit_log_id": str(result.get("audit_log_id") or ""),
            },
            "relationship_strength": 30,
            "relevance_to_dossier": 40,
            "recent_activity": 20,
            "influence": 0,
            "accessibility": 0,
            "strategic_alignment": 0,
        },
        actor_id=actor_id,
    )
    job = db.session.scalar(
        select(BackgroundJob)
        .where(BackgroundJob.id == job_id, BackgroundJob.tenant_id == tenant_id)
        .with_for_update()
    )
    if job is None:
        raise ReportWorkflowError("El job desapareció durante la incorporación.")
    result = dict(job.result_ref)
    audit_id = uuid.UUID(str(result["audit_log_id"]))
    audit = db.session.scalar(
        select(AIAuditLog).where(AIAuditLog.id == audit_id, AIAuditLog.tenant_id == tenant_id)
    )
    if audit is None or audit.agent != ENTITY_DOSSIER_AGENT:
        raise ReportWorkflowError("La auditoría IA del informe no está disponible.")
    existing_artifact = db.session.scalar(
        select(AIArtifact).where(
            AIArtifact.tenant_id == tenant_id,
            AIArtifact.audit_log_id == audit.id,
        )
    )
    if existing_artifact is not None and existing_artifact.target_id is not None:
        existing = db.session.scalar(
            select(Report).where(
                Report.id == existing_artifact.target_id,
                Report.tenant_id == tenant_id,
            )
        )
        if existing is not None:
            result["incorporated_report_id"] = str(existing.id)
            result["incorporated_dossier_id"] = str(existing.dossier_id)
            job.result_ref = result
            job.version += 1
            db.session.commit()
            return existing, job
    template = ReportTemplateRegistry().get(ENTITY_DOSSIER_REPORT_TEMPLATE)
    generation_version = (
        db.session.scalar(
            select(func.max(Report.generation_version)).where(
                Report.tenant_id == tenant_id,
                Report.dossier_id == dossier_id,
                Report.template_key == ENTITY_DOSSIER_REPORT_TEMPLATE,
            )
        )
        or 0
    ) + 1
    now = datetime.now(UTC)
    snapshot = {
        "template": template.public_dict(),
        "entity": result.get("entity"),
        "computed_metrics": result.get("computed_metrics"),
        "source_limits": result.get("source_limits"),
        "corpus_hash": result.get("corpus_hash"),
        "audit_log_id": str(audit.id),
        "background_job_id": str(job.id),
        "waiting_area_schema": ENTITY_DOSSIER_SCHEMA,
        "pending_evidence_schema": result.get("pending_evidence_schema"),
        "pending_evidence_count": len(_pending_evidence_sources_from_result(result)),
    }
    report = Report(
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        report_type=template.report_type,
        template_key=template.key,
        template_version=template.version,
        generation_version=generation_version,
        idempotency_key=f"entity-report-incorporate:{job.id}:{dossier_id}",
        request_hash=_sha256({"job_id": str(job.id), "dossier_id": str(dossier_id)}),
        options={"entity_name": entity_name, "entity_kind": entity_kind},
        source_snapshot=snapshot,
        source_snapshot_hash=_sha256(snapshot),
        classification="internal",
        confidentiality_label="Uso interno",
        requested_by_user_id=actor_id,
        generated_by_user_id=job.requested_by_user_id,
        background_job_id=job.id,
        title=output.title[:300],
        content=output.model_dump(mode="json"),
        status="ready",
        ready_at=now,
    )
    db.session.add(report)
    db.session.flush()
    snapshot_rows = _materialize_pending_entity_evidence(
        report=report,
        result=result,
        entity=entity,
        job=job,
        audit=audit,
    )
    if snapshot_rows:
        output = _authoritative_source_index(output, snapshot_rows)
        report.title = output.title[:300]
        report.content = output.model_dump(mode="json")
        report.source_snapshot_hash = _sha256(report.source_snapshot)
    artifact = AIArtifact(
        tenant_id=tenant_id,
        audit_log_id=audit.id,
        dossier_id=dossier_id,
        target_type="report",
        target_id=report.id,
        agent=ENTITY_DOSSIER_AGENT,
        schema_name=audit.schema_name,
        schema_version=audit.schema_version,
        output=report.content,
        output_hash=_sha256(report.content),
        status="candidate",
        version=1,
    )
    db.session.add(artifact)
    db.session.flush()
    report.ai_artifact_id = artifact.id
    revision = ReportRevision(
        tenant_id=tenant_id,
        report_id=report.id,
        revision_no=1,
        status="ready",
        title=report.title,
        content=report.content,
        content_hash=_sha256(report.content),
        created_by_user_id=actor_id,
        change_summary="Incorporación inicial desde informe IA de entidad.",
    )
    db.session.add(revision)
    db.session.flush()
    artifacts = _render_revision_artifacts(report, revision)
    audit.dossier_id = dossier_id
    result["incorporated_report_id"] = str(report.id)
    result["incorporated_dossier_id"] = str(dossier_id)
    result["incorporated_at"] = now.isoformat()
    result["materialized_evidence_ids"] = [str(item.evidence_id) for item in snapshot_rows]
    job.result_ref = result
    job.resource_id = report.id
    job.version += 1
    append_audit_event(
        db.session,
        action="entity_dossier_report.incorporated",
        resource_type="report",
        resource_id=report.id,
        dossier_id=dossier_id,
        result="success",
        correlation_id=job.correlation_id,
        metadata={
            "job_id": str(job.id),
            "audit_log_id": str(audit.id),
            "artifact_ids": [str(item.id) for item in artifacts],
            "materialized_evidence_count": len(snapshot_rows),
        },
    )
    db.session.commit()
    return report, job


def serialize_entity_report_job(job: BackgroundJob) -> dict[str, Any]:
    payload = serialize_job(job)
    payload["entity"] = job.input_payload.get("name")
    payload["entity_key"] = job.input_payload.get("entity_key")
    return payload
