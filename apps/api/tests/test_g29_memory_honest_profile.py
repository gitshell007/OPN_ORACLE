"""G-29 unit/API: explicit honest DossierMemoryProfile on new dossiers."""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from types import SimpleNamespace
from typing import Any

import pytest
from flask import g

from opn_oracle.auth import permissions
from opn_oracle.integrations import memory_routes
from opn_oracle.integrations.memory_context import capability_payload
from opn_oracle.integrations.memory_profile import (
    OPERATIONAL_MODES,
    SERVER_DEFAULT_MEMORY_MODE,
    create_dossier_memory_profile,
    default_profile_payload,
    legacy_missing_payload,
    memory_scope_payload,
    profile_config_fingerprint,
    profile_to_public,
)
from opn_oracle.platform.models import User


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
        email="g29-memory@example.com",
        display_name="G29 Memory",
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
        fail_on_add_memory: bool = False,
    ) -> None:
        self.dossier = dossier
        self.profile = profile
        self.connection = connection
        self.added: list[Any] = []
        self.commits = 0
        self.rollbacks = 0
        self.fail_on_add_memory = fail_on_add_memory
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
        if self.fail_on_add_memory and obj.__class__.__name__ == "DossierMemoryProfile":
            raise RuntimeError("simulated memory profile insert failure")
        self.added.append(obj)
        if obj.__class__.__name__ == "DossierMemoryProfile":
            self.profile = obj

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


def _dossier(tenant_id: uuid.UUID, dossier_id: uuid.UUID | None = None) -> SimpleNamespace:
    return SimpleNamespace(
        id=dossier_id or uuid.uuid4(),
        tenant_id=tenant_id,
        owner_user_id=None,
        title="G29 Mem dossier",
    )


def _profile_row(
    *,
    tenant_id: uuid.UUID,
    dossier_id: uuid.UUID,
    mode: str = "disabled",
    version: int = 1,
) -> SimpleNamespace:
    cfg = default_profile_payload(mode=mode, provenance="server_policy_on_create")
    from opn_oracle.integrations.memory_profile import _etag

    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        connection_id=None,
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
        if session.profile is None:
            return None
        if session.profile.tenant_id != tenant_id or session.profile.dossier_id != dossier_id:
            return None
        if connection_id is None and session.profile.connection_id is not None:
            return None
        if connection_id is not None and session.profile.connection_id != connection_id:
            return None
        return session.profile

    monkeypatch.setattr(memory_routes, "_load_profile", load_profile)

    def capture_audit(sess: Any, **kwargs: Any) -> None:
        session.audit_events.append(kwargs)

    monkeypatch.setattr(memory_routes, "append_audit_event", capture_audit)


@pytest.mark.unit
def test_server_default_is_disabled_operational_modes() -> None:
    assert SERVER_DEFAULT_MEMORY_MODE == "disabled"
    assert frozenset({"disabled", "shadow", "augment"}) == OPERATIONAL_MODES
    scope = memory_scope_payload(dossier_id=uuid.uuid4(), mode="augment")
    assert scope["dossier_only"] is True
    assert scope["uses_tenant_curated"] is False
    assert scope["uses_global_memory"] is False
    assert scope["cross_tenant"] is False
    assert "other_dossiers" in scope["exclusions"]


@pytest.mark.unit
def test_capability_payload_honest_scope() -> None:
    cap = capability_payload(host_mode="disabled", connection_healthy=False)
    assert cap["scope_type"] == "dossier"
    assert cap["dossier_only"] is True
    assert cap["uses_global_memory"] is False
    assert cap["uses_tenant_curated"] is False
    assert cap["cross_tenant"] is False
    assert "disabled" in cap["available_modes"]
    assert "tenant_curated" not in cap["available_modes"]


@pytest.mark.unit
def test_legacy_missing_payload_readonly() -> None:
    tid, did = uuid.uuid4(), uuid.uuid4()
    body = legacy_missing_payload(tenant_id=tid, dossier_id=did, connection_id=None)
    assert body["status"] == "legacy_missing"
    assert body["persisted"] is False
    assert body["mode"] == "disabled"
    assert body["config_source"] == "legacy_missing"


@pytest.mark.unit
def test_put_rejects_forced_tenant(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _authenticated_http_probe(
        app, monkeypatch, frozenset({"dossier.read", "dossier.write"})
    ) as (_user, tenant_id):
        dossier = _dossier(tenant_id)
        row = _profile_row(tenant_id=tenant_id, dossier_id=dossier.id)
        session = _FakeSession(dossier=dossier, profile=row)
        _wire_session(monkeypatch, session)
        resp = client.put(
            f"/api/v1/dossiers/{dossier.id}/memory/profile",
            json={"mode": "shadow", "tenant_id": str(uuid.uuid4())},
            headers={"If-Match": row.etag},
        )
    assert resp.status_code == 422
    assert resp.get_json()["code"] == "schema_validation_failed"


@pytest.mark.unit
def test_put_stale_version_409(app: Any, client: Any, monkeypatch: pytest.MonkeyPatch) -> None:
    with _authenticated_http_probe(
        app, monkeypatch, frozenset({"dossier.read", "dossier.write"})
    ) as (_user, tenant_id):
        dossier = _dossier(tenant_id)
        row = _profile_row(tenant_id=tenant_id, dossier_id=dossier.id, version=2)
        session = _FakeSession(dossier=dossier, profile=row)
        _wire_session(monkeypatch, session)
        resp = client.put(
            f"/api/v1/dossiers/{dossier.id}/memory/profile",
            json={"mode": "shadow", "expected_version": 1},
            headers={"If-Match": row.etag},
        )
    assert resp.status_code == 409
    assert resp.get_json()["code"] == "version_conflict"
    assert session.commits == 0


@pytest.mark.unit
def test_put_identical_retry_no_version_bump(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _authenticated_http_probe(
        app, monkeypatch, frozenset({"dossier.read", "dossier.write"})
    ) as (_user, tenant_id):
        dossier = _dossier(tenant_id)
        row = _profile_row(tenant_id=tenant_id, dossier_id=dossier.id, mode="shadow", version=3)
        session = _FakeSession(dossier=dossier, profile=row)
        _wire_session(monkeypatch, session)
        cfg = dict(row.profile_config)
        resp = client.put(
            f"/api/v1/dossiers/{dossier.id}/memory/profile",
            json={
                "mode": "shadow",
                "sources": cfg["sources"],
                "kinds": cfg["kinds"],
                "classifications_allowed": cfg["classifications_allowed"],
                "token_budget": cfg["token_budget"],
                "limit": cfg["limit"],
                "expected_version": 3,
            },
            headers={"If-Match": row.etag},
        )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["version"] == 3
    assert body.get("idempotent_replay") is True
    assert session.commits == 0
    assert session.audit_events == []


@pytest.mark.unit
def test_put_updates_with_audit(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _authenticated_http_probe(
        app, monkeypatch, frozenset({"dossier.read", "dossier.write"})
    ) as (_user, tenant_id):
        dossier = _dossier(tenant_id)
        row = _profile_row(tenant_id=tenant_id, dossier_id=dossier.id, mode="disabled", version=1)
        session = _FakeSession(dossier=dossier, profile=row)
        _wire_session(monkeypatch, session)
        resp = client.put(
            f"/api/v1/dossiers/{dossier.id}/memory/profile",
            json={"mode": "augment", "reason": "g29-unit"},
            headers={"If-Match": row.etag},
        )
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert body["mode"] == "augment"
    assert body["version"] == 2
    assert body["scope"]["dossier_only"] is True
    assert session.commits == 1
    assert len(session.audit_events) == 1
    assert session.audit_events[0]["action"] == "dossier.memory_profile.update"
    assert session.audit_events[0]["metadata"]["before"]["mode"] == "disabled"
    assert session.audit_events[0]["metadata"]["after"]["mode"] == "augment"
    assert session.audit_events[0]["metadata"]["actor_reason"] == "g29-unit"


@pytest.mark.unit
def test_materialize_idempotent(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _authenticated_http_probe(
        app, monkeypatch, frozenset({"dossier.read", "dossier.write"})
    ) as (_user, tenant_id):
        dossier = _dossier(tenant_id)
        session = _FakeSession(dossier=dossier)
        _wire_session(monkeypatch, session)
        first = client.post(
            f"/api/v1/dossiers/{dossier.id}/memory/profile/materialize",
            json={"reason": "g29-materialize"},
        )
        assert first.status_code == 201, first.get_json()
        assert first.get_json()["materialized"] is True
        assert first.get_json()["mode"] == "disabled"
        assert session.commits == 1
        # Second call reuses existing profile.
        second = client.post(
            f"/api/v1/dossiers/{dossier.id}/memory/profile/materialize",
            json={"reason": "g29-materialize-again"},
        )
    assert second.status_code == 200
    assert second.get_json()["idempotent_replay"] is True
    assert second.get_json()["materialized"] is False
    assert session.commits == 1  # no second commit


@pytest.mark.unit
def test_get_persisted_profile_public_scope(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _authenticated_http_probe(app, monkeypatch, frozenset({"dossier.read"})) as (
        _user,
        tenant_id,
    ):
        dossier = _dossier(tenant_id)
        row = _profile_row(tenant_id=tenant_id, dossier_id=dossier.id, mode="shadow")
        session = _FakeSession(dossier=dossier, profile=row)
        _wire_session(monkeypatch, session)
        resp = client.get(f"/api/v1/dossiers/{dossier.id}/memory/profile")
    body = resp.get_json()
    assert resp.status_code == 200
    assert body["persisted"] is True
    assert body["mode"] == "shadow"
    assert body["scope"]["scope_type"] == "dossier"
    assert body["available_modes"] == sorted(OPERATIONAL_MODES)


@pytest.mark.unit
def test_create_dossier_memory_profile_helper_uses_server_policy() -> None:
    class Sess:
        def __init__(self) -> None:
            self.added: list[Any] = []

        def add(self, obj: Any) -> None:
            self.added.append(obj)

    sess = Sess()
    tid, did = uuid.uuid4(), uuid.uuid4()
    row = create_dossier_memory_profile(sess, tenant_id=tid, dossier_id=did)  # type: ignore[arg-type]
    assert row.mode == "disabled"
    assert row.version == 1
    assert row.profile_config["config_source"] == "server_policy"
    assert row.profile_config["provenance"] == "server_policy_on_create"
    assert len(sess.added) == 1


@pytest.mark.unit
def test_profile_to_public_never_claims_global() -> None:
    row = _profile_row(tenant_id=uuid.uuid4(), dossier_id=uuid.uuid4(), mode="augment")
    pub = profile_to_public(row)
    assert pub["scope"]["uses_global_memory"] is False
    assert pub["scope"]["uses_tenant_curated"] is False


@pytest.mark.unit
def test_fingerprint_equality() -> None:
    a = profile_config_fingerprint(default_profile_payload(mode="disabled"), "disabled")
    b = profile_config_fingerprint(default_profile_payload(mode="disabled"), "disabled")
    assert a == b
    c = profile_config_fingerprint(default_profile_payload(mode="shadow"), "shadow")
    assert a != c


@pytest.mark.unit
def test_capability_endpoint_honest(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    with _authenticated_http_probe(app, monkeypatch, frozenset({"dossier.read"})):
        resp = client.get("/api/v1/memory/capability")
    assert resp.status_code == 200
    body = resp.get_json()
    assert body["dossier_only"] is True
    assert body["uses_global_memory"] is False
    assert body["uses_tenant_curated"] is False
