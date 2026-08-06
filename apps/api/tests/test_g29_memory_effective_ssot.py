"""G-29 correctivo: effective profile as single source of truth.

Adversarial gates:
- payload.memory_mode cannot force augment when profile is disabled
- connection-bound override is deferred (not selected) for jobs + /effective
- legacy_missing + payload augment → disabled, no write
- PUT with body connection_id does not create a second product profile
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock

import pytest
from flask import g

from opn_oracle.auth import permissions
from opn_oracle.integrations import memory_routes
from opn_oracle.integrations.memory_profile import (
    RESOLUTION_DEFAULT_PROFILE,
    RESOLUTION_LEGACY_MISSING,
    effective_resolution_to_public,
    resolve_effective_dossier_memory_profile,
)
from opn_oracle.oracle import conversations as conv
from opn_oracle.platform.models import User
from opn_oracle.tenants.context import TenantContext, tenant_context


@contextmanager
def _authenticated_http_probe(
    app: Any,
    monkeypatch: pytest.MonkeyPatch,
    allowed_permissions: frozenset[str],
    *,
    user: User | None = None,
    tenant_id: uuid.UUID | None = None,
) -> Iterator[tuple[User, uuid.UUID]]:
    actor = user or User(
        id=uuid.uuid4(),
        email="g29-ssot@example.com",
        display_name="G29 SSOT",
        status="active",
    )
    tid = tenant_id or uuid.uuid4()
    monkeypatch.setattr(permissions, "current_user", actor)
    monkeypatch.setattr(memory_routes, "current_user", actor)
    monkeypatch.setattr(
        permissions,
        "current_permissions",
        lambda user_id, active_tenant_id: allowed_permissions,
    )
    before_request_funcs = app.before_request_funcs.get(None, [])
    auth_index = next(
        index
        for index, function in enumerate(before_request_funcs)
        if function.__name__ == "protect_csrf_and_install_identity"
    )
    original = before_request_funcs[auth_index]

    def install_test_identity() -> None:
        g.active_tenant_id = tid

    before_request_funcs[auth_index] = install_test_identity
    try:
        yield actor, tid
    finally:
        before_request_funcs[auth_index] = original


class _FakeSession:
    def __init__(
        self,
        *,
        dossier: Any | None = None,
        profile: Any | None = None,
        connection: Any | None = None,
        extra_profiles: list[Any] | None = None,
    ) -> None:
        self.dossier = dossier
        self.profile = profile
        self.connection = connection
        self.extra_profiles = list(extra_profiles or [])
        self.added: list[Any] = []
        self.commits = 0
        self.audit_events: list[dict[str, Any]] = []

    def scalar(self, _q: Any) -> Any:
        return self.dossier

    def get(self, model: Any, ident: Any) -> Any:
        name = getattr(model, "__name__", str(model))
        if "StrategicDossier" in name:
            if self.dossier is not None and str(self.dossier.id) == str(ident):
                return self.dossier
            return None
        if "IntegrationConnection" in name:
            if self.connection is not None and str(self.connection.id) == str(ident):
                return self.connection
            return None
        return None

    def add(self, obj: Any) -> None:
        self.added.append(obj)
        if obj.__class__.__name__ == "DossierMemoryProfile":
            self.profile = obj

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        pass


def _dossier(tenant_id: uuid.UUID, dossier_id: uuid.UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=dossier_id or uuid.uuid4(),
        tenant_id=tenant_id,
        owner_user_id=None,
        title="G29 SSOT dossier",
    )


def _profile_row(
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    mode: str = "disabled",
    version: int = 1,
    connection_id: uuid.UUID | None = None,
) -> SimpleNamespace:
    from opn_oracle.integrations.memory_profile import _etag, default_profile_payload

    cfg = default_profile_payload(mode=mode, provenance="server_policy_on_create")
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        connection_id=connection_id,
        mode=mode,
        version=version,
        etag=_etag(version, cfg),
        profile_config=cfg,
        last_test_at=None,
        last_test_status=None,
        last_error=None,
        last_coverage=None,
        updated_at=None,
    )


def _wire_session(monkeypatch: pytest.MonkeyPatch, session: _FakeSession) -> None:
    monkeypatch.setattr(memory_routes, "_session", lambda: session)
    monkeypatch.setattr(
        memory_routes,
        "dossier_accessible",
        lambda session, dossier, user_id, *, write: True,
    )

    def load_profile(
        sess: Any,
        *,
        tenant_id: uuid.UUID,
        dossier_id: uuid.UUID,
        connection_id: uuid.UUID | None,
    ) -> Any:
        candidates = []
        if session.profile is not None:
            candidates.append(session.profile)
        candidates.extend(session.extra_profiles)
        for row in candidates:
            if row.tenant_id != tenant_id or row.dossier_id != dossier_id:
                continue
            if connection_id is None and row.connection_id is None:
                return row
            if connection_id is not None and row.connection_id == connection_id:
                return row
        return None

    monkeypatch.setattr(memory_routes, "_load_profile", load_profile)

    def capture_audit(sess: Any, **kwargs: Any) -> None:
        session.audit_events.append(kwargs)

    monkeypatch.setattr(memory_routes, "append_audit_event", capture_audit)


class _ResolveSession:
    """Minimal session for resolve_effective_dossier_memory_profile."""

    def __init__(self, rows: list[Any]) -> None:
        self.rows = list(rows)

    def scalar(self, _q: Any) -> Any:
        for r in self.rows:
            if getattr(r, "connection_id", "x") is None:
                return r
        return None

    def scalars(self, _q: Any) -> Any:
        deferred = [r for r in self.rows if getattr(r, "connection_id", None) is not None]

        class _R:
            def all(self_inner) -> list[Any]:
                return deferred

        return _R()


@pytest.mark.unit
def test_resolve_prefers_default_defers_connection_override() -> None:
    tid, did = uuid.uuid4(), uuid.uuid4()
    default = _profile_row(tenant_id=tid, dossier_id=did, mode="disabled", version=3)
    conn_override = _profile_row(
        tenant_id=tid,
        dossier_id=did,
        mode="augment",
        version=9,
        connection_id=uuid.uuid4(),
    )
    session = _ResolveSession([default, conn_override])
    res = resolve_effective_dossier_memory_profile(session, tenant_id=tid, dossier_id=did)
    assert res.mode == "disabled"
    assert res.profile_id == str(default.id)
    assert res.version == 3
    assert res.resolution_source == RESOLUTION_DEFAULT_PROFILE
    assert res.deferred_connection_profile_count == 1
    assert res.deferred_connection_profiles[0]["mode"] == "augment"
    assert res.deferred_connection_profiles[0]["product_supported"] is False

    pub = effective_resolution_to_public(res, tenant_id=tid, dossier_id=did)
    assert pub["mode"] == "disabled"
    assert pub["effective_profile"]["mode"] == "disabled"
    assert pub["effective_profile"]["resolution_source"] == RESOLUTION_DEFAULT_PROFILE
    assert pub["configured_profile"]["mode"] == "disabled"
    assert pub["deferred_connection_profile_count"] == 1
    assert pub["profiles_diverge"] is False


@pytest.mark.unit
def test_resolve_legacy_missing_disabled() -> None:
    tid, did = uuid.uuid4(), uuid.uuid4()
    session = _ResolveSession([])
    res = resolve_effective_dossier_memory_profile(session, tenant_id=tid, dossier_id=did)
    assert res.mode == "disabled"
    assert res.profile_id is None
    assert res.version is None
    assert res.resolution_source == RESOLUTION_LEGACY_MISSING
    assert res.persisted is False


@pytest.mark.unit
def test_adversary_payload_augment_cannot_override_disabled_profile(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Profile disabled + payload.memory_mode=augment → disabled, real profile id/version."""
    tenant = uuid.uuid4()
    dossier = uuid.uuid4()
    conversation = uuid.uuid4()
    message_id = uuid.uuid4()
    profile = _profile_row(tenant_id=tenant, dossier_id=dossier, mode="disabled", version=4)

    class CountingAdapter:
        effective_mode = "augment"
        calls = 0

        def retrieve(self, scope: Any, query: str, purpose: str, limit: int) -> dict[str, Any]:
            CountingAdapter.calls += 1
            # Even if called, disabled path must yield zero items.
            assert scope.get("mode") == "disabled"
            return {
                "items": [],
                "items_for_prompt": [],
                "items_observed": [],
                "coverage_manifest": {
                    "requested": ["q"],
                    "used": [],
                    "failed": [],
                    "excluded": [],
                },
                "policy_version": "memory.v1",
            }

    msg = SimpleNamespace(
        id=message_id,
        tenant_id=tenant,
        dossier_id=dossier,
        conversation_id=conversation,
        role="user",
        status="queued",
        content_text="pregunta adversaria",
        answer_payload={},
        coverage_manifest={},
        error_code=None,
        error_message=None,
        background_job_id=None,
    )
    job = SimpleNamespace(
        id=uuid.uuid4(),
        cancel_requested=False,
        correlation_id="corr-adv-1",
        attempt_count=1,
    )

    session = MagicMock()
    session.scalars = MagicMock(
        side_effect=AssertionError("legacy inline DMP query must not be used")
    )
    session.get = MagicMock(return_value=None)
    session.scalar = MagicMock(return_value=None)
    session.flush = MagicMock()
    session.add = MagicMock()
    session.refresh = MagicMock()

    monkeypatch.setattr(conv, "get_message", lambda *a, **k: msg)
    monkeypatch.setattr(conv, "append_audit_event", lambda *a, **k: None)
    monkeypatch.setattr(conv, "_signal_ai_enabled", lambda: False)
    monkeypatch.setattr(
        "opn_oracle.integrations.memory_ask_dual.load_oracle_authority_from_session",
        lambda *a, **k: {
            "dossier_id": str(dossier),
            "tenant_id": str(tenant),
            "question": "q",
            "intent": None,
            "requirements": [],
            "objectives": [],
            "decisions": [],
            "oracle_evidence": [],
        },
    )
    monkeypatch.setattr(
        "opn_oracle.integrations.memory_ask_dual.persist_memory_signal_evidence",
        lambda *a, **k: {},
    )
    monkeypatch.setattr(
        "opn_oracle.integrations.memory_ask_dual.load_dossier_citable_evidence_ids",
        lambda *a, **k: set(),
    )
    monkeypatch.setattr(
        "opn_oracle.integrations.memory_ask_dual.load_existing_memory_signal_mappings",
        lambda *a, **k: {},
    )

    def _resolve(sess: Any, *, tenant_id: uuid.UUID, dossier_id: uuid.UUID) -> Any:
        from opn_oracle.integrations.memory_profile import EffectiveMemoryResolution

        return EffectiveMemoryResolution(
            mode="disabled",
            profile_id=str(profile.id),
            version=4,
            scope_type="dossier",
            resolution_source=RESOLUTION_DEFAULT_PROFILE,
            persisted=True,
            state="active",
            profile_config=dict(profile.profile_config),
            row=profile,
        )

    monkeypatch.setattr(
        "opn_oracle.integrations.memory_profile.resolve_effective_dossier_memory_profile",
        _resolve,
    )

    adapter = CountingAdapter()
    with tenant_context(TenantContext(tenant_id=tenant, actor_id=uuid.uuid4())):
        result = conv.process_dossier_question_answer(
            session,
            {
                "message_id": str(message_id),
                "conversation_id": str(conversation),
                "dossier_id": str(dossier),
                "memory_mode": "augment",  # adversarial client force
            },
            job,  # type: ignore[arg-type]
            memory_adapter=adapter,
            # no memory_mode kwarg — production path
        )

    assert result["memory_mode"] == "disabled"
    assert result["memory_profile_id"] == str(profile.id)
    assert result["memory_profile_version"] == 4
    assert result["memory_scope_type"] == "dossier"
    assert result["resolution_source"] == RESOLUTION_DEFAULT_PROFILE
    assert result["item_count"] == 0
    assert msg.answer_payload.get("memory_mode") == "disabled"
    assert msg.answer_payload.get("memory_profile_id") == str(profile.id)
    assert msg.answer_payload.get("resolution_source") == RESOLUTION_DEFAULT_PROFILE
    # Adapter may be called with mode=disabled (0 items) — never with augment from payload.
    if CountingAdapter.calls:
        pass  # retrieve with disabled is ok; scope assert above gates mode


@pytest.mark.unit
def test_adversary_legacy_payload_augment_zero_memory(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant = uuid.uuid4()
    dossier = uuid.uuid4()
    conversation = uuid.uuid4()
    message_id = uuid.uuid4()

    class ZeroAdapter:
        effective_mode = "augment"

        def retrieve(self, scope: Any, query: str, purpose: str, limit: int) -> dict[str, Any]:
            assert scope.get("mode") == "disabled"
            return {
                "items": [],
                "items_for_prompt": [],
                "items_observed": [],
                "coverage_manifest": {
                    "requested": [],
                    "used": [],
                    "failed": [],
                    "excluded": [],
                },
                "policy_version": "disabled",
            }

    msg = SimpleNamespace(
        id=message_id,
        tenant_id=tenant,
        dossier_id=dossier,
        conversation_id=conversation,
        role="user",
        status="queued",
        content_text="legacy q",
        answer_payload={},
        coverage_manifest={},
        error_code=None,
        error_message=None,
        background_job_id=None,
    )
    job = SimpleNamespace(
        id=uuid.uuid4(),
        cancel_requested=False,
        correlation_id="corr-legacy",
        attempt_count=1,
    )
    session = MagicMock()
    session.get = MagicMock(return_value=None)
    session.scalar = MagicMock(return_value=None)
    session.flush = MagicMock()
    session.add = MagicMock()
    session.refresh = MagicMock()

    monkeypatch.setattr(conv, "get_message", lambda *a, **k: msg)
    monkeypatch.setattr(conv, "append_audit_event", lambda *a, **k: None)
    monkeypatch.setattr(conv, "_signal_ai_enabled", lambda: False)
    monkeypatch.setattr(
        "opn_oracle.integrations.memory_ask_dual.load_oracle_authority_from_session",
        lambda *a, **k: {
            "dossier_id": str(dossier),
            "tenant_id": str(tenant),
            "question": "q",
            "intent": None,
            "requirements": [],
            "objectives": [],
            "decisions": [],
            "oracle_evidence": [],
        },
    )
    monkeypatch.setattr(
        "opn_oracle.integrations.memory_ask_dual.persist_memory_signal_evidence",
        lambda *a, **k: {},
    )
    monkeypatch.setattr(
        "opn_oracle.integrations.memory_ask_dual.load_dossier_citable_evidence_ids",
        lambda *a, **k: set(),
    )
    monkeypatch.setattr(
        "opn_oracle.integrations.memory_ask_dual.load_existing_memory_signal_mappings",
        lambda *a, **k: {},
    )

    def _resolve(sess: Any, *, tenant_id: uuid.UUID, dossier_id: uuid.UUID) -> Any:
        from opn_oracle.integrations.memory_profile import EffectiveMemoryResolution

        return EffectiveMemoryResolution(
            mode="disabled",
            profile_id=None,
            version=None,
            scope_type="dossier",
            resolution_source=RESOLUTION_LEGACY_MISSING,
            persisted=False,
            state="legacy_missing",
            profile_config={},
            row=None,
        )

    monkeypatch.setattr(
        "opn_oracle.integrations.memory_profile.resolve_effective_dossier_memory_profile",
        _resolve,
    )

    with tenant_context(TenantContext(tenant_id=tenant, actor_id=uuid.uuid4())):
        result = conv.process_dossier_question_answer(
            session,
            {
                "message_id": str(message_id),
                "conversation_id": str(conversation),
                "dossier_id": str(dossier),
                "memory_mode": "augment",
            },
            job,  # type: ignore[arg-type]
            memory_adapter=ZeroAdapter(),
        )

    assert result["memory_mode"] == "disabled"
    assert result["memory_profile_id"] is None
    assert result["resolution_source"] == RESOLUTION_LEGACY_MISSING
    assert result["item_count"] == 0
    assert msg.answer_payload.get("memory_mode") == "disabled"


@pytest.mark.unit
def test_put_body_connection_id_does_not_create_parallel_profile(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _authenticated_http_probe(
        app, monkeypatch, frozenset({"dossier.read", "dossier.write"})
    ) as (_user, tenant_id):
        dossier = _dossier(tenant_id)
        row = _profile_row(tenant_id=tenant_id, dossier_id=dossier.id, mode="disabled", version=1)
        conn_id = uuid.uuid4()
        session = _FakeSession(
            dossier=dossier,
            profile=row,
            connection=SimpleNamespace(
                id=conn_id,
                tenant_id=tenant_id,
                provider="signal-avanza",
                status="active",
            ),
        )
        _wire_session(monkeypatch, session)
        resp = client.put(
            f"/api/v1/dossiers/{dossier.id}/memory/profile",
            json={
                "mode": "shadow",
                "connection_id": str(conn_id),
                "reason": "try-spawn-parallel",
            },
            headers={"If-Match": row.etag},
        )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["mode"] == "shadow"
    assert body["connection_id"] is None
    assert body.get("ignored_body_connection_id") is True
    # Only the existing default row was updated — no second add with connection.
    assert row.connection_id is None
    assert row.mode == "shadow"
    assert session.commits == 1
    assert len(session.extra_profiles) == 0


@pytest.mark.unit
def test_effective_endpoint_shares_resolution(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _authenticated_http_probe(app, monkeypatch, frozenset({"dossier.read"})) as (
        _user,
        tenant_id,
    ):
        dossier = _dossier(tenant_id)
        default = _profile_row(
            tenant_id=tenant_id, dossier_id=dossier.id, mode="disabled", version=2
        )
        override = _profile_row(
            tenant_id=tenant_id,
            dossier_id=dossier.id,
            mode="augment",
            version=1,
            connection_id=uuid.uuid4(),
        )
        session = _FakeSession(dossier=dossier, profile=default, extra_profiles=[override])
        _wire_session(monkeypatch, session)

        def _resolve(sess: Any, *, tenant_id: uuid.UUID, dossier_id: uuid.UUID) -> Any:
            from opn_oracle.integrations.memory_profile import EffectiveMemoryResolution

            return EffectiveMemoryResolution(
                mode="disabled",
                profile_id=str(default.id),
                version=2,
                scope_type="dossier",
                resolution_source=RESOLUTION_DEFAULT_PROFILE,
                persisted=True,
                state="active",
                profile_config=dict(default.profile_config),
                row=default,
                deferred_connection_profile_count=1,
                deferred_connection_profiles=[
                    {
                        "id": str(override.id),
                        "connection_id": str(override.connection_id),
                        "mode": "augment",
                        "version": 1,
                        "status": "deferred_connection_override",
                        "product_supported": False,
                    }
                ],
            )

        monkeypatch.setattr(
            memory_routes,
            "resolve_effective_dossier_memory_profile",
            _resolve,
        )
        resp = client.get(f"/api/v1/dossiers/{dossier.id}/memory/effective")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["mode"] == "disabled"
    assert body["resolution_source"] == RESOLUTION_DEFAULT_PROFILE
    assert body["effective_profile"]["mode"] == "disabled"
    assert body["effective_profile"]["version"] == 2
    assert body["configured_profile"]["mode"] == "disabled"
    assert body["deferred_connection_profile_count"] == 1
    assert body["capability"]["publisher_reliable"] is body["publisher_reliable"]
