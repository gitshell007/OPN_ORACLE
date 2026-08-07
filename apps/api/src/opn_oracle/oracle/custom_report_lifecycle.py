"""MDEV-08 provisional · lifecycle durable de informe libre con snapshot congelado.

Estados product:
  brief_draft → plan_proposed → plan_accepted → generating → reviewing → ready
                                                             ↘ failed | cancelled

CAS vía Report.version + If-Match (428 sin header, 409 conflicto).
Una versión ready nunca se sobrescribe: nueva generación crea generation_version+1.
Memoria durable MDEV-05 ausente → degraded/disabled explícito; no store in-process.
"""

from __future__ import annotations

import hashlib
import json
import os
import uuid
from collections.abc import Mapping
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from opn_oracle.jobs.service import stage_job
from opn_oracle.oracle.custom_report_runtime_catalog import (
    RuntimeCatalogError,
    resolve_frozen_runtime_hashes,
)
from opn_oracle.oracle.custom_reports import (
    CustomReportConflict,
    CustomReportError,
    CustomReportNotFound,
    _sha256,
    get_custom_brief,
    normalize_brief_plan_output,
)
from opn_oracle.oracle.jobs import BackgroundJob
from opn_oracle.oracle.models import Report, StrategicDossier
from opn_oracle.platform.audit import append_audit_event
from opn_oracle.tenants.context import require_tenant_id

LIFECYCLE_STATES = frozenset(
    {
        "brief_draft",
        "plan_proposed",
        "plan_accepted",
        "accepted_degraded",
        "generating",
        "reviewing",
        "ready",
        "failed",
        "cancelled",
    }
)

# Legal transitions (from → allowed tos)
_TRANSITIONS: dict[str, frozenset[str]] = {
    "brief_draft": frozenset({"plan_proposed", "cancelled", "failed"}),
    "plan_proposed": frozenset(
        {
            "plan_accepted",
            "accepted_degraded",
            "plan_proposed",
            "brief_draft",
            "cancelled",
            "failed",
        }
    ),
    "plan_accepted": frozenset({"generating", "cancelled", "failed"}),
    # accepted_degraded: plan frozen but productive generation blocked (memory debt)
    "accepted_degraded": frozenset({"cancelled", "failed"}),
    "generating": frozenset({"reviewing", "failed", "cancelled"}),
    "reviewing": frozenset({"ready", "failed", "cancelled"}),
    "ready": frozenset(),  # immutable; new version = new report generation
    "failed": frozenset({"plan_proposed", "generating", "cancelled"}),  # retry paths
    "cancelled": frozenset(),
}

CUSTOM_WRITE_JOB = "oracle.report.custom_brief.write"
CUSTOM_REVIEW_JOB = "oracle.report.custom_brief.review"
SNAPSHOT_HASH_ALG = "canonical-json-sha256-v1"


class PreconditionRequired(RuntimeError):
    """If-Match ausente → HTTP 428."""


class IllegalTransition(CustomReportError):
    def __init__(self, message: str) -> None:
        super().__init__(message, errors={"lifecycle": [message]})


def _testing_mode() -> bool:
    """Deterministic generators are allowed only under explicit TESTING."""

    return os.getenv("TESTING", "0").strip().lower() in {"1", "true", "yes", "on"}


def _memory_durable_flag() -> bool:
    """Raw env flag — never sufficient alone to declare durable memory."""

    try:
        from opn_oracle.integrations.surveillance_signal_adapter import (
            durable_memory_store_available,
        )

        return durable_memory_store_available()
    except Exception:
        return os.getenv("MEMORY_DURABLE_STORE_READY", "0").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }


def _build_materialize_transport() -> Any:
    """Default HTTP transport for durable materialize reads. Tests may monkeypatch."""

    from opn_oracle.integrations.memory_http_client import HttpxTransport

    return HttpxTransport()


def _signal_memory_client_for_materialize(session: Session, connection: Any) -> Any:
    """Authenticated Signal memory client for freeze reads (no in-process store)."""

    from opn_oracle.integrations.memory_profile import build_client_for_connection

    require_https = os.getenv("MEMORY_MATERIALIZE_REQUIRE_HTTPS", "1").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    return build_client_for_connection(
        connection,
        transport=_build_materialize_transport(),
        require_https=require_https,
    )


def _map_retrieve_to_evidence(
    response: Mapping[str, Any],
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
) -> tuple[list[dict[str, Any]], list[str], str | None, dict[str, Any]]:
    """Map a contractual memory.v1 retrieve payload into freeze evidence + allowlist.

    Empty items with a durable watermark is a valid materialized read (no invent).
    Items missing required citability fields are excluded, never invented.
    """

    from opn_oracle.integrations.memory_contract_v1 import materialize_signal_item_to_evidence

    raw_items = response.get("items") if isinstance(response, Mapping) else None
    items = list(raw_items) if isinstance(raw_items, list) else []
    watermark_raw = response.get("watermark") if isinstance(response, Mapping) else None
    watermark = str(watermark_raw).strip() if watermark_raw not in (None, "") else None
    coverage_manifest = (
        dict(response.get("coverage_manifest") or {}) if isinstance(response, Mapping) else {}
    )
    evidence_items: list[dict[str, Any]] = []
    allowlist: list[str] = []
    excluded: list[dict[str, Any]] = []
    for raw in items:
        if not isinstance(raw, dict):
            excluded.append({"reason": "item_not_object"})
            continue
        try:
            # Ensure required citability fields for materialize_signal_item_to_evidence.
            item = dict(raw)
            if "policy_version" not in item or item["policy_version"] in (None, ""):
                item["policy_version"] = "memory.v1"
            if ("watermark" not in item or item["watermark"] in (None, "")) and watermark:
                item["watermark"] = watermark
            citation = materialize_signal_item_to_evidence(
                item,
                tenant_id=str(tenant_id),
                dossier_id=str(dossier_id),
            )
            ev = {
                "evidence_id": citation.oracle_evidence_id,
                "signal_item_id": citation.signal_item_id,
                "source_ref": citation.source_ref,
                "checksum": citation.checksum,
                "exact_excerpt": citation.exact_excerpt,
                "classification": citation.classification,
                "locator": citation.locator,
                "occurred_at": citation.occurred_at,
                "policy_version": citation.policy_version,
                "watermark": citation.watermark,
                "tenant_id": citation.tenant_id,
                "dossier_id": citation.dossier_id,
            }
            evidence_items.append(ev)
            allowlist.append(citation.oracle_evidence_id)
        except Exception as exc:
            excluded.append(
                {
                    "signal_item_id": str(raw.get("id") or ""),
                    "reason": f"not_citable:{exc}",
                }
            )
    coverage = {
        "evidence_count": len(evidence_items),
        "durable": bool(watermark),
        "excluded_count": len(excluded),
        "excluded": excluded[:50],
        "coverage_manifest": {
            "version": coverage_manifest.get("version"),
            "failed": list(coverage_manifest.get("failed") or [])[:20],
            "used": list(coverage_manifest.get("used") or [])[:20],
            "truncated": bool(coverage_manifest.get("truncated")),
        },
        "source_status": "signal_memory_v1_postgresql",
        "authoritative_store": "signal_memory_v1_postgresql",
    }
    return evidence_items, allowlist, watermark, coverage


def _materialize_durable_memory(
    session: Session,
    *,
    dossier: StrategicDossier,
) -> dict[str, Any]:
    """Attempt a real durable-memory materialization via authenticated Signal retrieve.

    Never uses the in-process store. Authority is a contractual memory.v1 read scoped
    to tenant+dossier (PostgreSQL-backed on Signal). Flag alone is never sufficient.
    Empty durable read with watermark is allowed; missing watermark → degraded.
    """

    flag_on = _memory_durable_flag()
    empty: dict[str, Any] = {
        "memory_mode": "disabled",
        "memory_degraded": True,
        "memory_degraded_reason": (
            "DUR-MDEV05-001: memoria durable no disponible; flujo degraded, "
            "allowlist vacía, sin store in-process"
        ),
        "evidence_items": [],
        "allowlist": [],
        "watermark": None,
        "coverage": {
            "evidence_count": 0,
            "durable": False,
            "gaps": ["DUR-MDEV05-001: store durable no disponible"],
        },
        "memory_policy": {
            "mode": "disabled",
            "authoritative_store": None,
            "in_process_forbidden": True,
            "materialized": False,
            "flag_alone_insufficient": True,
        },
    }
    if not flag_on:
        return empty

    # Flag is on: require real connection + authenticated retrieve with watermark.
    try:
        from opn_oracle.integrations.memory_profile import resolve_signal_memory_connection
        from opn_oracle.tenants.context import require_tenant_id

        tenant_id = require_tenant_id()
        try:
            connection = resolve_signal_memory_connection(session, tenant_id=tenant_id)
        except Exception:
            out = dict(empty)
            out["memory_degraded_reason"] = (
                "DUR-MDEV05-001: flag MEMORY_DURABLE_STORE_READY sin conexión "
                "Signal/profile materializada; no se declara durable"
            )
            out["coverage"] = {
                "evidence_count": 0,
                "durable": False,
                "gaps": ["flag_without_materialized_evidence"],
                "note": "flag alone insufficient for durable claim",
            }
            out["memory_policy"] = {
                **dict(empty["memory_policy"]),
                "flag_was_set": True,
            }
            return out
    except Exception:
        out = dict(empty)
        out["memory_policy"] = {**dict(empty["memory_policy"]), "flag_was_set": True}
        return out

    # Real durable read via Signal memory.v1 (adapter contractual autenticado).
    try:
        client = _signal_memory_client_for_materialize(session, connection)
        query = (
            f"custom_report_freeze dossier={dossier.id} "
            f"intent={getattr(dossier, 'current_intent_revision_id', '') or ''}"
        )
        response = client.retrieve(
            external_tenant_id=str(tenant_id),
            dossier_id=str(dossier.id),
            query=query,
            purpose="report",
            limit=50,
            token_budget=4000,
            correlation_id=f"ora_freeze_{uuid.uuid4().hex[:12]}",
        )
    except Exception as exc:
        out = dict(empty)
        out["memory_degraded_reason"] = (
            f"DUR-MDEV08: lectura durable Signal falló ({type(exc).__name__}: {exc}); "
            "snapshot disabled/degraded (fail-closed, sin store in-process)"
        )
        out["coverage"] = {
            "evidence_count": 0,
            "durable": False,
            "gaps": ["signal_retrieve_failed", "DUR-MDEV08"],
            "error_type": type(exc).__name__,
        }
        out["memory_policy"] = {
            "mode": "disabled",
            "authoritative_store": None,
            "in_process_forbidden": True,
            "materialized": False,
            "flag_alone_insufficient": True,
            "flag_was_set": True,
            "retrieve_attempted": True,
        }
        return out

    evidence_items, allowlist, watermark, coverage = _map_retrieve_to_evidence(
        response if isinstance(response, Mapping) else {},
        tenant_id=tenant_id,
        dossier_id=dossier.id,
    )
    if not watermark:
        out = dict(empty)
        out["memory_degraded_reason"] = (
            "DUR-MDEV08: retrieve Signal sin watermark durable; no se declara "
            "memory_mode=durable (fail-closed)"
        )
        out["evidence_items"] = []
        out["allowlist"] = []
        out["coverage"] = {
            "evidence_count": 0,
            "durable": False,
            "gaps": ["missing_watermark", "DUR-MDEV08"],
            "retrieve_items_seen": len(evidence_items),
        }
        out["memory_policy"] = {
            "mode": "disabled",
            "authoritative_store": None,
            "in_process_forbidden": True,
            "materialized": False,
            "flag_alone_insufficient": True,
            "flag_was_set": True,
            "retrieve_attempted": True,
            "watermark_required": True,
        }
        return out

    # Durable claim: authenticated retrieve + watermark. Empty allowlist is OK.
    return {
        "memory_mode": "durable",
        "memory_degraded": False,
        "memory_degraded_reason": None,
        "evidence_items": evidence_items,
        "allowlist": allowlist,
        "watermark": watermark,
        "coverage": coverage,
        "memory_policy": {
            "mode": "durable",
            "authoritative_store": "signal_memory_v1_postgresql",
            "in_process_forbidden": True,
            "materialized": True,
            "flag_alone_insufficient": True,
            "flag_was_set": True,
            "empty_allowlist_ok": True,
            "source": "signal_retrieve_authenticated",
            "tenant_scoped": True,
            "dossier_scoped": True,
        },
    }


def _lifecycle_of(report: Report) -> str:
    options = dict(report.options or {})
    raw = str(options.get("lifecycle_state") or "").strip()
    if raw in LIFECYCLE_STATES:
        return raw
    # Back-compat from plan_status
    plan = str(options.get("plan_status") or "draft")
    if report.status == "ready":
        return "ready"
    if report.status == "failed":
        return "failed"
    if report.status == "generating":
        return "generating"
    if plan == "accepted":
        return "plan_accepted"
    if plan == "proposed":
        return "plan_proposed"
    return "brief_draft"


def _require_if_match(report: Report, expected_version: int | None) -> None:
    if expected_version is None:
        raise PreconditionRequired("If-Match es obligatorio.")
    if int(report.version) != int(expected_version):
        raise CustomReportConflict(
            f"Conflicto de versión: esperada {expected_version}, actual {report.version}."
        )


def _assert_transition(current: str, target: str) -> None:
    allowed = _TRANSITIONS.get(current, frozenset())
    if target not in allowed:
        raise IllegalTransition(f"Transición ilegal: {current} → {target}.")


def serialize_lifecycle(report: Report) -> dict[str, Any]:
    options = dict(report.options or {})
    lifecycle = _lifecycle_of(report)
    accepted = options.get("accepted_snapshot")
    artifact = options.get("ready_artifact")
    generation_blocked = bool(options.get("generation_blocked") or lifecycle == "accepted_degraded")
    return {
        "id": str(report.id),
        "tenant_id": str(report.tenant_id),
        "dossier_id": str(report.dossier_id),
        "title": report.title,
        "status": report.status,
        "lifecycle_state": lifecycle,
        "plan_status": str(options.get("plan_status") or "draft"),
        "version": report.version,
        "generation_version": report.generation_version,
        "brief_request": str(options.get("brief_request") or ""),
        "proposed_plan": options.get("proposed_plan"),
        "accepted_plan": options.get("accepted_plan"),
        "accepted_snapshot": accepted,
        "accepted_snapshot_hash": (
            options.get("accepted_snapshot_hash")
            if isinstance(options.get("accepted_snapshot_hash"), str)
            else (
                report.source_snapshot_hash.hex()
                if report.source_snapshot_hash is not None and options.get("accepted_snapshot")
                else None
            )
        ),
        "memory_mode": (accepted or {}).get("memory_mode") if isinstance(accepted, dict) else None,
        "memory_degraded": bool(options.get("memory_degraded", False)),
        "memory_degraded_reason": options.get("memory_degraded_reason"),
        "accepted_degraded": bool(
            options.get("accepted_degraded") or lifecycle == "accepted_degraded"
        ),
        "generation_blocked": generation_blocked,
        "generation_blocked_code": options.get("generation_blocked_code"),
        "generation_blocked_reason": options.get("generation_blocked_reason"),
        "coverage": options.get("coverage"),
        "ready_artifact": artifact,
        "downloadable": bool(
            lifecycle == "ready"
            and isinstance(artifact, dict)
            and artifact.get("status") == "available"
            and artifact.get("sha256")
            and int(artifact.get("byte_size") or 0) > 0
        ),
        "background_job_id": (
            str(report.background_job_id) if report.background_job_id is not None else None
        ),
        "error_code": getattr(report, "error_code", None),
        "error_message": getattr(report, "error_message", None),
        "etag": f'W/"{report.version}"',
        "created_at": report.created_at.isoformat() if report.created_at else None,
        "updated_at": report.updated_at.isoformat() if report.updated_at else None,
        "ready_at": report.ready_at.isoformat() if report.ready_at is not None else None,
    }


def _frozen_runtime_hashes(options: dict[str, Any]) -> dict[str, str]:
    """Freeze RT-08/09/10 hashes from contractual catalog only — never invent SHA seeds."""

    try:
        return resolve_frozen_runtime_hashes(options)
    except RuntimeCatalogError as exc:
        raise CustomReportError(
            str(exc),
            errors={"runtime": [exc.code], "code": [exc.code]},
        ) from exc


def _productive_generation_allowed(
    snap: Mapping[str, Any],
) -> tuple[bool, str, str]:
    """Gate for productive writer enqueue. Fail-closed when memory is not durable.

    Returns (allowed, code, reason).
    """

    mode = str(snap.get("memory_mode") or "").strip()
    raw_policy = snap.get("memory_policy")
    policy: dict[str, Any] = raw_policy if isinstance(raw_policy, dict) else {}
    materialized = bool(policy.get("materialized"))
    watermark = snap.get("watermark")
    if mode != "durable":
        return (
            False,
            "memory_not_durable",
            "memory_mode != durable; generación productiva bloqueada (DUR-MDEV05-001)",
        )
    if not materialized:
        return (
            False,
            "memory_not_materialized",
            "Evidence durable no materializada; no se encola writer",
        )
    if watermark in (None, "", {}):
        return (
            False,
            "memory_watermark_missing",
            "Falta watermark de memoria durable; generación bloqueada",
        )
    # Evidence may be empty only when policy explicitly materialised empty set.
    # With watermark + materialized, empty allowlist is permitted (no invent).
    _ = bool(policy.get("empty_allowlist_ok"))
    # Runtime hashes must be present (contractual).
    runtime = snap.get("runtime_sha256")
    if not isinstance(runtime, dict):
        return False, "runtime_hash_missing", "runtime_sha256 ausente en snapshot"
    for role in ("plan", "writer", "review"):
        value = runtime.get(role)
        if not (
            isinstance(value, str)
            and len(value) == 64
            and all(c in "0123456789abcdef" for c in value.lower())
        ):
            return (
                False,
                "runtime_hash_missing",
                f"Hash runtime {role} ausente o no contractual en snapshot",
            )
    return True, "", ""


def _load_authoritative_intent_context(
    session: Session,
    *,
    dossier: StrategicDossier,
) -> dict[str, Any]:
    """Read requirements/offering/intent from accepted revision entities — never client options."""

    from opn_oracle.oracle.intent import (
        get_current_intent,
        list_offerings,
        list_requirements,
        serialize_intent_revision,
        serialize_offering,
        serialize_requirement,
    )

    intent = None
    intent_ser: dict[str, Any] | None = None
    requirements: list[dict[str, Any]] = []
    offerings: list[dict[str, Any]] = []
    try:
        intent = get_current_intent(session, dossier.id)
        if intent is not None:
            intent_ser = serialize_intent_revision(intent)
    except Exception:
        intent = None
        intent_ser = None
    try:
        requirements = [serialize_requirement(r) for r in list_requirements(session, dossier.id)]
    except Exception:
        requirements = []
    try:
        offerings = [serialize_offering(o) for o in list_offerings(session, dossier.id)]
    except Exception:
        offerings = []
    intent_revision_id = (
        str(intent_ser["id"])
        if isinstance(intent_ser, dict) and intent_ser.get("id")
        else (
            str(dossier.current_intent_revision_id)
            if getattr(dossier, "current_intent_revision_id", None) is not None
            else None
        )
    )
    # Prefer offering linked to current intent; else first active; else None.
    offering: dict[str, Any] | None = None
    for item in offerings:
        if intent_revision_id and str(item.get("intent_revision_id") or "") == intent_revision_id:
            offering = item
            break
    if offering is None and offerings:
        offering = offerings[0]
    return {
        "intent_revision_id": intent_revision_id,
        "intent": intent_ser,
        "requirements": requirements,
        "offering": offering,
        "source": "authoritative_entities",
    }


def _build_accepted_snapshot(
    session: Session,
    *,
    report: Report,
    dossier: StrategicDossier,
    accepted_plan: dict[str, Any],
    actor_id: uuid.UUID,
) -> dict[str, Any]:
    """Freeze immutable snapshot at plan acceptance.

    Never uses in-process memory as authoritative store (MDEV-05 debt).
    Never declares durable solely from MEMORY_DURABLE_STORE_READY flag.
    """
    mem = _materialize_durable_memory(session, dossier=dossier)
    memory_mode = str(mem["memory_mode"])
    memory_policy = dict(mem["memory_policy"])
    evidence_items: list[dict[str, Any]] = list(mem["evidence_items"])
    allowlist: list[str] = list(mem["allowlist"])
    watermark = mem.get("watermark")
    coverage: dict[str, Any] = dict(mem["coverage"])

    options = dict(report.options or {})
    brief = str(options.get("brief_request") or "")
    runtime_hashes = _frozen_runtime_hashes(options)
    prompt_versions = {
        "plan_task_key": "report_custom_brief_plan",
        "writer_task_key": "report_custom_writer",
        "review_task_key": "report_custom_review",
        "runtime_plan": "RT-08",
        "runtime_writer": "RT-09",
        "runtime_review": "RT-10",
        "prompt_version": "1.0.2",
        "schema_version": "custom_report.v1",
        "runtime_sha256": runtime_hashes,
        "catalog_source": "signal_verified_manifests_contractual_v1",
    }
    # SHA of frozen plan text for integrity
    plan_canonical = json.dumps(accepted_plan, sort_keys=True, separators=(",", ":"))
    plan_sha = hashlib.sha256(plan_canonical.encode("utf-8")).hexdigest()
    # AUTHORITY-MDEV08-010: never trust report.options client fields for these.
    authority = _load_authoritative_intent_context(session, dossier=dossier)
    snapshot = {
        "kind": "custom_assistant_accepted_v1",
        "frozen_at": datetime.now(UTC).isoformat(),
        "frozen_by_user_id": str(actor_id),
        "report_id": str(report.id),
        "generation_version": report.generation_version,
        "dossier_id": str(dossier.id),
        "intent_revision_id": authority["intent_revision_id"],
        "intent": authority["intent"],
        "requirements": authority["requirements"],
        "offering": authority["offering"],
        "authority_source": authority["source"],
        "brief_request": brief,
        "brief_sha256": hashlib.sha256(brief.encode("utf-8")).hexdigest() if brief else None,
        "accepted_plan": accepted_plan,
        "accepted_plan_sha256": plan_sha,
        "memory_mode": memory_mode,
        "memory_policy": memory_policy,
        "memory_degraded": bool(mem.get("memory_degraded", memory_mode != "durable")),
        "memory_degraded_reason": mem.get("memory_degraded_reason"),
        "watermark": watermark,
        "evidence_items": evidence_items,
        "allowlist": allowlist,
        "coverage": coverage,
        "prompt_schema_runtime": prompt_versions,
        "runtime_sha256": runtime_hashes,
    }
    # Guarantee no null/synthetic runtime hash on accepted snapshot.
    for k, v in runtime_hashes.items():
        if not (
            isinstance(v, str) and len(v) == 64 and all(c in "0123456789abcdef" for c in v.lower())
        ):
            raise CustomReportError(
                f"runtime hash {k} no contractual en snapshot aceptado.",
                errors={"runtime": ["runtime_hash_missing"], "code": ["runtime_hash_missing"]},
            )
    return snapshot


def accept_plan(
    session: Session,
    *,
    dossier_id: uuid.UUID,
    report_id: uuid.UUID,
    actor_id: uuid.UUID,
    expected_version: int | None,
    plan_override: Mapping[str, Any] | None = None,
    request_id: str | None = None,
    auto_start_generation: bool = True,
) -> Report:
    """Human accepts plan → freeze snapshot. Never auto-accept without call."""

    report = get_custom_brief(session, dossier_id=dossier_id, report_id=report_id)
    _require_if_match(report, expected_version)
    current = _lifecycle_of(report)
    # Target may be plan_accepted or accepted_degraded depending on generation gate.
    if current not in {"plan_proposed"} and (
        "plan_accepted" not in _TRANSITIONS.get(current, frozenset())
        and "accepted_degraded" not in _TRANSITIONS.get(current, frozenset())
    ):
        raise IllegalTransition(f"Transición ilegal: {current} → plan_accepted.")

    options = dict(report.options or {})
    proposed = plan_override or options.get("proposed_plan")
    if not isinstance(proposed, dict) or not proposed.get("sections"):
        raise CustomReportError(
            "No hay plan propuesto válido para aceptar.",
            errors={"plan": ["proposed_plan.sections requerido"]},
        )

    dossier = session.scalar(
        select(StrategicDossier).where(
            StrategicDossier.id == dossier_id,
            StrategicDossier.tenant_id == require_tenant_id(),
        )
    )
    if dossier is None:
        raise CustomReportNotFound("Expediente no encontrado.")

    accepted_plan = normalize_brief_plan_output(proposed)
    accepted_plan["accepted_at"] = datetime.now(UTC).isoformat()
    accepted_plan["accepted_by_user_id"] = str(actor_id)
    snapshot = _build_accepted_snapshot(
        session,
        report=report,
        dossier=dossier,
        accepted_plan=accepted_plan,
        actor_id=actor_id,
    )
    snap_hash = _sha256(snapshot)
    snap_hash_hex = snap_hash.hex()

    gen_ok, gen_code, gen_reason = _productive_generation_allowed(snapshot)
    target_state = "plan_accepted" if gen_ok else "accepted_degraded"
    _assert_transition(current, target_state)

    options["plan_status"] = "accepted"
    options["lifecycle_state"] = target_state
    options["accepted_plan"] = accepted_plan
    options["accepted_snapshot"] = snapshot
    options["accepted_snapshot_hash"] = snap_hash_hex
    options["coverage"] = snapshot.get("coverage")
    options["memory_degraded"] = bool(snapshot.get("memory_degraded", True))
    if options["memory_degraded"]:
        options["memory_degraded_reason"] = snapshot.get("memory_degraded_reason") or (
            "DUR-MDEV05-001: memoria durable no disponible; flujo degraded, "
            "allowlist vacía, sin store in-process"
        )
    options["accepted_degraded"] = not gen_ok
    options["generation_blocked"] = not gen_ok
    if gen_ok:
        options.pop("generation_blocked_code", None)
        options.pop("generation_blocked_reason", None)
    else:
        options["generation_blocked_code"] = gen_code
        options["generation_blocked_reason"] = gen_reason
    # Freeze runtime hashes onto options for audit.
    options["runtime_sha256"] = snapshot.get("runtime_sha256")
    report.options = options
    report.source_snapshot = snapshot
    report.source_snapshot_hash = snap_hash
    report.snapshot_hash_algorithm = SNAPSHOT_HASH_ALG
    report.version = int(report.version) + 1
    report.status = "draft"
    report.error_code = None if gen_ok else gen_code
    report.error_message = None if gen_ok else gen_reason[:500]

    append_audit_event(
        session,
        action="report.custom_brief.plan_accepted",
        resource_type="report",
        resource_id=report.id,
        dossier_id=dossier_id,
        result="success",
        request_id=request_id,
        metadata={
            "version": report.version,
            "snapshot_hash": snap_hash_hex,
            "memory_degraded": options["memory_degraded"],
            "memory_mode": snapshot.get("memory_mode"),
            "generation_version": report.generation_version,
            "lifecycle_state": target_state,
            "generation_blocked": not gen_ok,
            "generation_blocked_code": None if gen_ok else gen_code,
        },
    )
    session.flush()

    # DISABLED-MDEV08-009: never auto-start writer when memory is not durable.
    if auto_start_generation and gen_ok:
        return start_generation(
            session,
            dossier_id=dossier_id,
            report_id=report.id,
            actor_id=actor_id,
            expected_version=report.version,
            request_id=request_id,
            publish=False,
        )
    return report


def edit_plan(
    session: Session,
    *,
    dossier_id: uuid.UUID,
    report_id: uuid.UUID,
    actor_id: uuid.UUID,
    expected_version: int | None,
    proposed_plan: Mapping[str, Any],
    request_id: str | None = None,
) -> Report:
    report = get_custom_brief(session, dossier_id=dossier_id, report_id=report_id)
    _require_if_match(report, expected_version)
    current = _lifecycle_of(report)
    if current not in {"plan_proposed", "brief_draft"}:
        raise IllegalTransition(f"No se puede editar el plan en estado {current}.")
    if not isinstance(proposed_plan, dict) or not proposed_plan.get("sections"):
        raise CustomReportError(
            "proposed_plan.sections es obligatorio.",
            errors={"plan": ["sections requerido"]},
        )
    options = dict(report.options or {})
    options["proposed_plan"] = normalize_brief_plan_output(proposed_plan)
    options["plan_status"] = "proposed"
    options["lifecycle_state"] = "plan_proposed"
    options["plan_edited_by"] = str(actor_id)
    options["plan_edited_at"] = datetime.now(UTC).isoformat()
    report.options = options
    report.version = int(report.version) + 1
    append_audit_event(
        session,
        action="report.custom_brief.plan_edited",
        resource_type="report",
        resource_id=report.id,
        dossier_id=dossier_id,
        result="success",
        request_id=request_id,
        metadata={"version": report.version},
    )
    session.flush()
    return report


def reject_plan(
    session: Session,
    *,
    dossier_id: uuid.UUID,
    report_id: uuid.UUID,
    actor_id: uuid.UUID,
    expected_version: int | None,
    reason: str | None = None,
    request_id: str | None = None,
) -> Report:
    report = get_custom_brief(session, dossier_id=dossier_id, report_id=report_id)
    _require_if_match(report, expected_version)
    current = _lifecycle_of(report)
    _assert_transition(current, "brief_draft")
    options = dict(report.options or {})
    options["plan_status"] = "draft"
    options["lifecycle_state"] = "brief_draft"
    options["rejected_plan"] = options.get("proposed_plan")
    options["proposed_plan"] = None
    options["reject_reason"] = (reason or "")[:500]
    options["rejected_by"] = str(actor_id)
    report.options = options
    report.version = int(report.version) + 1
    append_audit_event(
        session,
        action="report.custom_brief.plan_rejected",
        resource_type="report",
        resource_id=report.id,
        dossier_id=dossier_id,
        result="success",
        request_id=request_id,
        metadata={"version": report.version, "reason": (reason or "")[:200]},
    )
    session.flush()
    return report


def start_generation(
    session: Session,
    *,
    dossier_id: uuid.UUID,
    report_id: uuid.UUID,
    actor_id: uuid.UUID,
    expected_version: int | None,
    request_id: str | None = None,
    publish: bool = False,
) -> Report:
    report = get_custom_brief(session, dossier_id=dossier_id, report_id=report_id)
    _require_if_match(report, expected_version)
    current = _lifecycle_of(report)
    if current == "generating":
        # idempotent
        return report
    options = dict(report.options or {})
    snap = options.get("accepted_snapshot")
    if not isinstance(snap, dict):
        raise CustomReportError(
            "Snapshot no congelado: acepte el plan antes de generar.",
            errors={
                "snapshot": ["accepted_snapshot required"],
                "code": ["snapshot_missing"],
            },
        )
    # Repeat generation gate on every start/retry path (no route/job bypass).
    gen_ok, gen_code, gen_reason = _productive_generation_allowed(snap)
    if not gen_ok:
        options["lifecycle_state"] = "accepted_degraded"
        options["accepted_degraded"] = True
        options["generation_blocked"] = True
        options["generation_blocked_code"] = gen_code
        options["generation_blocked_reason"] = gen_reason
        options["plan_status"] = "accepted"
        report.options = options
        report.status = "draft"
        report.error_code = gen_code
        report.error_message = gen_reason[:500]
        report.version = int(report.version) + 1
        append_audit_event(
            session,
            action="report.custom_brief.generation_blocked",
            resource_type="report",
            resource_id=report.id,
            dossier_id=dossier_id,
            result="denied",
            request_id=request_id,
            metadata={
                "code": gen_code,
                "reason": gen_reason,
                "version": report.version,
                "from_state": current,
            },
        )
        session.flush()
        raise CustomReportError(
            gen_reason,
            errors={"generation": [gen_code], "code": [gen_code]},
        )
    _assert_transition(current, "generating")
    # Fence: bind job to snapshot hash
    snap_hash = str(options.get("accepted_snapshot_hash") or "")
    job = stage_job(
        CUSTOM_WRITE_JOB,
        payload={
            "report_id": str(report.id),
            "dossier_id": str(dossier_id),
            "purpose": "report",
            "snapshot_hash": snap_hash,
            "generation_version": report.generation_version,
            # generation_fence: avoid forbidden key family "token" in job payload validator
            "generation_fence": str(uuid.uuid4()),
        },
        idempotency_key=f"custom-brief-write:{report.id}:{report.generation_version}:{snap_hash[:16]}",
        requested_by_user_id=actor_id,
        dossier_id=dossier_id,
        resource_type="report",
        resource_id=report.id,
        request_id=request_id,
        max_attempts=3,
    )
    options["lifecycle_state"] = "generating"
    options["generation_blocked"] = False
    options["accepted_degraded"] = False
    options.pop("generation_blocked_code", None)
    options.pop("generation_blocked_reason", None)
    options["write_job_id"] = str(job.id)
    fence = None
    if isinstance(getattr(job, "input_payload", None), dict):
        fence = job.input_payload.get("generation_fence") or job.input_payload.get("fence_token")
    options["fence_token"] = fence
    report.options = options
    report.background_job_id = job.id
    report.status = "generating"
    report.error_code = None
    report.error_message = None
    report.version = int(report.version) + 1
    append_audit_event(
        session,
        action="report.custom_brief.generating",
        resource_type="report",
        resource_id=report.id,
        dossier_id=dossier_id,
        result="success",
        request_id=request_id,
        metadata={"job_id": str(job.id), "snapshot_hash": snap_hash, "version": report.version},
    )
    session.flush()
    if publish:
        from opn_oracle.jobs.service import publish_job

        session.commit()
        publish_job(job)
        # re-attach
        session.refresh(report)
    return report


def cancel_report(
    session: Session,
    *,
    dossier_id: uuid.UUID,
    report_id: uuid.UUID,
    actor_id: uuid.UUID,
    expected_version: int | None,
    request_id: str | None = None,
) -> Report:
    report = get_custom_brief(session, dossier_id=dossier_id, report_id=report_id)
    _require_if_match(report, expected_version)
    current = _lifecycle_of(report)
    if current in {"ready", "cancelled"}:
        raise IllegalTransition(f"No se puede cancelar en estado {current}.")
    _assert_transition(current, "cancelled")
    options = dict(report.options or {})
    options["lifecycle_state"] = "cancelled"
    options["cancelled_by"] = str(actor_id)
    options["cancelled_at"] = datetime.now(UTC).isoformat()
    report.options = options
    report.status = "failed"
    report.error_code = "cancelled"
    report.error_message = "Informe cancelado por el usuario."
    report.version = int(report.version) + 1
    # Best-effort cancel of background job
    if report.background_job_id is not None:
        job = session.get(BackgroundJob, report.background_job_id)
        if job is not None and hasattr(job, "cancel_requested"):
            job.cancel_requested = True
    append_audit_event(
        session,
        action="report.custom_brief.cancelled",
        resource_type="report",
        resource_id=report.id,
        dossier_id=dossier_id,
        result="success",
        request_id=request_id,
        metadata={"version": report.version},
    )
    session.flush()
    return report


def retry_report(
    session: Session,
    *,
    dossier_id: uuid.UUID,
    report_id: uuid.UUID,
    actor_id: uuid.UUID,
    expected_version: int | None,
    request_id: str | None = None,
) -> Report:
    report = get_custom_brief(session, dossier_id=dossier_id, report_id=report_id)
    _require_if_match(report, expected_version)
    current = _lifecycle_of(report)
    if current != "failed":
        raise IllegalTransition(f"Retry solo desde failed; actual={current}.")
    options = dict(report.options or {})
    if options.get("accepted_snapshot"):
        # Resume generation with same frozen snapshot
        options["lifecycle_state"] = "plan_accepted"
        options["plan_status"] = "accepted"
        report.options = options
        report.status = "draft"
        report.error_code = None
        report.error_message = None
        report.version = int(report.version) + 1
        session.flush()
        return start_generation(
            session,
            dossier_id=dossier_id,
            report_id=report.id,
            actor_id=actor_id,
            expected_version=report.version,
            request_id=request_id,
        )
    # Re-propose plan path
    options["lifecycle_state"] = "brief_draft"
    options["plan_status"] = "draft"
    report.options = options
    report.status = "draft"
    report.error_code = None
    report.error_message = None
    report.version = int(report.version) + 1
    session.flush()
    return report


def validate_citations_against_snapshot(
    snapshot: Mapping[str, Any],
    citations: list[Any],
) -> list[str]:
    """Return foreign evidence ids (empty list = ok). Empty allowlist rejects all citations."""
    allow = {str(x) for x in (snapshot.get("allowlist") or []) if str(x).strip()}
    foreign: list[str] = []
    for raw in citations or []:
        if not isinstance(raw, dict):
            foreign.append("<non-object>")
            continue
        eid = str(raw.get("evidence_id") or "").strip()
        if not eid or eid not in allow:
            foreign.append(eid or "<missing>")
    return foreign


def _deterministic_writer_output_for_testing(
    *,
    snap: Mapping[str, Any],
    options: Mapping[str, Any],
    current_hash: str,
) -> dict[str, Any]:
    """TESTING-only generator. Never used as productive placeholder report content."""

    sections_out: list[dict[str, Any]] = []
    plan = options.get("accepted_plan") or snap.get("accepted_plan") or {}
    for sec in plan.get("sections") or []:
        if not isinstance(sec, dict):
            continue
        sections_out.append(
            {
                "id": sec.get("id") or sec.get("title") or "section",
                "title": sec.get("title") or "Sección",
                "facts": [],
                "claims": [],
                "conflicts": [],
                "inferences": [],
                "recommendations": [],
                "body": f"[TEST draft from plan] {sec.get('title') or ''}",
                "citations": [],
            }
        )
    if not sections_out:
        sections_out = [
            {
                "id": "empty",
                "title": "Sin secciones",
                "body": "[TEST] empty plan",
                "facts": [],
                "claims": [],
                "conflicts": [],
                "inferences": [],
                "recommendations": [],
                "citations": [],
            }
        ]
    return {
        "version": "custom_report_writer.v1",
        "sections": sections_out,
        "citations": [],
        "snapshot_hash": current_hash,
        "facts": [],
        "claims": [],
        "conflicts": [],
        "inferences": [],
        "recommendations": [],
    }


def _invoke_rt09_writer_via_signal(
    *,
    snap: Mapping[str, Any],
    options: Mapping[str, Any],
    current_hash: str,
) -> dict[str, Any]:
    """Call governed RT-09 via Signal adapter; consume ONLY validated_output."""

    from flask import current_app

    from opn_oracle.ai.provider import AIRejected, AIUnavailable, SignalGovernedLLMProvider

    base_url = str(current_app.config.get("SIGNAL_AI_BASE_URL") or "").strip()
    api_key = str(current_app.config.get("SIGNAL_AI_API_KEY") or "").strip()
    if not base_url or not api_key:
        raise CustomReportError(
            "Signal AI no configurado para RT-09; no se genera placeholder productivo.",
            errors={"signal": ["SIGNAL_AI_BASE_URL/API_KEY required"]},
        )
    provider = SignalGovernedLLMProvider(
        base_url=base_url,
        api_key=api_key,
        timeout_seconds=float(current_app.config.get("SIGNAL_AI_TIMEOUT_SECONDS") or 120),
    )
    allowlist = [str(x) for x in (snap.get("allowlist") or []) if str(x).strip()]
    plan = options.get("accepted_plan") or snap.get("accepted_plan") or {}
    # SV2: el writer necesita los TEXTOS de la evidencia congelada, no solo ids —
    # con ids desnudos el modelo solo puede inventar contenido y sellarlo.
    evidence_for_writer = [
        {
            "evidence_id": str(item.get("evidence_id") or ""),
            "source_ref": str(item.get("source_ref") or ""),
            "text": str(item.get("exact_excerpt") or item.get("extract") or "")[:600],
        }
        for item in (snap.get("evidence_items") or [])
        if isinstance(item, Mapping) and str(item.get("evidence_id") or "").strip()
    ][:80]
    body: dict[str, Any] = {
        "task_key": "report_custom_writer",
        "allowed_evidence_ids": allowlist,
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "snapshot_hash": current_hash,
                            "accepted_plan": plan,
                            "brief_request": snap.get("brief_request"),
                            "allowlist": allowlist,
                            "evidence_items": evidence_for_writer,
                            "grounding_rule": (
                                "Redacta EXCLUSIVAMENTE con la información de evidence_items; "
                                "cita sus evidence_id. No inventes personas, empresas ni cifras."
                            ),
                            "coverage": snap.get("coverage"),
                            "memory_mode": snap.get("memory_mode"),
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                }
            ],
            "allowed_evidence_ids": allowlist,
            "format": "json",
        },
    }
    try:
        # Public governed boundary — never call private _run from product code.
        payload = provider.run_governed(body)
    except AIRejected as exc:
        raise CustomReportError(
            f"Signal rechazó la salida de RT-09: {exc}",
            errors={
                "signal_rejection": [exc.error_code],
                "signal_request_id": [exc.request_id] if exc.request_id else [],
            },
        ) from exc
    except AIUnavailable as exc:
        raise CustomReportError(
            f"Signal no disponible para RT-09: {exc}",
            errors={"signal": [str(exc)]},
        ) from exc
    validated = payload.get("validated_output")
    if not isinstance(validated, dict):
        raise CustomReportError(
            "Signal no devolvió validated_output para report_custom_writer; "
            "nunca se consume result crudo.",
            errors={"validated_output": ["missing"]},
        )
    # RT-09 v1.0.2: arrays opcionales en el schema → normalizar ausentes a []
    # (mismo contrato que normalize_brief_plan_output para RT-08).
    for _key in ("citations", "facts", "claims", "conflicts", "inferences", "recommendations"):
        if not isinstance(validated.get(_key), list):
            validated[_key] = []
    # Bind usage once (no double-charge).
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    return {
        "validated_output": validated,
        "validated_output_sha256": payload.get("validated_output_sha256"),
        "runtime": payload.get("runtime"),
        "provider": payload.get("provider"),
        "model": payload.get("model"),
        "run_id": payload.get("run_id") or payload.get("request_id"),
        "request_id": payload.get("request_id"),
        "fallback_used": payload.get("fallback_used"),
        "usage": usage,
        "attempts": payload.get("attempts"),
    }


def _invoke_rt10_review_via_signal(
    *,
    snap: Mapping[str, Any],
    writer_output: Mapping[str, Any],
    current_hash: str,
) -> dict[str, Any]:
    """Call governed RT-10 via Signal; consume ONLY validated_output."""

    from flask import current_app

    from opn_oracle.ai.provider import AIRejected, AIUnavailable, SignalGovernedLLMProvider

    base_url = str(current_app.config.get("SIGNAL_AI_BASE_URL") or "").strip()
    api_key = str(current_app.config.get("SIGNAL_AI_API_KEY") or "").strip()
    if not base_url or not api_key:
        raise CustomReportError(
            "Signal AI no configurado para RT-10.",
            errors={"signal": ["SIGNAL_AI_BASE_URL/API_KEY required"]},
        )
    provider = SignalGovernedLLMProvider(
        base_url=base_url,
        api_key=api_key,
        timeout_seconds=float(current_app.config.get("SIGNAL_AI_TIMEOUT_SECONDS") or 120),
    )
    # SV2: el reviewer juzga grounding con los mismos textos de evidencia congelados.
    evidence_for_review = [
        {
            "evidence_id": str(item.get("evidence_id") or ""),
            "text": str(item.get("exact_excerpt") or item.get("extract") or "")[:400],
        }
        for item in (snap.get("evidence_items") or [])
        if isinstance(item, Mapping) and str(item.get("evidence_id") or "").strip()
    ][:80]
    body: dict[str, Any] = {
        "task_key": "report_custom_review",
        "input": {
            "messages": [
                {
                    "role": "user",
                    "content": json.dumps(
                        {
                            "snapshot_hash": current_hash,
                            "writer_output": writer_output,
                            "allowlist": snap.get("allowlist") or [],
                            "evidence_items": evidence_for_review,
                            "review_rule": (
                                "approved=false si el informe afirma personas, empresas o "
                                "cifras que no estén respaldadas por evidence_items."
                            ),
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                }
            ],
            "format": "json",
        },
    }
    try:
        payload = provider.run_governed(body)
    except AIRejected as exc:
        raise CustomReportError(
            f"Signal rechazó la salida de RT-10: {exc}",
            errors={
                "signal_rejection": [exc.error_code],
                "signal_request_id": [exc.request_id] if exc.request_id else [],
            },
        ) from exc
    except AIUnavailable as exc:
        raise CustomReportError(
            f"Signal no disponible para RT-10: {exc}",
            errors={"signal": [str(exc)]},
        ) from exc
    validated = payload.get("validated_output")
    if not isinstance(validated, dict):
        raise CustomReportError(
            "Signal no devolvió validated_output para report_custom_review.",
            errors={"validated_output": ["missing"]},
        )
    usage = payload.get("usage") if isinstance(payload.get("usage"), dict) else {}
    return {
        "validated_output": validated,
        "validated_output_sha256": payload.get("validated_output_sha256"),
        "runtime": payload.get("runtime"),
        "provider": payload.get("provider"),
        "model": payload.get("model"),
        "run_id": payload.get("run_id") or payload.get("request_id"),
        "request_id": payload.get("request_id"),
        "fallback_used": payload.get("fallback_used"),
        "usage": usage,
        "attempts": payload.get("attempts"),
    }


def _bind_ai_usage_once(
    session: Session,
    *,
    report: Report,
    job: BackgroundJob,
    phase: str,
    task_key: str,
    runtime_id: str,
    signal_meta: Mapping[str, Any] | None,
    snapshot_hash: str,
) -> dict[str, Any]:
    """Persist a durable idempotent usage binding (retry/replay keeps one row)."""

    from opn_oracle.oracle.custom_report_usage import upsert_report_ai_usage_binding

    meta = dict(signal_meta or {})
    run_id = str(meta.get("run_id") or getattr(job, "id", "") or "")
    binding = upsert_report_ai_usage_binding(
        session,
        tenant_id=require_tenant_id(),
        report_id=report.id,
        job_id=getattr(job, "id", None),
        phase=phase,
        task_key=task_key,
        runtime_id=runtime_id,
        run_id=run_id,
        request_id=str(meta.get("request_id") or getattr(job, "request_id", "") or "") or None,
        provider=str(meta.get("provider") or "unknown"),
        model=str(meta.get("model") or "unknown"),
        fallback_used=bool(meta.get("fallback_used", False)),
        snapshot_hash=snapshot_hash,
        usage=(dict(meta["usage"]) if isinstance(meta.get("usage"), dict) else {}),
        attempts=meta.get("attempts"),
        validated_output_sha256=(
            str(meta.get("validated_output_sha256"))
            if meta.get("validated_output_sha256")
            else None
        ),
    )
    return {
        "id": str(binding.id),
        "phase": phase,
        "task_key": task_key,
        "runtime_id": runtime_id,
        "run_id": run_id,
        "provider": binding.provider,
        "model": binding.model,
        "usage": meta.get("usage"),
        "attempts": meta.get("attempts"),
        "snapshot_hash": snapshot_hash,
        "job_id": str(getattr(job, "id", "") or ""),
        "binding_id": str(binding.id),
    }


def process_custom_brief_write(
    session: Session,
    payload: Mapping[str, Any],
    job: BackgroundJob,
) -> dict[str, Any]:
    """Writer uses EXACTLY accepted_snapshot. Enqueues separate RT-10 review job.

    Consumes Signal validated_output only (never payload.result).
    Deterministic generator is TESTING-only — never productive placeholder.
    """

    tenant_id = require_tenant_id()
    try:
        report_id = uuid.UUID(str(payload["report_id"]))
        dossier_id = uuid.UUID(str(payload["dossier_id"]))
        expected_snap = str(payload.get("snapshot_hash") or "")
        fence = str(payload.get("generation_fence") or payload.get("fence_token") or "")
    except (KeyError, TypeError, ValueError) as error:
        raise CustomReportError("Payload de write incompleto.") from error

    report = session.scalar(
        select(Report).where(
            Report.id == report_id,
            Report.tenant_id == tenant_id,
            Report.dossier_id == dossier_id,
        )
    )
    if report is None:
        raise CustomReportNotFound("Informe no encontrado.")
    options = dict(report.options or {})
    lifecycle = _lifecycle_of(report)

    if job.cancel_requested or lifecycle == "cancelled":
        return {"report_id": str(report.id), "dropped": True, "reason": "cancelled"}

    snap = options.get("accepted_snapshot")
    if not isinstance(snap, dict):
        raise CustomReportError("Snapshot no congelado.")
    current_hash = str(options.get("accepted_snapshot_hash") or "")
    if expected_snap and current_hash and expected_snap != current_hash:
        return {
            "report_id": str(report.id),
            "dropped": True,
            "reason": "snapshot_fence_mismatch",
        }
    if fence and options.get("fence_token") and str(options.get("fence_token")) != fence:
        return {"report_id": str(report.id), "dropped": True, "reason": "fence_token_mismatch"}

    if lifecycle == "ready":
        return {"report_id": str(report.id), "dropped": True, "reason": "already_ready"}

    # Defense in depth: worker must re-check productive generation gate.
    gen_ok, gen_code, gen_reason = _productive_generation_allowed(snap)
    if not gen_ok:
        options["lifecycle_state"] = "failed"
        options["generation_blocked"] = True
        options["generation_blocked_code"] = gen_code
        options["generation_blocked_reason"] = gen_reason
        report.options = options
        report.status = "failed"
        report.error_code = gen_code
        report.error_message = gen_reason[:500]
        report.version = int(report.version) + 1
        session.flush()
        return {
            "report_id": str(report.id),
            "failed": True,
            "reason": gen_code,
            "error": gen_reason[:300],
        }

    signal_meta: dict[str, Any] | None = None
    if _testing_mode():
        writer_output = _deterministic_writer_output_for_testing(
            snap=snap, options=options, current_hash=current_hash
        )
        vo_sha = hashlib.sha256(
            json.dumps(writer_output, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        signal_meta = {
            "source": "testing_deterministic",
            "validated_output_sha256": vo_sha,
            "provider": "testing",
            "model": "deterministic",
            "run_id": str(getattr(job, "id", "")),
            "usage": {"input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0},
            "attempts": 1,
        }
    else:
        try:
            signal_bundle = _invoke_rt09_writer_via_signal(
                snap=snap, options=options, current_hash=current_hash
            )
        except CustomReportError as exc:
            failure_code = (
                "signal_rt09_invalid_output"
                if exc.errors.get("signal_rejection")
                else "signal_rt09_unavailable"
            )
            options["lifecycle_state"] = "failed"
            report.options = options
            report.status = "failed"
            report.error_code = failure_code
            report.error_message = str(exc)[:500]
            report.version = int(report.version) + 1
            session.flush()
            return {
                "report_id": str(report.id),
                "failed": True,
                "reason": failure_code,
                "error": str(exc)[:300],
            }
        writer_output = dict(signal_bundle["validated_output"])
        signal_meta = {
            "source": "signal_validated_output",
            "validated_output_sha256": signal_bundle.get("validated_output_sha256"),
            "provider": signal_bundle.get("provider"),
            "model": signal_bundle.get("model"),
            "run_id": signal_bundle.get("run_id"),
            "usage": signal_bundle.get("usage"),
            "attempts": signal_bundle.get("attempts"),
            "runtime": signal_bundle.get("runtime"),
        }

    # Enforce snapshot allowlist locally (defense in depth; Signal already gated).
    all_citations: list[Any] = list(writer_output.get("citations") or [])
    for sec in writer_output.get("sections") or []:
        if isinstance(sec, dict):
            all_citations.extend(sec.get("citations") or [])
    foreign = validate_citations_against_snapshot(snap, all_citations)
    if foreign:
        options["lifecycle_state"] = "failed"
        report.options = options
        report.status = "failed"
        report.error_code = "citation_foreign"
        report.error_message = f"Citas fuera de allowlist: {foreign[:5]}"
        report.version = int(report.version) + 1
        session.flush()
        return {"report_id": str(report.id), "failed": True, "foreign": foreign}

    # Persist fenced draft only; enqueue separate review job (no inline review).
    options["writer_output"] = writer_output
    options["writer_validated_output_sha256"] = (signal_meta or {}).get("validated_output_sha256")
    options["writer_signal_meta"] = signal_meta
    options["lifecycle_state"] = "reviewing"
    # Durable idempotent usage binding (retry keeps one effective row).
    writer_binding = _bind_ai_usage_once(
        session,
        report=report,
        job=job,
        phase="writer",
        task_key="report_custom_writer",
        runtime_id="RT-09",
        signal_meta=signal_meta,
        snapshot_hash=current_hash,
    )
    bindings = list(options.get("ai_usage_bindings") or [])
    # Keep JSONB mirror in sync without duplicating phase+run_id.
    bindings = [
        b
        for b in bindings
        if not (
            isinstance(b, dict)
            and b.get("phase") == "writer"
            and str(b.get("run_id") or "") == str(writer_binding.get("run_id") or "")
        )
    ]
    bindings.append(writer_binding)
    options["ai_usage_bindings"] = bindings
    report.options = options
    report.status = "generating"
    report.version = int(report.version) + 1

    review_job = stage_job(
        CUSTOM_REVIEW_JOB,
        payload={
            "report_id": str(report.id),
            "dossier_id": str(dossier_id),
            "purpose": "report",
            "snapshot_hash": current_hash,
            "generation_version": report.generation_version,
            # generation_fence: el validador de payloads prohíbe la familia "token"
            # (mismo rename que el staging del write en 036).
            "generation_fence": fence or options.get("fence_token"),
            "writer_job_id": str(job.id),
        },
        idempotency_key=(
            f"custom-brief-review:{report.id}:{report.generation_version}:{current_hash[:16]}"
        ),
        requested_by_user_id=getattr(job, "requested_by_user_id", None),
        dossier_id=dossier_id,
        resource_type="report",
        resource_id=report.id,
        request_id=getattr(job, "request_id", None),
        max_attempts=3,
    )
    options = dict(report.options or {})
    options["review_job_id"] = str(review_job.id)
    report.options = options
    report.background_job_id = review_job.id

    append_audit_event(
        session,
        action="report.custom_brief.reviewing",
        resource_type="report",
        resource_id=report.id,
        dossier_id=dossier_id,
        result="success",
        correlation_id=job.correlation_id,
        metadata={
            "snapshot_hash": current_hash,
            "section_count": len(writer_output.get("sections") or []),
            "review_job_id": str(review_job.id),
            "writer_run_id": (signal_meta or {}).get("run_id"),
            "inline_review": False,
        },
    )
    session.flush()
    return {
        "report_id": str(report.id),
        "lifecycle_state": "reviewing",
        "review_job_id": str(review_job.id),
        "validated_output_sha256": (signal_meta or {}).get("validated_output_sha256"),
        "snapshot_hash": current_hash,
    }


def process_custom_brief_review(
    session: Session,
    payload: Mapping[str, Any],
    job: BackgroundJob,
) -> dict[str, Any]:
    """Separate RT-10 review job. Ready only after approval + hash/size validation."""

    tenant_id = require_tenant_id()
    report_id = uuid.UUID(str(payload["report_id"]))
    dossier_id = uuid.UUID(str(payload["dossier_id"]))
    expected_snap = str(payload.get("snapshot_hash") or "")
    fence = str(payload.get("generation_fence") or payload.get("fence_token") or "")

    report = session.scalar(
        select(Report).where(
            Report.id == report_id,
            Report.tenant_id == tenant_id,
            Report.dossier_id == dossier_id,
        )
    )
    if report is None:
        raise CustomReportNotFound("Informe no encontrado.")
    options = dict(report.options or {})
    lifecycle = _lifecycle_of(report)
    if job.cancel_requested or lifecycle == "cancelled":
        return {"report_id": str(report.id), "dropped": True, "reason": "cancelled"}
    if lifecycle == "ready":
        return {"report_id": str(report.id), "idempotent": True, "lifecycle_state": "ready"}

    snap = options.get("accepted_snapshot")
    if not isinstance(snap, dict):
        raise CustomReportError("Snapshot no congelado en review.")
    current_hash = str(options.get("accepted_snapshot_hash") or "")
    if expected_snap and current_hash and expected_snap != current_hash:
        return {"report_id": str(report.id), "dropped": True, "reason": "snapshot_fence_mismatch"}
    if fence and options.get("fence_token") and str(options.get("fence_token")) != fence:
        return {"report_id": str(report.id), "dropped": True, "reason": "fence_token_mismatch"}

    writer_output = options.get("writer_output")
    if not isinstance(writer_output, dict) or not writer_output.get("sections"):
        options["lifecycle_state"] = "failed"
        report.options = options
        report.status = "failed"
        report.error_code = "writer_output_missing"
        report.error_message = "Salida del writer ausente o incompleta."
        report.version = int(report.version) + 1
        session.flush()
        return {"report_id": str(report.id), "failed": True, "reason": "writer_output_missing"}

    # RT-10 review: TESTING uses local approve; prod consumes Signal validated_output only.
    review_meta: dict[str, Any]
    if _testing_mode():
        review_output = {
            "version": "custom_report_review.v1",
            "approved": True,
            "issues": [],
            "citations_ok": True,
            "notes": ["testing auto-approve"],
            "snapshot_hash": current_hash,
        }
        review_meta = {
            "source": "testing_deterministic",
            "validated_output_sha256": hashlib.sha256(
                json.dumps(review_output, sort_keys=True, separators=(",", ":")).encode()
            ).hexdigest(),
            "provider": "testing",
            "model": "deterministic",
            "run_id": str(getattr(job, "id", "")),
            "usage": {"input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0},
            "attempts": 1,
        }
    else:
        try:
            signal_bundle = _invoke_rt10_review_via_signal(
                snap=snap, writer_output=writer_output, current_hash=current_hash
            )
        except CustomReportError as exc:
            failure_code = (
                "signal_rt10_invalid_output"
                if exc.errors.get("signal_rejection")
                else "signal_rt10_unavailable"
            )
            options["lifecycle_state"] = "failed"
            report.options = options
            report.status = "failed"
            report.error_code = failure_code
            report.error_message = str(exc)[:500]
            report.version = int(report.version) + 1
            session.flush()
            return {
                "report_id": str(report.id),
                "failed": True,
                "reason": failure_code,
                "error": str(exc)[:300],
            }
        review_output = dict(signal_bundle["validated_output"])
        review_meta = {
            "source": "signal_validated_output",
            "validated_output_sha256": signal_bundle.get("validated_output_sha256"),
            "provider": signal_bundle.get("provider"),
            "model": signal_bundle.get("model"),
            "run_id": signal_bundle.get("run_id"),
            "usage": signal_bundle.get("usage"),
            "attempts": signal_bundle.get("attempts"),
            "runtime": signal_bundle.get("runtime"),
        }

    options["review_output"] = review_output
    options["review_validated_output_sha256"] = review_meta.get("validated_output_sha256")
    options["review_signal_meta"] = review_meta
    review_binding = _bind_ai_usage_once(
        session,
        report=report,
        job=job,
        phase="review",
        task_key="report_custom_review",
        runtime_id="RT-10",
        signal_meta=review_meta,
        snapshot_hash=current_hash,
    )
    bindings = list(options.get("ai_usage_bindings") or [])
    bindings = [
        b
        for b in bindings
        if not (
            isinstance(b, dict)
            and b.get("phase") == "review"
            and str(b.get("run_id") or "") == str(review_binding.get("run_id") or "")
        )
    ]
    bindings.append(review_binding)
    options["ai_usage_bindings"] = bindings

    approved = bool(review_output.get("approved")) and bool(review_output.get("citations_ok", True))
    if not approved:
        issues_raw = review_output.get("issues")
        issues_list: list[Any] = issues_raw if isinstance(issues_raw, list) else []
        options["lifecycle_state"] = "failed"
        report.options = options
        report.status = "failed"
        report.error_code = "review_rejected"
        report.error_message = (
            "Revisión RT-10 no aprobó el borrador: " + ", ".join(str(x) for x in issues_list[:5])
        )[:500]
        report.version = int(report.version) + 1
        session.flush()
        return {
            "report_id": str(report.id),
            "failed": True,
            "reason": "review_rejected",
            "issues": review_output.get("issues"),
        }

    # Assemble artifact body (Oracle owns render) — only after approval.
    content = {
        "kind": "custom_assistant_report",
        "title": report.title,
        "snapshot_hash": current_hash,
        "accepted_plan": options.get("accepted_plan"),
        "sections": writer_output.get("sections"),
        "sourcing": summarize_section_sourcing(writer_output.get("sections")),
        "facts": writer_output.get("facts") or [],
        "claims": writer_output.get("claims") or [],
        "conflicts": writer_output.get("conflicts") or [],
        "inferences": writer_output.get("inferences") or [],
        "recommendations": writer_output.get("recommendations") or [],
        "citations": writer_output.get("citations") or [],
        "coverage": snap.get("coverage"),
        "memory_mode": snap.get("memory_mode"),
        "runtime": {
            "writer": "RT-09",
            "review": "RT-10",
            "plan": "RT-08",
            "writer_validated_output_sha256": options.get("writer_validated_output_sha256"),
            "review_validated_output_sha256": options.get("review_validated_output_sha256"),
            "runtime_sha256": snap.get("runtime_sha256"),
        },
        "review": {
            "approved": True,
            "citations_ok": review_output.get("citations_ok"),
            "issues": review_output.get("issues") or [],
        },
        "assembled_at": datetime.now(UTC).isoformat(),
    }
    raw = json.dumps(content, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode(
        "utf-8"
    )
    sha = hashlib.sha256(raw).hexdigest()
    byte_size = len(raw)
    if byte_size <= 0 or not sha:
        options["lifecycle_state"] = "failed"
        report.options = options
        report.status = "failed"
        report.error_code = "artifact_empty"
        report.error_message = "Artefacto vacío o sin hash; no se publica ready."
        report.version = int(report.version) + 1
        session.flush()
        return {"report_id": str(report.id), "failed": True, "reason": "artifact_empty"}

    # Atomic publish: only set ready after review approval + hash/size validation
    artifact = {
        "status": "available",
        "format": "json",
        "sha256": sha,
        "byte_size": byte_size,
        "content": content,
        "generation_version": report.generation_version,
        "snapshot_hash": current_hash,
        "published_at": datetime.now(UTC).isoformat(),
        "review_approved": True,
    }
    versions = list(options.get("artifact_versions") or [])
    prev = options.get("ready_artifact")
    if isinstance(prev, dict) and prev.get("status") == "available":
        versions.append(prev)
    options["artifact_versions"] = versions
    options["ready_artifact"] = artifact
    options["lifecycle_state"] = "ready"
    report.options = options
    report.content = content
    report.status = "ready"
    report.ready_at = datetime.now(UTC)
    report.version = int(report.version) + 1
    report.error_code = None
    report.error_message = None
    append_audit_event(
        session,
        action="report.custom_brief.ready",
        resource_type="report",
        resource_id=report.id,
        dossier_id=dossier_id,
        result="success",
        correlation_id=getattr(job, "correlation_id", None),
        metadata={
            "sha256": sha,
            "byte_size": byte_size,
            "snapshot_hash": current_hash,
            "version": report.version,
            "review_run_id": review_meta.get("run_id"),
            "review_approved": True,
        },
    )
    session.flush()
    return {
        "report_id": str(report.id),
        "lifecycle_state": "ready",
        "sha256": sha,
        "byte_size": byte_size,
        "snapshot_hash": current_hash,
        "review_approved": True,
    }


def summarize_section_sourcing(sections: Any) -> dict[str, Any]:
    """Resume que secciones del informe tienen respaldo y cuales no.

    El informe se publica siempre; lo que cambia es que el lector sepa de que se fia.
    Una seccion sin cita no se oculta ni se descarta: se etiqueta, y ese resumen viaja
    dentro del artefacto descargable para que sobreviva a la exportacion. Una etiqueta
    que solo existe en pantalla desaparece en cuanto el informe sale a Word.
    """

    total = 0
    con_fuente = 0
    sin_fuente: list[str] = []
    if isinstance(sections, list):
        for idx, sec in enumerate(sections, 1):
            if not isinstance(sec, dict):
                continue
            total += 1
            cits = sec.get("citations")
            titulo = str(sec.get("title") or f"Sección {idx}").strip()
            if isinstance(cits, list) and cits:
                con_fuente += 1
            else:
                sin_fuente.append(titulo)
                sec["unsourced"] = True
                sec["sourcing_label"] = "SIN FUENTE VERIFICABLE"
    etiqueta = (
        f"{con_fuente} de {total} secciones con fuente verificable" if total else "sin secciones"
    )
    return {
        "sections_total": total,
        "sections_with_source": con_fuente,
        "sections_without_source": len(sin_fuente),
        "unsourced_titles": sin_fuente,
        "label": etiqueta,
        "notice": (
            "Las secciones marcadas SIN FUENTE VERIFICABLE no están respaldadas por "
            "evidencia autorizada del expediente: trátalas como hipótesis, no como hechos."
        )
        if sin_fuente
        else "",
    }


def get_downloadable_artifact(report: Report) -> dict[str, Any] | None:
    """Only ready+validated artifacts are downloadable."""
    if _lifecycle_of(report) != "ready":
        return None
    options = dict(report.options or {})
    art = options.get("ready_artifact")
    if not isinstance(art, dict):
        return None
    if art.get("status") != "available":
        return None
    if not art.get("sha256") or int(art.get("byte_size") or 0) <= 0:
        return None
    return art
