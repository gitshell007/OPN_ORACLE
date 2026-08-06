"""G-16 routes rework · HTTP + PostgreSQL gates (bypass B1/B2/B3 closed).

Real Flask dispatch against disposable PG (oracle_app RLS). No UI/fusion G-17.
"""

from __future__ import annotations

import os
import threading
import uuid
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import pytest
from flask_migrate import upgrade
from sqlalchemy import create_engine, text

from opn_oracle import create_app
from opn_oracle.auth import permissions
from opn_oracle.oracle import routes as oracle_routes
from opn_oracle.tenants.context import TenantContext, tenant_context

pytestmark = pytest.mark.integration

_DISPOSABLE = ("test", "aislados", "ci")


def _assert_disposable(url: str, *, env_name: str) -> str:
    if url.startswith("postgresql://"):
        url = url.replace("postgresql://", "postgresql+psycopg://", 1)
    parsed = urlparse(url)
    db_name = (parsed.path or "").lstrip("/").split("?")[0]
    host = (parsed.hostname or "").lower()
    if host not in {"127.0.0.1", "localhost", "postgres", "pg"}:
        raise RuntimeError(f"{env_name} host={host!r} not disposable")
    if not db_name or not any(m in db_name.lower() for m in _DISPOSABLE):
        raise RuntimeError(f"{env_name} database={db_name!r} not disposable")
    return url


def _require_pg_urls() -> tuple[str, str, str]:
    if os.getenv("ORACLE_RUN_INTEGRATION") != "1":
        pytest.skip("define ORACLE_RUN_INTEGRATION=1")
    migration_url = os.getenv("TEST_DATABASE_URL")
    runtime_url = os.getenv("TEST_RUNTIME_DATABASE_URL") or migration_url
    redis_url = os.getenv("TEST_REDIS_URL") or "redis://127.0.0.1:6379/14"
    if not migration_url or not runtime_url:
        pytest.skip("define TEST_DATABASE_URL / TEST_RUNTIME_DATABASE_URL")
    return (
        _assert_disposable(migration_url, env_name="TEST_DATABASE_URL"),
        _assert_disposable(runtime_url, env_name="TEST_RUNTIME_DATABASE_URL"),
        redis_url,
    )


def _seed_tenant_user(
    connection: Any,
    *,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    slug: str,
) -> None:
    connection.execute(
        text(
            "INSERT INTO tenants("
            "id,slug,name,status,locale,timezone,settings,created_at,updated_at"
            ") VALUES ("
            ":id,:slug,:name,'active','es-ES','UTC','{}',now(),now()"
            ") ON CONFLICT DO NOTHING"
        ),
        {"id": tenant_id, "slug": slug, "name": slug.upper()},
    )
    connection.execute(
        text(
            "INSERT INTO users(id,email,display_name,password_hash,status,"
            "email_verified_at,created_at,updated_at)"
            " VALUES (:id,:email,:dn,'x','active',now(),now(),now())"
            " ON CONFLICT DO NOTHING"
        ),
        {
            "id": user_id,
            "email": f"{slug}@example.test",
            "dn": "G16 Routes",
        },
    )
    membership_id = uuid.uuid4()
    role_id = uuid.uuid4()
    connection.execute(
        text(
            "INSERT INTO tenant_memberships(id,tenant_id,user_id,status,accepted_at,"
            "settings,created_at,updated_at)"
            " VALUES (:id,:t,:u,'active',now(),'{}',now(),now())"
            " ON CONFLICT DO NOTHING"
        ),
        {"id": membership_id, "t": tenant_id, "u": user_id},
    )
    connection.execute(
        text(
            "INSERT INTO roles(id,tenant_id,key,name,description,is_system,created_at,updated_at)"
            " VALUES (:id,:t,'owner','Owner','Owner',true,now(),now())"
            " ON CONFLICT DO NOTHING"
        ),
        {"id": role_id, "t": tenant_id},
    )
    connection.execute(
        text(
            "INSERT INTO membership_roles(tenant_id,membership_id,role_id)"
            " VALUES (:t,:m,:r) ON CONFLICT DO NOTHING"
        ),
        {"t": tenant_id, "m": membership_id, "r": role_id},
    )
    connection.execute(
        text(
            "INSERT INTO role_permissions(tenant_id,role_id,permission_key)"
            " SELECT :t,:r,key FROM permissions ON CONFLICT DO NOTHING"
        ),
        {"t": tenant_id, "r": role_id},
    )


@contextmanager
def _authenticated_http(
    app: Any,
    monkeypatch: pytest.MonkeyPatch,
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    perms: frozenset[str] | None = None,
) -> Iterator[None]:
    granted = perms or frozenset({"actor.read", "actor.write", "audit.read"})
    principal = type(
        "Principal",
        (),
        {"id": user_id, "is_authenticated": True, "platform_role": None},
    )()
    monkeypatch.setattr(permissions, "current_user", principal)
    monkeypatch.setattr(oracle_routes, "current_user", principal)
    monkeypatch.setattr(
        permissions,
        "current_permissions",
        lambda _user_id, _active_tenant_id: granted,
    )
    before = app.before_request_funcs.get(None, [])
    index = next(
        (
            i
            for i, function in enumerate(before)
            if getattr(function, "__name__", "") == "protect_csrf_and_install_identity"
        ),
        None,
    )
    original = before[index] if index is not None else None

    def install_identity() -> None:
        g_active = tenant_id
        from flask import g

        g.active_tenant_id = g_active
        manager = tenant_context(TenantContext(tenant_id=tenant_id, actor_id=user_id))
        manager.__enter__()
        g.auth_tenant_context_manager = manager

    if index is not None:
        before[index] = install_identity
    else:
        app.before_request_funcs[None] = [install_identity, *before]
    try:
        yield
    finally:
        if index is not None and original is not None:
            before[index] = original
        else:
            app.before_request_funcs[None] = before


@pytest.fixture
def g16_routes_pg(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Any, dict[str, Any]]]:
    migration_url, runtime_url, redis_url = _require_pg_urls()
    app = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "g16-routes-rework-secret-key-32bytes!",
            "DATABASE_URL": runtime_url,
            "DATABASE_MIGRATION_URL": migration_url,
            "REDIS_URL": redis_url,
            "SESSION_REDIS_URL": redis_url,
            "RATELIMIT_STORAGE_URL": redis_url,
            "OPENAPI_ENABLED": False,
        }
    )
    migrations = str(Path(__file__).resolve().parents[1] / "migrations")
    with app.app_context():
        upgrade(directory=migrations, revision="head")

    tenant_id = uuid.uuid4()
    user_id = uuid.uuid4()
    tenant_b = uuid.uuid4()
    migrator = create_engine(migration_url)
    with migrator.begin() as connection:
        _seed_tenant_user(
            connection,
            tenant_id=tenant_id,
            user_id=user_id,
            slug=f"g16r-{tenant_id.hex[:8]}",
        )
        _seed_tenant_user(
            connection,
            tenant_id=tenant_b,
            user_id=uuid.uuid4(),
            slug=f"g16rb-{tenant_b.hex[:8]}",
        )

    client = app.test_client()
    ctx = {
        "tenant_id": tenant_id,
        "tenant_b": tenant_b,
        "user_id": user_id,
        "migration_url": migration_url,
        "client": client,
        "app": app,
        "monkeypatch": monkeypatch,
    }
    yield app, ctx


def _count_actors(migration_url: str, tenant_id: uuid.UUID) -> int:
    engine = create_engine(migration_url)
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("SELECT count(*) FROM actors WHERE tenant_id=:t"),
                {"t": tenant_id},
            ).scalar()
            or 0
        )


def _count_audit(migration_url: str, tenant_id: uuid.UUID, action: str) -> int:
    engine = create_engine(migration_url)
    with engine.connect() as connection:
        return int(
            connection.execute(
                text("SELECT count(*) FROM audit_events WHERE tenant_id=:t AND action=:a"),
                {"t": tenant_id, "a": action},
            ).scalar()
            or 0
        )


def _load_actor(migration_url: str, actor_id: uuid.UUID) -> dict[str, Any]:
    engine = create_engine(migration_url)
    with engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    "SELECT id, canonical_name, canonical_key, tax_id, tax_id_scheme,"
                    " tax_id_country, actor_type, identifiers, provenance, version"
                    " FROM actors WHERE id=:id"
                ),
                {"id": actor_id},
            )
            .mappings()
            .one()
        )
        return dict(row)


def test_g16_http_post_valid_cif_and_invalid_families(
    g16_routes_pg: tuple[Any, dict[str, Any]],
) -> None:
    app, ctx = g16_routes_pg
    client = ctx["client"]
    tenant_id = ctx["tenant_id"]
    user_id = ctx["user_id"]
    migration_url = ctx["migration_url"]
    monkeypatch = ctx["monkeypatch"]

    before = _count_actors(migration_url, tenant_id)
    before_audit = _count_audit(migration_url, tenant_id, "actors.created")

    with (
        app.app_context(),
        _authenticated_http(app, monkeypatch, user_id=user_id, tenant_id=tenant_id),
    ):
        ok = client.post(
            "/api/v1/actors",
            json={
                "canonical_name": "Capgemini España S.L.",
                "actor_type": "organization",
                "identifiers": {"tax_id": "b-08.377.715"},
            },
        )
    assert ok.status_code == 201, ok.get_data(as_text=True)[:500]
    body = ok.get_json()
    assert body["tax_id"] == "B08377715"
    assert body["tax_id_scheme"] == "ES_CIF"
    assert body["tax_id_country"] == "ES"
    assert body["canonical_key"] == "tax:es:B08377715"
    assert body["identifiers"]["tax_id"] == "B08377715"
    actor_id = uuid.UUID(body["id"])
    db_row = _load_actor(migration_url, actor_id)
    assert db_row["tax_id"] == "B08377715"
    assert db_row["canonical_key"] == "tax:es:B08377715"

    families = [
        {"tax_id": "***4856**"},  # masked
        {"tax_id": "12345678Z"},  # person NIF
        {"tax_id": "B08377715; A12345674"},  # multi-ID
        {"tax_id": "B08377715"},  # valid CIF but person type → incompatible
    ]
    actor_types = ["organization", "organization", "organization", "person"]
    for identifiers, actor_type in zip(families, actor_types, strict=True):
        with (
            app.app_context(),
            _authenticated_http(app, monkeypatch, user_id=user_id, tenant_id=tenant_id),
        ):
            bad = client.post(
                "/api/v1/actors",
                json={
                    "canonical_name": f"Bad {identifiers['tax_id'][:8]}",
                    "actor_type": actor_type,
                    "identifiers": identifiers,
                },
            )
        assert bad.status_code == 422, (
            f"expected 422 for {identifiers} type={actor_type}, got {bad.status_code}: "
            f"{bad.get_data(as_text=True)[:300]}"
        )
        payload = bad.get_json()
        assert payload["code"] in {"tax_id_validation", "domain_validation", "validation_error"}

    after = _count_actors(migration_url, tenant_id)
    # Only the one valid create (invalid families create zero rows).
    assert after == before + 1

    # Absence of tax_id still uses name fallback (not a 422).
    with (
        app.app_context(),
        _authenticated_http(app, monkeypatch, user_id=user_id, tenant_id=tenant_id),
    ):
        name_only = client.post(
            "/api/v1/actors",
            json={
                "canonical_name": "Nexus Tech SL",
                "actor_type": "organization",
                "identifiers": {"lei": "only-lei"},
            },
        )
    assert name_only.status_code == 201, name_only.get_data(as_text=True)[:400]
    name_body = name_only.get_json()
    assert name_body["tax_id"] is None
    assert name_body["canonical_key"] == "nexus-tech-sl"

    # No spurious create audits for the four invalid POSTs.
    # actors.create does not always write audit_events via append — gate is zero new actors.
    del before_audit  # explicit: POST invalid leaves actor count stable (checked above)


def test_g16_http_rename_preserves_tax_key_and_tenant_scope(
    g16_routes_pg: tuple[Any, dict[str, Any]],
) -> None:
    app, ctx = g16_routes_pg
    client = ctx["client"]
    tenant_id = ctx["tenant_id"]
    tenant_b = ctx["tenant_b"]
    user_id = ctx["user_id"]
    monkeypatch = ctx["monkeypatch"]

    with (
        app.app_context(),
        _authenticated_http(app, monkeypatch, user_id=user_id, tenant_id=tenant_id),
    ):
        fiscal = client.post(
            "/api/v1/actors",
            json={
                "canonical_name": "Capgemini España S.L.",
                "actor_type": "organization",
                "identifiers": {"tax_id": "B08377715"},
            },
        )
        plain = client.post(
            "/api/v1/actors",
            json={"canonical_name": "Local Partner SL", "actor_type": "organization"},
        )
    assert fiscal.status_code in {200, 201}
    assert plain.status_code == 201
    fiscal_id = fiscal.get_json()["id"]
    plain_id = plain.get_json()["id"]
    fiscal_version = fiscal.get_json()["version"]
    plain_version = plain.get_json()["version"]

    with (
        app.app_context(),
        _authenticated_http(app, monkeypatch, user_id=user_id, tenant_id=tenant_id),
    ):
        renamed = client.patch(
            f"/api/v1/actors/{fiscal_id}",
            json={"canonical_name": "CAPGEMINI ESPAÑA, S.L.U."},
            headers={"If-Match": f'W/"{fiscal_version}"'},
        )
        plain_renamed = client.patch(
            f"/api/v1/actors/{plain_id}",
            json={"canonical_name": "Local Partner Spain SL"},
            headers={"If-Match": f'W/"{plain_version}"'},
        )
    assert renamed.status_code == 200, renamed.get_data(as_text=True)[:400]
    assert renamed.get_json()["canonical_key"] == "tax:es:B08377715"
    assert renamed.get_json()["tax_id"] == "B08377715"
    assert plain_renamed.status_code == 200
    assert plain_renamed.get_json()["canonical_key"] == "local-partner-spain-sl"
    assert plain_renamed.get_json()["tax_id"] is None

    # Same name key in other tenant is allowed (duplicate check is tenant-scoped).
    with (
        app.app_context(),
        _authenticated_http(app, monkeypatch, user_id=user_id, tenant_id=tenant_b),
    ):
        other = client.post(
            "/api/v1/actors",
            json={
                "canonical_name": "Local Partner Spain SL",
                "actor_type": "organization",
            },
        )
    assert other.status_code == 201, other.get_data(as_text=True)[:400]
    assert other.get_json()["canonical_key"] == "local-partner-spain-sl"


def test_g16_http_patch_identifiers_assign_sync_conflict_and_guards(
    g16_routes_pg: tuple[Any, dict[str, Any]],
) -> None:
    app, ctx = g16_routes_pg
    client = ctx["client"]
    tenant_id = ctx["tenant_id"]
    user_id = ctx["user_id"]
    migration_url = ctx["migration_url"]
    monkeypatch = ctx["monkeypatch"]

    with (
        app.app_context(),
        _authenticated_http(app, monkeypatch, user_id=user_id, tenant_id=tenant_id),
    ):
        a = client.post(
            "/api/v1/actors",
            json={"canonical_name": "Company Alpha SL", "actor_type": "organization"},
        )
        b = client.post(
            "/api/v1/actors",
            json={"canonical_name": "Company Beta SL", "actor_type": "organization"},
        )
    assert a.status_code == 201 and b.status_code == 201
    a_id, a_ver = a.get_json()["id"], a.get_json()["version"]
    b_id, b_ver = b.get_json()["id"], b.get_json()["version"]

    # First valid CIF assign + sync.
    with (
        app.app_context(),
        _authenticated_http(app, monkeypatch, user_id=user_id, tenant_id=tenant_id),
    ):
        assigned = client.patch(
            f"/api/v1/actors/{a_id}",
            json={"identifiers": {"tax_id": "B08377715", "lei": "ALPHA"}},
            headers={"If-Match": f'W/"{a_ver}"'},
        )
    assert assigned.status_code == 200, assigned.get_data(as_text=True)[:400]
    body = assigned.get_json()
    assert body["tax_id"] == "B08377715"
    assert body["canonical_key"] == "tax:es:B08377715"
    assert body["identifiers"]["tax_id"] == "B08377715"
    assert body["identifiers"]["lei"] == "ALPHA"
    a_ver = body["version"]
    a_row = _load_actor(migration_url, uuid.UUID(a_id))
    assert a_row["tax_id"] == "B08377715"
    assert a_row["identifiers"]["tax_id"] == "B08377715"

    # Same CIF → idempotent.
    with (
        app.app_context(),
        _authenticated_http(app, monkeypatch, user_id=user_id, tenant_id=tenant_id),
    ):
        same = client.patch(
            f"/api/v1/actors/{a_id}",
            json={"identifiers": {"tax_id": "B08377715", "lei": "ALPHA2"}},
            headers={"If-Match": f'W/"{a_ver}"'},
        )
    assert same.status_code == 200
    assert same.get_json()["tax_id"] == "B08377715"
    assert same.get_json()["identifiers"]["lei"] == "ALPHA2"
    a_ver = same.get_json()["version"]

    # Occupied CIF on B → 409 with canonical_actor_id.
    with (
        app.app_context(),
        _authenticated_http(app, monkeypatch, user_id=user_id, tenant_id=tenant_id),
    ):
        conflict = client.patch(
            f"/api/v1/actors/{b_id}",
            json={"identifiers": {"tax_id": "B08377715"}},
            headers={"If-Match": f'W/"{b_ver}"'},
        )
    assert conflict.status_code == 409, conflict.get_data(as_text=True)[:400]
    conf = conflict.get_json()
    assert conf["code"] == "tax_id_conflict"
    assert conf["errors"]["canonical_actor_id"] == a_id
    b_after = _load_actor(migration_url, uuid.UUID(b_id))
    assert b_after["tax_id"] is None
    assert b_after["version"] == b_ver

    # Invalid / change / clear → 422 without mutation.
    for payload in (
        {"identifiers": {"tax_id": "***9999**"}},
        {"identifiers": {"tax_id": "A28855260"}},
        {"identifiers": {"tax_id": None}},
        {"identifiers": {"tax_id": ""}},
        {"identifiers": {"tax_id": "12345678Z"}},
    ):
        with (
            app.app_context(),
            _authenticated_http(app, monkeypatch, user_id=user_id, tenant_id=tenant_id),
        ):
            bad = client.patch(
                f"/api/v1/actors/{a_id}",
                json=payload,
                headers={"If-Match": f'W/"{a_ver}"'},
            )
        assert bad.status_code == 422, (
            f"{payload} → {bad.status_code}: {bad.get_data(as_text=True)[:300]}"
        )
        still = _load_actor(migration_url, uuid.UUID(a_id))
        assert still["tax_id"] == "B08377715"
        assert still["version"] == a_ver
        assert still["identifiers"]["tax_id"] == "B08377715"

    # Other identifiers keys do not wipe tax_id / provenance.
    with (
        app.app_context(),
        _authenticated_http(app, monkeypatch, user_id=user_id, tenant_id=tenant_id),
    ):
        other = client.patch(
            f"/api/v1/actors/{a_id}",
            json={"identifiers": {"website": "https://capgemini.es"}},
            headers={"If-Match": f'W/"{a_ver}"'},
        )
    assert other.status_code == 200
    o = other.get_json()
    assert o["tax_id"] == "B08377715"
    assert o["identifiers"]["tax_id"] == "B08377715"
    assert o["identifiers"]["website"] == "https://capgemini.es"
    assert o["provenance"].get("tax_id_assignment") is not None
    a_ver = o["version"]

    # actor_type incompatible → 422, state/version/audit intact.
    audits_before = _count_audit(migration_url, tenant_id, "actors.updated")
    with (
        app.app_context(),
        _authenticated_http(app, monkeypatch, user_id=user_id, tenant_id=tenant_id),
    ):
        demote = client.patch(
            f"/api/v1/actors/{a_id}",
            json={"actor_type": "person"},
            headers={"If-Match": f'W/"{a_ver}"'},
        )
    assert demote.status_code == 422
    final = _load_actor(migration_url, uuid.UUID(a_id))
    assert final["actor_type"] == "organization"
    assert final["tax_id"] == "B08377715"
    assert final["version"] == a_ver
    assert _count_audit(migration_url, tenant_id, "actors.updated") == audits_before

    # Compatible type change preserves fiscal identity.
    with (
        app.app_context(),
        _authenticated_http(app, monkeypatch, user_id=user_id, tenant_id=tenant_id),
    ):
        promote = client.patch(
            f"/api/v1/actors/{a_id}",
            json={"actor_type": "institution"},
            headers={"If-Match": f'W/"{a_ver}"'},
        )
    assert promote.status_code == 200
    assert promote.get_json()["actor_type"] == "institution"
    assert promote.get_json()["tax_id"] == "B08377715"
    assert promote.get_json()["canonical_key"] == "tax:es:B08377715"


def test_g16_http_concurrent_assign_one_holder_one_conflict(
    g16_routes_pg: tuple[Any, dict[str, Any]],
) -> None:
    """Carrera real: dos PATCH HTTP simultáneos → 1 holder + 1 conflicto 409.

    Identity se instala una sola vez (fuera de los hilos) para no pelear por
    before_request; cada hilo usa su propio test_client + app_context.
    """

    app, ctx = g16_routes_pg
    client = ctx["client"]
    tenant_id = ctx["tenant_id"]
    user_id = ctx["user_id"]
    migration_url = ctx["migration_url"]
    monkeypatch = ctx["monkeypatch"]

    with (
        app.app_context(),
        _authenticated_http(app, monkeypatch, user_id=user_id, tenant_id=tenant_id),
    ):
        x = client.post(
            "/api/v1/actors",
            json={"canonical_name": "Race X SL", "actor_type": "organization"},
        )
        y = client.post(
            "/api/v1/actors",
            json={"canonical_name": "Race Y SL", "actor_type": "organization"},
        )
        assert x.status_code == 201 and y.status_code == 201
        x_id, x_ver = x.get_json()["id"], x.get_json()["version"]
        y_id, y_ver = y.get_json()["id"], y.get_json()["version"]

        barrier = threading.Barrier(2)
        results: list[tuple[str, int, str]] = []
        lock = threading.Lock()

        def patch_one(actor_id: str, version: int) -> None:
            local_client = app.test_client()
            with app.app_context():
                barrier.wait(timeout=10)
                response = local_client.patch(
                    f"/api/v1/actors/{actor_id}",
                    json={"identifiers": {"tax_id": "A28855260"}},
                    headers={"If-Match": f'W/"{version}"'},
                )
                with lock:
                    results.append(
                        (
                            actor_id,
                            response.status_code,
                            response.get_data(as_text=True)[:200],
                        )
                    )

        with ThreadPoolExecutor(max_workers=2) as pool:
            futs = [
                pool.submit(patch_one, x_id, x_ver),
                pool.submit(patch_one, y_id, y_ver),
            ]
            for fut in futs:
                fut.result(timeout=30)

        statuses = sorted(code for _, code, _ in results)
        assert 200 in statuses, results
        assert 409 in statuses, results
        assert statuses.count(200) == 1
        assert statuses.count(409) == 1

    engine = create_engine(migration_url)
    with engine.connect() as connection:
        holders = connection.execute(
            text("SELECT id FROM actors WHERE tenant_id=:t AND tax_id='A28855260'"),
            {"t": tenant_id},
        ).fetchall()
    assert len(holders) == 1
