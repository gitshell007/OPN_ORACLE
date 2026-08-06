"""G-16-B / G-17 · HTTP + PostgreSQL: tax-first candidates, merge CAS, blocks.

Disposable PG (oracle_app RLS). No SQLite. Covers Capgemini, blocked NIF pairs,
name fallback, tenant isolation, fiscal transfer, double-submit and audit.
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
            "dn": "G16B G17",
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
    granted = perms or frozenset(
        {"actor.read", "actor.write", "audit.read", "dossier.read", "dossier.write"}
    )
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
        from flask import g

        g.active_tenant_id = tenant_id
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
def g17_pg(monkeypatch: pytest.MonkeyPatch) -> Iterator[tuple[Any, dict[str, Any]]]:
    migration_url, runtime_url, redis_url = _require_pg_urls()
    app = create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "g16b-g17-merge-secret-key-32bytes!!",
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
    user_b = uuid.uuid4()
    migrator = create_engine(migration_url)
    with migrator.begin() as connection:
        _seed_tenant_user(
            connection,
            tenant_id=tenant_id,
            user_id=user_id,
            slug=f"g17a-{tenant_id.hex[:8]}",
        )
        _seed_tenant_user(
            connection,
            tenant_id=tenant_b,
            user_id=user_b,
            slug=f"g17b-{tenant_b.hex[:8]}",
        )

    client = app.test_client()
    yield (
        app,
        {
            "tenant_id": tenant_id,
            "tenant_b": tenant_b,
            "user_id": user_id,
            "user_b": user_b,
            "migration_url": migration_url,
            "client": client,
            "app": app,
            "monkeypatch": monkeypatch,
        },
    )


def _create_actor(client: Any, payload: dict[str, Any]) -> dict[str, Any]:
    response = client.post("/api/v1/actors", json=payload)
    assert response.status_code == 201, response.get_data(as_text=True)[:800]
    return response.get_json()


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


def _load_actor(migration_url: str, actor_id: str | uuid.UUID) -> dict[str, Any] | None:
    engine = create_engine(migration_url)
    with engine.connect() as connection:
        row = (
            connection.execute(
                text(
                    "SELECT id, canonical_name, tax_id, identifiers, provenance, version"
                    " FROM actors WHERE id=:id"
                ),
                {"id": str(actor_id)},
            )
            .mappings()
            .first()
        )
        return dict(row) if row else None


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


def test_capgemini_tax_first_candidate_and_meta(
    g17_pg: tuple[Any, dict[str, Any]],
) -> None:
    app, ctx = g17_pg
    client = ctx["client"]
    tenant_id = ctx["tenant_id"]
    user_id = ctx["user_id"]
    monkeypatch = ctx["monkeypatch"]

    with (
        app.app_context(),
        _authenticated_http(app, monkeypatch, user_id=user_id, tenant_id=tenant_id),
    ):
        a = _create_actor(
            client,
            {
                "canonical_name": "CAPGEMINI ESPAÑA SL",
                "actor_type": "organization",
                "identifiers": {"tax_id": "B08377715", "lei": "LEI-A", "duns": "DUNS-A"},
            },
        )
        # Second actor same NIF only in JSON would conflict on column assign at POST.
        # Create without tax_id then patch identifiers.tax_id is blocked if column held.
        # Simulate declared twin: same name family, tax only in identifiers via raw SQL
        # is not allowed under app path. Instead create second with same tax via
        # conflict path: different name, no column — then hydrate identifiers only.
        b = _create_actor(
            client,
            {
                "canonical_name": "Capgemini España S.L.",
                "actor_type": "organization",
                "identifiers": {"lei": "LEI-B", "website": "https://capgemini.example"},
            },
        )
        # Put declared tax_id into identifiers without column (backfill-loser style).
        engine = create_engine(ctx["migration_url"])
        with engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE actors SET identifiers = identifiers || CAST(:j AS jsonb) WHERE id=:id"
                ),
                {
                    "id": b["id"],
                    "j": (
                        '{"tax_id":"B08377715","tax_id_scheme":"ES_CIF",'
                        '"tax_id_declared":"B08377715",'
                        '"tax_id_source":{"kind":"award_hydration","folder_id":"F1"}}'
                    ),
                },
            )
        person = _create_actor(
            client,
            {
                "canonical_name": "CAPGEMINI ESPAÑA SL",
                "actor_type": "person",
            },
        )
        _create_actor(
            client,
            {"canonical_name": "Otra Org Sin NIF", "actor_type": "organization"},
        )
        person_id = person["id"]

        candidates = client.get("/api/v1/actors/alias-candidates")
        assert candidates.status_code == 200, candidates.get_data(as_text=True)[:500]
        body = candidates.get_json()
        assert "meta" in body
        meta = body["meta"]
        assert meta["organizations_evaluated"] >= 3
        assert meta["organizations_with_tax_id"] >= 2
        assert "limpio" not in (meta.get("empty_state_message") or "").lower()
        items = body["items"]
        tax_items = [item for item in items if item.get("match_reason") == "tax_id"]
        assert len(tax_items) == 1
        tax = tax_items[0]
        assert tax["tax_id"] == "B08377715"
        assert tax["priority"] == 100
        names = {actor["name"] for actor in tax["actors"]}
        assert "CAPGEMINI ESPAÑA SL" in names
        assert "Capgemini España S.L." in names
        assert all(actor.get("tax_id") == "B08377715" for actor in tax["actors"])
        assert tax["suggested_target_id"] == a["id"]
        # person never listed in any candidate
        for item in items:
            assert all(actor["id"] != person_id for actor in item["actors"])
        # tax match first
        assert items[0]["match_reason"] == "tax_id"
        for actor in tax["actors"]:
            assert actor.get("version") is not None
            assert actor.get("tax_id_provenance", {}).get("verified") is False


def test_same_name_distinct_tax_ids_blocked_and_merge_noops(
    g17_pg: tuple[Any, dict[str, Any]],
) -> None:
    app, ctx = g17_pg
    client = ctx["client"]
    tenant_id = ctx["tenant_id"]
    user_id = ctx["user_id"]
    migration_url = ctx["migration_url"]
    monkeypatch = ctx["monkeypatch"]

    with (
        app.app_context(),
        _authenticated_http(app, monkeypatch, user_id=user_id, tenant_id=tenant_id),
    ):
        left = _create_actor(
            client,
            {
                "canonical_name": "ACME SL",
                "actor_type": "organization",
                "identifiers": {"tax_id": "A58818501"},
            },
        )
        right = _create_actor(
            client,
            {
                "canonical_name": "Acme S.L.",
                "actor_type": "organization",
                "identifiers": {"tax_id": "B08377715"},
            },
        )
        before = _count_actors(migration_url, tenant_id)
        candidates = client.get("/api/v1/actors/alias-candidates").get_json()
        blocked = [
            item
            for item in candidates["items"]
            if item.get("status") == "blocked" or item.get("match_reason") == "tax_id_conflict"
        ]
        assert blocked, candidates
        assert any("A58818501" in (item.get("blocking_tax_ids") or []) for item in blocked)

        preview = client.post(
            f"/api/v1/actors/{left['id']}/merge/preview",
            json={"source_actor_id": right["id"]},
        )
        assert preview.status_code == 200
        assert preview.get_json()["blocked"] is True

        merged = client.post(
            f"/api/v1/actors/{left['id']}/merge",
            json={
                "source_actor_id": right["id"],
                "reason": "Intento indebido",
                "confirm": True,
                "expected_target_version": left["version"],
                "expected_source_version": right["version"],
            },
        )
        assert merged.status_code in {409, 422}
        problem = merged.get_json()
        assert (
            "tax_id" in str(problem).lower()
            or "NIF" in str(problem)
            or "bloquead" in str(problem).lower()
        )
        assert _count_actors(migration_url, tenant_id) == before
        assert _load_actor(migration_url, left["id"]) is not None
        assert _load_actor(migration_url, right["id"]) is not None


def test_name_fallback_labeled_and_merge_with_cas_transfer(
    g17_pg: tuple[Any, dict[str, Any]],
) -> None:
    app, ctx = g17_pg
    client = ctx["client"]
    tenant_id = ctx["tenant_id"]
    user_id = ctx["user_id"]
    migration_url = ctx["migration_url"]
    monkeypatch = ctx["monkeypatch"]

    with (
        app.app_context(),
        _authenticated_http(app, monkeypatch, user_id=user_id, tenant_id=tenant_id),
    ):
        target = _create_actor(
            client,
            {
                "canonical_name": "ITURRI SA",
                "actor_type": "organization",
                "identifiers": {"lei": "TARGET-LEI", "duns": "T-DUNS"},
            },
        )
        source = _create_actor(
            client,
            {
                "canonical_name": "Iturri S.L.",
                "actor_type": "organization",
                "identifiers": {
                    "tax_id": "B82528558",
                    "lei": "SOURCE-LEI",
                    "duns": "S-DUNS",
                    "extra": "keep-me",
                },
            },
        )
        candidates = client.get("/api/v1/actors/alias-candidates").get_json()
        name_items = [
            item
            for item in candidates["items"]
            if item.get("match_reason") == "normalized_name"
            and any(actor["id"] in {target["id"], source["id"]} for actor in item["actors"])
        ]
        assert name_items
        assert name_items[0]["confidence"] == "low"

        preview = client.post(
            f"/api/v1/actors/{target['id']}/merge/preview",
            json={"source_actor_id": source["id"]},
        )
        assert preview.status_code == 200
        pbody = preview.get_json()
        assert pbody["blocked"] is False
        assert pbody["confirmation_required"]["expected_target_version"] == target["version"]
        assert pbody["confirmation_required"]["expected_source_version"] == source["version"]

        # CAS stale
        stale = client.post(
            f"/api/v1/actors/{target['id']}/merge",
            json={
                "source_actor_id": source["id"],
                "reason": "stale attempt",
                "confirm": True,
                "expected_target_version": 999,
                "expected_source_version": source["version"],
            },
        )
        assert stale.status_code == 409
        assert _load_actor(migration_url, source["id"]) is not None

        before_audit = _count_audit(migration_url, tenant_id, "actor.merged")
        ok = client.post(
            f"/api/v1/actors/{target['id']}/merge",
            json={
                "source_actor_id": source["id"],
                "reason": "Misma empresa, distinta forma jurídica",
                "confirm": True,
                "expected_target_version": target["version"],
                "expected_source_version": source["version"],
                "match_reason": "normalized_name",
            },
        )
        assert ok.status_code == 200, ok.get_data(as_text=True)[:800]
        body = ok.get_json()
        assert body["tax_id"] == "B82528558"
        assert body["identifiers"]["lei"] == "TARGET-LEI"
        assert body["identifiers"]["duns"] == "T-DUNS"
        assert body["identifiers"].get("extra") == "keep-me"
        assert "Iturri S.L." in body["aliases"] or "Iturri" in " ".join(body.get("aliases") or [])
        assert _load_actor(migration_url, source["id"]) is None
        assert _count_audit(migration_url, tenant_id, "actor.merged") == before_audit + 1

        # Double submit / retry is idempotent (source already gone).
        retry = client.post(
            f"/api/v1/actors/{target['id']}/merge",
            json={
                "source_actor_id": source["id"],
                "reason": "Misma empresa, distinta forma jurídica",
                "confirm": True,
                "expected_target_version": body["version"],
                "expected_source_version": source["version"],
            },
        )
        # Idempotent success or 404 — never deletes another entity.
        assert retry.status_code in {200, 404}
        assert _count_audit(migration_url, tenant_id, "actor.merged") == before_audit + 1


def test_second_tenant_never_appears_in_candidates(
    g17_pg: tuple[Any, dict[str, Any]],
) -> None:
    app, ctx = g17_pg
    client = ctx["client"]
    tenant_id = ctx["tenant_id"]
    tenant_b = ctx["tenant_b"]
    user_id = ctx["user_id"]
    user_b = ctx["user_b"]
    monkeypatch = ctx["monkeypatch"]

    with (
        app.app_context(),
        _authenticated_http(app, monkeypatch, user_id=user_id, tenant_id=tenant_id),
    ):
        _create_actor(
            client,
            {
                "canonical_name": "Tenant A Twin SA",
                "actor_type": "organization",
            },
        )
        _create_actor(
            client,
            {
                "canonical_name": "Tenant A Twin SL",
                "actor_type": "organization",
            },
        )

    with (
        app.app_context(),
        _authenticated_http(app, monkeypatch, user_id=user_b, tenant_id=tenant_b),
    ):
        foreign = _create_actor(
            client,
            {
                "canonical_name": "Tenant A Twin SA",
                "actor_type": "organization",
            },
        )
        foreign_b = _create_actor(
            client,
            {
                "canonical_name": "Tenant A Twin SL",
                "actor_type": "organization",
            },
        )
        foreign_ids = {foreign["id"], foreign_b["id"]}
        body = client.get("/api/v1/actors/alias-candidates").get_json()
        # Tenant A twins must not appear in tenant B response.
        assert all(
            actor["id"] in foreign_ids
            for item in body["items"]
            for actor in item["actors"]
            if "Tenant A Twin" in actor["name"]
        )


def test_merge_conflict_resolve_via_endpoint_rejects_merge_action(
    g17_pg: tuple[Any, dict[str, Any]],
) -> None:
    app, ctx = g17_pg
    client = ctx["client"]
    tenant_id = ctx["tenant_id"]
    user_id = ctx["user_id"]
    monkeypatch = ctx["monkeypatch"]

    with (
        app.app_context(),
        _authenticated_http(app, monkeypatch, user_id=user_id, tenant_id=tenant_id),
    ):
        response = client.post(
            f"/api/v1/actors/{uuid.uuid4()}/tax-id-conflicts/{uuid.uuid4()}/resolve"
            if False
            else f"/api/v1/actors/tax-id-conflicts/{uuid.uuid4()}/resolve",
            json={"action": "merge", "note": "should fail"},
        )
        assert response.status_code == 422
        detail = str(response.get_json())
        assert "merge" in detail.lower() or "fusion" in detail.lower()


def test_concurrent_merge_single_winner(
    g17_pg: tuple[Any, dict[str, Any]],
) -> None:
    """Real concurrent merge: one 200, one CAS/gone; single audit event."""

    app, ctx = g17_pg
    client = ctx["client"]
    tenant_id = ctx["tenant_id"]
    user_id = ctx["user_id"]
    migration_url = ctx["migration_url"]
    monkeypatch = ctx["monkeypatch"]

    with (
        app.app_context(),
        _authenticated_http(app, monkeypatch, user_id=user_id, tenant_id=tenant_id),
    ):
        target = _create_actor(
            client,
            {"canonical_name": "Race Target SA", "actor_type": "organization"},
        )
        source = _create_actor(
            client,
            {"canonical_name": "Race Target SL", "actor_type": "organization"},
        )
        payload = {
            "source_actor_id": source["id"],
            "reason": "carrera real concurrente",
            "confirm": True,
            "expected_target_version": target["version"],
            "expected_source_version": source["version"],
        }
        results: list[tuple[int, str]] = []
        barrier = threading.Barrier(2)
        lock = threading.Lock()

        def worker() -> None:
            local_client = app.test_client()
            with (
                app.app_context(),
                _authenticated_http(app, monkeypatch, user_id=user_id, tenant_id=tenant_id),
            ):
                barrier.wait(timeout=10)
                response = local_client.post(
                    f"/api/v1/actors/{target['id']}/merge",
                    json=payload,
                )
                with lock:
                    results.append((response.status_code, response.get_data(as_text=True)[:240]))

        with ThreadPoolExecutor(max_workers=2) as pool:
            futures = [pool.submit(worker) for _ in range(2)]
            for future in futures:
                future.result(timeout=30)

        statuses = [code for code, _ in results]
        # One mutation wins; the loser is either CAS/404 or idempotent 200
        # (source already merged into target → last_merge retry path).
        assert 200 in statuses, results
        assert all(code in {200, 404, 409, 422} for code in statuses), results
        assert _load_actor(migration_url, source["id"]) is None
        assert _load_actor(migration_url, target["id"]) is not None
        # Exactly one durable merge audit regardless of idempotent retries.
        assert _count_audit(migration_url, tenant_id, "actor.merged") == 1


def test_empty_candidates_meta_not_clean(
    g17_pg: tuple[Any, dict[str, Any]],
) -> None:
    app, ctx = g17_pg
    client = ctx["client"]
    tenant_id = ctx["tenant_id"]
    user_id = ctx["user_id"]
    monkeypatch = ctx["monkeypatch"]

    with (
        app.app_context(),
        _authenticated_http(app, monkeypatch, user_id=user_id, tenant_id=tenant_id),
    ):
        for index in range(3):
            _create_actor(
                client,
                {
                    "canonical_name": f"Unica Org {index}",
                    "actor_type": "organization",
                },
            )
        body = client.get("/api/v1/actors/alias-candidates").get_json()
        assert body["items"] == []
        assert body["meta"]["organizations_evaluated"] == 3
        assert "limpio" not in body["meta"]["empty_state_message"].lower()
        assert body["meta"]["organizations_with_tax_id"] == 0
