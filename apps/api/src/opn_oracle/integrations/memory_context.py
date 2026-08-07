"""Oracle adapter for Signal opn_memory context retrieval (MDEV-04 provisional).

Oracle never opens SQL to Signal. Retrieval is HTTP (or mock/disabled).
Publisher debt (RACE-MDEV02-003 / DB-MDEV02-001): capability degraded; reindex not promised.
"""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Mapping
from typing import Any, Literal, Protocol, runtime_checkable

from flask import current_app

from opn_oracle.integrations.memory_contract_v1 import (
    resolve_effective_mode,
    should_call_signal,
    should_inject_into_llm,
)
from opn_oracle.integrations.memory_http_client import (
    MemoryHttpError,
    SignalMemoryHttpClient,
)
from opn_oracle.integrations.memory_profile import (
    build_client_for_connection,
    resolve_signal_memory_connection,
)

Purpose = Literal["question", "report", "summary", "wizard"]
MemoryContextMode = Literal["disabled", "mock", "http"]

COVERAGE_MANIFEST_VERSION = "coverage_manifest.v1"
MEMORY_RETRIEVAL_API_VERSION = "memory.v1"


class MemoryContextError(RuntimeError):
    """Non-retryable adapter failure without secret-bearing detail."""


class MemoryContextDisabled(MemoryContextError):
    """MEMORY_CONTEXT_MODE=disabled; retrieval is intentionally off."""


def empty_coverage_manifest(
    *,
    requested: list[str] | None = None,
    token_budget: int = 0,
    failed: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "version": COVERAGE_MANIFEST_VERSION,
        "requested": list(requested or []),
        "consulted": [],
        "failed": list(failed or []),
        "excluded": [],
        "used": [],
        "truncated": False,
        "truncation_notes": [],
        "cutoff_at": None,
        "token_budget": int(token_budget),
        "token_used_estimate": 0,
    }


def empty_memory_retrieval_response(
    *,
    request_id: str | None = None,
    policy_version: str = "disabled",
    requested: list[str] | None = None,
    failed: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "api_version": MEMORY_RETRIEVAL_API_VERSION,
        "request_id": request_id or str(uuid.uuid4()),
        "policy_version": policy_version,
        "items": [],
        "coverage_manifest": empty_coverage_manifest(requested=requested, failed=failed),
    }


@runtime_checkable
class MemoryContextAdapter(Protocol):
    def retrieve(
        self,
        scope_hint: Mapping[str, Any] | None,
        query: str,
        purpose: str,
        limit: int,
    ) -> dict[str, Any]: ...


class DisabledMemoryContextAdapter:
    def retrieve(
        self,
        scope_hint: Mapping[str, Any] | None,
        query: str,
        purpose: str,
        limit: int,
    ) -> dict[str, Any]:
        del scope_hint, query, purpose, limit
        raise MemoryContextDisabled("Recuperación de memoria desactivada.")


class MockMemoryContextAdapter:
    def __init__(self, *, policy_version: str = "mock.v1") -> None:
        self.policy_version = policy_version
        self.calls: list[dict[str, Any]] = []

    def retrieve(
        self,
        scope_hint: Mapping[str, Any] | None,
        query: str,
        purpose: str,
        limit: int,
    ) -> dict[str, Any]:
        if not isinstance(query, str):
            raise MemoryContextError("query debe ser texto.")
        if purpose not in {"question", "report", "summary", "wizard"}:
            raise MemoryContextError("purpose no es válido.")
        if not isinstance(limit, int) or limit < 1 or limit > 100:
            raise MemoryContextError("limit debe estar entre 1 y 100.")
        scope = dict(scope_hint or {})
        requested = ["mock.memory"]
        if scope.get("dossier_id") is not None:
            requested.append(f"dossier:{scope['dossier_id']}")
        self.calls.append({"scope_hint": scope, "query": query, "purpose": purpose, "limit": limit})
        return empty_memory_retrieval_response(
            policy_version=self.policy_version,
            requested=requested,
        )


class HttpMemoryContextAdapter:
    """Productive HTTP consumer of Signal memory.v1 (tenant-scoped credentials)."""

    def __init__(
        self,
        *,
        client: SignalMemoryHttpClient | None = None,
        base_url: str = "",
        timeout_seconds: float = 10.0,
        transport: Any | None = None,
        api_token: str | None = None,
        external_tenant_id: str | None = None,
        effective_mode: str = "shadow",
        require_https: bool = True,
    ) -> None:
        self.client = client
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds
        self.transport = transport
        self.api_token = api_token
        self.external_tenant_id = external_tenant_id
        self.effective_mode = effective_mode
        self.require_https = require_https
        self.calls: list[dict[str, Any]] = []
        self.last_snapshot: dict[str, Any] | None = None

    def _resolve_client(self, scope: dict[str, Any]) -> tuple[SignalMemoryHttpClient, str]:
        if self.client is not None:
            tenant = str(self.external_tenant_id or scope.get("external_tenant_id") or "").strip()
            if not tenant:
                raise MemoryContextError("tenant_required")
            return self.client, tenant

        # From Flask app context + DB connection
        from opn_oracle.extensions import db

        tenant_id = scope.get("tenant_id")
        if tenant_id is None:
            raise MemoryContextError("tenant_id required in scope_hint")
        tenant_uuid = uuid.UUID(str(tenant_id))
        preferred = scope.get("connection_id")
        preferred_uuid = uuid.UUID(str(preferred)) if preferred else None
        session = db.session()
        conn = resolve_signal_memory_connection(
            session, tenant_id=tenant_uuid, preferred_connection_id=preferred_uuid
        )
        transport = self.transport
        if transport is None:
            from opn_oracle.integrations.memory_http_client import HttpxTransport

            transport = HttpxTransport()
        client = build_client_for_connection(
            conn, transport=transport, require_https=self.require_https
        )
        # external tenant string is Oracle tenant slug/key from scope
        external = str(scope.get("external_tenant_id") or "").strip()
        if not external:
            # Fallback from IC metadata (Ask/scope often omit header tenant).
            meta = (
                conn.connection_metadata
                if isinstance(getattr(conn, "connection_metadata", None), dict)
                else {}
            )
            external = str(
                meta.get("external_tenant_id")
                or meta.get("signal_external_tenant_id")
                or conn.tenant_id
                or ""
            ).strip()
        if not external:
            raise MemoryContextError("external_tenant_id required")
        return client, external

    def retrieve(
        self,
        scope_hint: Mapping[str, Any] | None,
        query: str,
        purpose: str,
        limit: int,
    ) -> dict[str, Any]:
        if not isinstance(query, str):
            raise MemoryContextError("query debe ser texto.")
        if purpose not in {"question", "report", "summary", "wizard"}:
            raise MemoryContextError("purpose no es válido.")
        if not isinstance(limit, int) or limit < 1 or limit > 100:
            raise MemoryContextError("limit debe estar entre 1 y 100.")

        scope = dict(scope_hint or {})
        dossier_id = str(scope.get("dossier_id") or "").strip()
        if not dossier_id:
            raise MemoryContextError("dossier_id required")

        # Mode gate: disabled never calls Signal
        mode = str(scope.get("mode") or self.effective_mode or "disabled")
        if not should_call_signal(mode):  # type: ignore[arg-type]
            raise MemoryContextDisabled("mode does not call Signal")

        # ORA-AUTOGRANT fail-closed: operational mode requires a stored authorized grant.
        # Do not invent authorized when grant was never checked or is manual_required.
        tenant_for_grant = scope.get("tenant_id")
        if tenant_for_grant is not None:
            from opn_oracle.extensions import db as _db
            from opn_oracle.integrations.memory_grant import require_usable_memory_grant
            from opn_oracle.integrations.memory_profile import (
                load_default_dossier_memory_profile,
            )

            try:
                grant_row = load_default_dossier_memory_profile(
                    _db.session(),
                    tenant_id=uuid.UUID(str(tenant_for_grant)),
                    dossier_id=uuid.UUID(str(dossier_id)),
                )
                require_usable_memory_grant(grant_row)
            except MemoryHttpError as grant_exc:
                raise MemoryContextError(grant_exc.code) from grant_exc

        # Tenant binding: reject key/tenant mismatch before HTTP when explicit
        bound_tenant = str(scope.get("connection_external_tenant_id") or "").strip()
        header_tenant = str(scope.get("external_tenant_id") or "").strip()
        if bound_tenant and header_tenant and bound_tenant != header_tenant:
            raise MemoryContextError("credential_tenant_mismatch")

        try:
            client, external_tenant = self._resolve_client(scope)
            if bound_tenant and external_tenant != bound_tenant:
                raise MemoryContextError("credential_tenant_mismatch")
            import hashlib as _hl

            self.calls.append(
                {
                    "query_sha256": _hl.sha256(query.encode()).hexdigest()[:16],
                    "query_len": len(query),
                    "purpose": purpose,
                    "limit": limit,
                    "dossier_id": dossier_id,
                    "external_tenant_id": external_tenant,
                }
            )
            result = client.retrieve(
                external_tenant_id=external_tenant,
                dossier_id=dossier_id,
                query=query,
                purpose=purpose,
                limit=limit,
                token_budget=int(scope.get("token_budget") or 4000),
                kinds=list(scope.get("kinds") or []) or None,
                source_types=list(scope.get("sources") or []) or None,
                classifications=list(scope.get("classifications_allowed") or []) or None,
                cutoff_at=scope.get("cutoff_at"),
            )
        except MemoryHttpError as exc:
            # Technical failure exhausted path: coverage.failed, not empty success
            failed = [
                {
                    "code": exc.code,
                    "retryable": exc.retryable,
                    "detail": exc.message[:120],
                }
            ]
            resp = empty_memory_retrieval_response(
                policy_version="memory.v1.error",
                requested=["retrieval"],
                failed=failed,
            )
            resp["error"] = {"code": exc.code, "retryable": exc.retryable}
            resp["publisher_degraded"] = True
            self.last_snapshot = {
                "mode": mode,
                "failed": True,
                "items": [],
                "coverage": resp["coverage_manifest"],
            }
            if not exc.retryable:
                raise MemoryContextError(exc.message) from exc
            return resp

        items = list(result.get("items") or [])
        # Bound item payload for snapshot (checksums only for large text)
        bounded_items = []
        for it in items[:50]:
            if not isinstance(it, dict):
                continue
            text = str(it.get("text") or "")[:2000]
            bounded_items.append(
                {
                    "id": it.get("id"),
                    "kind": it.get("kind"),
                    "checksum": it.get("checksum")
                    or hashlib.sha256(text.encode()).hexdigest()[:32],
                    "text_preview": text[:240],
                    "score": it.get("score"),
                }
            )
        inject = should_inject_into_llm(mode)  # type: ignore[arg-type]
        self.last_snapshot = {
            "mode": mode,
            "failed": False,
            "inject_into_llm": inject,
            "items": bounded_items if inject else [],
            "items_observed": len(items),
            "coverage": result.get("coverage_manifest"),
            "watermark": result.get("watermark"),
            "request_id": result.get("request_id"),
        }
        # Snapshot material is returned; orchestrator persists via Session (no silent swallow).
        # publisher_degraded is ONLY True on real failure (MemoryHttpError above). The old
        # hardcoded True ("Signal debt" for CAS/fencing/requeue) made every Ask look degraded
        # even with coverage.failed=[] — that debt closed operationally 2026-08-02.
        out_common = {
            "snapshot": self.last_snapshot,
            "snapshot_meta": {
                "tenant_id": str(scope.get("tenant_id") or ""),
                "dossier_id": dossier_id,
                "connection_id": str(scope.get("connection_id") or "") or None,
                "mode": mode,
                "correlation_id": str(result.get("request_id") or uuid.uuid4()),
                "intent_revision_hash": str(scope.get("intent_revision_hash") or "") or None,
            },
            "publisher_degraded": False,
        }

        if mode == "shadow":
            out = dict(result)
            out.update(out_common)
            out["items_for_prompt"] = []
            out["items_observed"] = items
            out["shadow"] = True
            return out
        out = dict(result)
        out.update(out_common)
        out["items_for_prompt"] = items if inject else []
        out["augment"] = inject
        return out


def build_memory_context_adapter(
    mode: str,
    *,
    base_url: str = "",
    timeout_seconds: float = 10.0,
    transport: Any | None = None,
    api_token: str | None = None,
    external_tenant_id: str | None = None,
    require_https: bool = True,
) -> MemoryContextAdapter:
    normalized = str(mode or "disabled").strip().lower() or "disabled"
    if normalized == "disabled":
        return DisabledMemoryContextAdapter()
    if normalized == "mock":
        return MockMemoryContextAdapter()
    if normalized == "http":
        client = None
        if base_url and api_token and transport is not None:
            from opn_oracle.integrations.memory_http_client import MemoryClientConfig

            client = SignalMemoryHttpClient(
                MemoryClientConfig(
                    base_url=base_url,
                    api_token=api_token,
                    require_https=require_https,
                ),
                transport,
            )
        return HttpMemoryContextAdapter(
            client=client,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            transport=transport,
            api_token=api_token,
            external_tenant_id=external_tenant_id,
            require_https=require_https,
        )
    raise MemoryContextError(
        "MEMORY_CONTEXT_MODE debe ser disabled, mock o http "
        f"(recibido {normalized!r}; fail-closed)."
    )


def get_memory_context_adapter() -> MemoryContextAdapter:
    mode = (
        str(current_app.config.get("MEMORY_CONTEXT_MODE", "disabled") or "disabled").strip().lower()
    )
    if mode not in {"disabled", "mock", "http"}:
        mode = "disabled"
    base_url = str(current_app.config.get("MEMORY_CONTEXT_BASE_URL", "") or "")
    timeout = float(current_app.config.get("MEMORY_CONTEXT_TIMEOUT_SECONDS", 10.0) or 10.0)
    return build_memory_context_adapter(mode, base_url=base_url, timeout_seconds=timeout)


def capability_payload(*, host_mode: str, connection_healthy: bool) -> dict[str, Any]:
    """Health/capability for UI — no secrets.

    G-29 honesty: retrieval is always dossier-scoped when enabled. There is no
    global, cross-tenant or tenant_curated memory capability in the motor.
    Available operational modes are disabled|shadow|augment only.
    """
    eff = resolve_effective_mode(
        host_memory_context_mode=host_mode,
        connection_healthy=connection_healthy,
        tenant_mode="disabled",
    )
    # Host gate only (tenant_mode is a placeholder here). CAS/fencing/requeue
    # closed 2026-08-02 — do not force publisher_status=degraded on green hosts.
    host = str(host_mode or "").strip().lower() or "disabled"
    host_enabled = host not in {"disabled", "mock"}
    publisher_ok = bool(connection_healthy and host_enabled)
    # Público: solo señales de salud comprensibles. Códigos internos de deuda
    # (RACE/DB/SEC/MIG-MDEV*) y actions_reliable quedan fuera del contrato cliente.
    return {
        "host_mode": host_mode,
        "effective_mode": eff.mode,
        "publisher_reliable": publisher_ok,
        "publisher_status": "ok" if publisher_ok else "unavailable",
        "message": (
            "Memory retrieve path operational (dossier-scoped only)."
            if publisher_ok
            else "Memory publisher unavailable (host disabled or connection unhealthy)."
        ),
        # Explicit non-claims so UI/OpenAPI cannot imply total memory.
        "scope_type": "dossier",
        "dossier_only": True,
        "uses_global_memory": False,
        "uses_tenant_curated": False,
        "cross_tenant": False,
        "available_modes": ["augment", "disabled", "shadow"],
        "retrieval_semantics": "dossier_scoped_signal_memory_v1",
    }


def persist_retrieval_snapshot(
    session: Any,
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    connection_id: uuid.UUID | None,
    mode: str,
    correlation_id: str,
    snapshot: dict[str, Any],
    intent_revision_hash: str | None = None,
) -> uuid.UUID | None:
    """Write immutable MemoryRetrievalSnapshot on caller session. No silent swallow, no commit."""
    from datetime import UTC, datetime

    from opn_oracle.integrations.models import MemoryRetrievalSnapshot

    if mode == "disabled":
        return None
    raw_items = snapshot.get("items") or []
    items_list: list[Any] = list(raw_items) if isinstance(raw_items, list) else []
    payload: dict[str, Any] = {
        "mode": mode,
        "failed": bool(snapshot.get("failed")),
        "inject_into_llm": bool(snapshot.get("inject_into_llm")),
        "items": items_list[:50],
        "items_observed": snapshot.get("items_observed"),
        "coverage": snapshot.get("coverage"),
        "watermark": snapshot.get("watermark"),
        "request_id": snapshot.get("request_id"),
        "intent_revision_hash": intent_revision_hash,
        "policy_version": "memory.v1",
        "schema": "memory.v1",
        # Reflect real failure; do not invent publisher debt on healthy retrieves.
        "publisher_degraded": bool(snapshot.get("failed")),
        # G-29: snapshot preserves mode + identity of scoped retrieval.
        "tenant_id": str(tenant_id),
        "dossier_id": str(dossier_id),
        "connection_id": str(connection_id) if connection_id else None,
        "scope_type": "dossier",
        "profile_version": snapshot.get("profile_version"),
        "profile_id": snapshot.get("profile_id"),
        "item_ids_used": [
            str(it.get("id") or it.get("signal_item_id") or "")
            for it in items_list[:50]
            if isinstance(it, dict)
        ],
    }
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    if len(raw) > 200_000:
        payload["items"] = list(payload["items"])[:10]
        raw = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ctx_hash = hashlib.sha256(raw).digest()
    row_id = uuid.uuid4()
    row = MemoryRetrievalSnapshot(
        id=row_id,
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        connection_id=connection_id,
        mode=mode,
        correlation_id=correlation_id[:80],
        context_hash=ctx_hash,
        payload=payload,
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )
    session.add(row)
    # Caller commits UoW; failures must propagate to job/coverage.failed.
    return row_id


def persist_snapshot_from_retrieve_result(
    session: Any, result: Mapping[str, Any]
) -> uuid.UUID | None:
    """Orchestrator helper: persist snapshot_meta returned by HttpMemoryContextAdapter.retrieve."""
    meta = result.get("snapshot_meta")
    snap = result.get("snapshot")
    if not isinstance(meta, Mapping) or not isinstance(snap, Mapping):
        return None
    mode = str(meta.get("mode") or "disabled")
    if mode == "disabled":
        return None
    tid = meta.get("tenant_id")
    did = meta.get("dossier_id")
    if not tid or not did:
        raise MemoryContextError("snapshot_meta missing tenant/dossier")
    cid_raw = meta.get("connection_id")
    connection_id = uuid.UUID(str(cid_raw)) if cid_raw else None
    return persist_retrieval_snapshot(
        session,
        tenant_id=uuid.UUID(str(tid)),
        dossier_id=uuid.UUID(str(did)),
        connection_id=connection_id,
        mode=mode,
        correlation_id=str(meta.get("correlation_id") or uuid.uuid4()),
        snapshot=dict(snap),
        intent_revision_hash=(
            str(meta["intent_revision_hash"]) if meta.get("intent_revision_hash") else None
        ),
    )
