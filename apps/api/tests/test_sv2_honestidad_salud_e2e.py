"""SV2-HONESTIDAD-SALUD-E2E · single source of truth for public memory health.

Endpoint-level contract for GET /dossiers/<id>/memory/effective:

- top-level publisher_reliable never contradicts nested capability
- MEMORY_CONTEXT_MODE=disabled → degraded for defaults and persisted profiles
- host http (healthy) → reliable for defaults and persisted profiles
- profile GET/PUT do not invent host health
- recursive absence of internal accounting fields

Regression (fails on base 9cfb529): disabled defaults returned
top_level=true / nested=false because profile defaults hard-coded True.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import pytest
from flask import g

from opn_oracle.auth import permissions
from opn_oracle.integrations import memory_routes
from opn_oracle.integrations.memory_profile import profile_to_public
from opn_oracle.integrations.memory_routes import _effective_defaults
from opn_oracle.platform.models import User

_MDEV_RE = re.compile(r"(RACE|DB|SEC|MIG)-MDEV")
_FORBIDDEN_KEYS = frozenset({"deferred_blockers", "actions_reliable", "missing_anchors", "path"})


def _assert_public_clean(payload: object, *, path: str = "$") -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            assert key not in _FORBIDDEN_KEYS, f"{path}.{key} no debe ser público"
            assert not _MDEV_RE.search(str(key)), f"clave MDEV en {path}.{key}"
            if isinstance(value, str):
                assert not _MDEV_RE.search(value), f"código MDEV en {path}.{key}"
            _assert_public_clean(value, path=f"{path}.{key}")
    elif isinstance(payload, list):
        for i, item in enumerate(payload):
            _assert_public_clean(item, path=f"{path}[{i}]")


def _assert_health_coherent(body: dict[str, Any]) -> None:
    """Top-level health projected from nested capability — no divergence allowed."""
    assert "capability" in body and isinstance(body["capability"], dict)
    cap = body["capability"]
    assert "publisher_reliable" in body
    assert body["publisher_reliable"] is cap["publisher_reliable"], (
        f"contradiction: top_level={body['publisher_reliable']!r} "
        f"nested={cap['publisher_reliable']!r}"
    )
    if "publisher_status" in body:
        assert body["publisher_status"] == cap["publisher_status"]
    if "message" in body:
        assert body["message"] == cap["message"]


@contextmanager
def _authenticated_http_probe(
    app: Any,
    monkeypatch: pytest.MonkeyPatch,
    allowed_permissions: frozenset[str],
) -> Iterator[tuple[User, uuid.UUID]]:
    actor = User(
        id=uuid.uuid4(),
        email="salud-e2e@example.com",
        display_name="Salud E2E",
        status="active",
    )
    tid = uuid.uuid4()
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
    ) -> None:
        self.dossier = dossier
        self.profile = profile
        self.commits = 0
        self.added: list[Any] = []

    def scalar(self, _q: Any) -> Any:
        return self.dossier

    def add(self, obj: Any) -> None:
        self.added.append(obj)

    def commit(self) -> None:
        self.commits += 1


def _dossier(tenant_id: uuid.UUID) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        owner_user_id=None,
        title="Salud E2E dossier",
    )


def _persisted_profile(tenant_id: uuid.UUID, dossier_id: uuid.UUID) -> SimpleNamespace:
    now = datetime.now(UTC)
    return SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        connection_id=None,
        mode="augment",
        version=2,
        etag='W/"dmp-v2-test"',
        profile_config={
            "mode": "augment",
            "sources": ["document"],
            "kinds": ["fact"],
            "classifications_allowed": ["public"],
            "token_budget": 4000,
            "limit": 20,
            "status": "active",
            "provenance": "tenant_default",
        },
        last_test_at=now,
        last_test_status="ok",
        last_error=None,
        last_coverage={"used": 1},
        updated_at=now,
    )


def _wire(monkeypatch: pytest.MonkeyPatch, session: _FakeSession) -> None:
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
        return session.profile

    monkeypatch.setattr(memory_routes, "_load_profile", load_profile)


def _get_effective(
    app: Any,
    client: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    host_mode: str,
    profile: Any | None,
) -> dict[str, Any]:
    app.config["MEMORY_CONTEXT_MODE"] = host_mode
    with _authenticated_http_probe(app, monkeypatch, frozenset({"dossier.read"})) as (
        _user,
        tenant_id,
    ):
        dossier = _dossier(tenant_id)
        if profile is not None:
            profile.tenant_id = tenant_id
            profile.dossier_id = dossier.id
        session = _FakeSession(dossier=dossier, profile=profile)
        _wire(monkeypatch, session)
        resp = client.get(f"/api/v1/dossiers/{dossier.id}/memory/effective")
    assert resp.status_code == 200, resp.get_json()
    body = resp.get_json()
    assert isinstance(body, dict)
    return body


# ---------------------------------------------------------------------------
# Regression: must FAIL on base 9cfb529 (top_level=true / nested=false)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_effective_disabled_defaults_no_top_level_nested_contradiction(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fails on 9cfb529: top_level=True while capability.publisher_reliable=False."""
    body = _get_effective(app, client, monkeypatch, host_mode="disabled", profile=None)
    assert body["persisted"] is False
    top = body.get("publisher_reliable")
    nested = body.get("capability", {}).get("publisher_reliable")
    # Exact bug shape on base SHA — must not reappear:
    assert not (top is True and nested is False), (
        f"regresión 000150: top_level={top!r} / nested={nested!r}"
    )
    assert top is False
    assert nested is False
    _assert_health_coherent(body)
    _assert_public_clean(body)


# ---------------------------------------------------------------------------
# Four contract cases: defaults/persisted x disabled/http
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_effective_disabled_defaults_degraded(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = _get_effective(app, client, monkeypatch, host_mode="disabled", profile=None)
    assert body["persisted"] is False
    assert body["publisher_reliable"] is False
    assert body["capability"]["host_mode"] == "disabled"
    assert body["capability"]["publisher_reliable"] is False
    assert body["capability"]["publisher_status"] == "unavailable"
    _assert_health_coherent(body)
    _assert_public_clean(body)


@pytest.mark.unit
def test_effective_disabled_persisted_degraded(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = _persisted_profile(uuid.uuid4(), uuid.uuid4())
    body = _get_effective(app, client, monkeypatch, host_mode="disabled", profile=profile)
    assert body["persisted"] is True
    assert body["mode"] == "augment"
    assert body["publisher_reliable"] is False
    assert body["capability"]["publisher_reliable"] is False
    _assert_health_coherent(body)
    _assert_public_clean(body)


@pytest.mark.unit
def test_effective_http_defaults_healthy(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    body = _get_effective(app, client, monkeypatch, host_mode="http", profile=None)
    assert body["persisted"] is False
    assert body["publisher_reliable"] is True
    assert body["capability"]["host_mode"] == "http"
    assert body["capability"]["publisher_reliable"] is True
    assert body["capability"]["publisher_status"] == "ok"
    _assert_health_coherent(body)
    _assert_public_clean(body)


@pytest.mark.unit
def test_effective_http_persisted_healthy(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    profile = _persisted_profile(uuid.uuid4(), uuid.uuid4())
    body = _get_effective(app, client, monkeypatch, host_mode="http", profile=profile)
    assert body["persisted"] is True
    assert body["mode"] == "augment"
    assert body["publisher_reliable"] is True
    assert body["capability"]["publisher_reliable"] is True
    _assert_health_coherent(body)
    _assert_public_clean(body)


# ---------------------------------------------------------------------------
# Profile endpoints: do not claim host health they do not know
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_profile_get_and_put_do_not_claim_publisher_reliable(
    app: Any, client: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    app.config["MEMORY_CONTEXT_MODE"] = "disabled"
    with _authenticated_http_probe(
        app, monkeypatch, frozenset({"dossier.read", "dossier.write"})
    ) as (_user, tenant_id):
        dossier = _dossier(tenant_id)
        session = _FakeSession(dossier=dossier)
        _wire(monkeypatch, session)
        monkeypatch.setattr(memory_routes, "append_audit_event", lambda *a, **k: None)
        get = client.get(f"/api/v1/dossiers/{dossier.id}/memory/profile")
        assert get.status_code == 200
        get_body = get.get_json()
        assert "publisher_reliable" not in get_body
        assert "capability" not in get_body
        _assert_public_clean(get_body)

        put = client.put(
            f"/api/v1/dossiers/{dossier.id}/memory/profile",
            json={"mode": "shadow"},
            headers={"If-Match": get_body["etag"]},
        )
        assert put.status_code == 200, put.get_json()
        put_body = put.get_json()
        assert "publisher_reliable" not in put_body
        assert put_body["persisted"] is True
        _assert_public_clean(put_body)


@pytest.mark.unit
def test_profile_helpers_do_not_invent_health() -> None:
    defaults = _effective_defaults(
        tenant_id=uuid.uuid4(), dossier_id=uuid.uuid4(), connection_id=None
    )
    assert "publisher_reliable" not in defaults
    row = _persisted_profile(uuid.uuid4(), uuid.uuid4())
    pub = profile_to_public(row)
    assert "publisher_reliable" not in pub
    _assert_public_clean(defaults)
    _assert_public_clean(pub)
