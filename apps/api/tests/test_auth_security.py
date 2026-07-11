from __future__ import annotations

from typing import Any

import pytest
from argon2 import PasswordHasher as Argon2PasswordHasher
from argon2.low_level import Type
from flask import Flask

from opn_oracle.auth.passwords import PasswordHasher, PasswordPolicy, PasswordPolicyError
from opn_oracle.auth.runtime import rotate_session_id
from opn_oracle.auth.tokens import generate_token, hash_token, token_matches


@pytest.mark.unit
def test_argon2id_hash_verify_policy_and_rehash() -> None:
    hasher = PasswordHasher(PasswordPolicy(min_length=12, max_bytes=128))
    encoded = hasher.hash("frase larga segura 2026")
    assert encoded.startswith("$argon2id$")
    assert hasher.verify(encoded, "frase larga segura 2026")
    assert not hasher.verify(encoded, "incorrecta")
    assert hasher.needs_rehash(encoded) is False
    legacy = Argon2PasswordHasher(time_cost=1, memory_cost=8192, parallelism=1, type=Type.ID).hash(
        "frase suficientemente larga"
    )
    assert hasher.verify(legacy, "frase suficientemente larga") is True
    assert hasher.needs_rehash(legacy) is True
    with pytest.raises(PasswordPolicyError):
        hasher.hash("corta")
    with pytest.raises(PasswordPolicyError):
        hasher.hash("password")


@pytest.mark.unit
def test_opaque_tokens_are_random_hashed_and_constant_time_checked() -> None:
    first, second = generate_token(), generate_token()
    assert first != second
    digest = hash_token(first)
    assert len(digest) == 32
    assert token_matches(first, digest)
    assert not token_matches(second, digest)


@pytest.mark.unit
def test_csrf_missing_invalid_valid_and_runtime_json_validation(client: Any) -> None:
    missing = client.post("/api/v1/auth/login", json={"email": "a@example.test", "password": "x"})
    assert missing.status_code == 403
    token = client.get("/api/v1/auth/csrf").get_json()["csrf_token"]
    invalid = client.post(
        "/api/v1/auth/login",
        json={"email": "a@example.test", "password": "x"},
        headers={"X-CSRF-Token": "incorrecto"},
    )
    assert invalid.status_code == 403
    malformed = client.post(
        "/api/v1/auth/login",
        json={"email": "no-es-email"},
        headers={"X-CSRF-Token": token},
    )
    assert malformed.status_code == 422
    assert malformed.get_json()["errors"]


@pytest.mark.unit
def test_csrf_does_not_mask_missing_route(client: Any) -> None:
    assert client.post("/missing").status_code == 404


@pytest.mark.unit
def test_session_rotation_fails_closed_without_regenerate() -> None:
    app = Flask(__name__)
    app.secret_key = "test"
    with app.test_request_context("/"), pytest.raises(RuntimeError, match="rotación segura"):
        rotate_session_id()


@pytest.mark.unit
def test_production_cookie_flags() -> None:
    from opn_oracle import create_app

    app = create_app(
        {
            "APP_ENV": "production",
            "SECRET_KEY": "x" * 40,
            "DATABASE_URL": "postgresql://user:password@db/oracle",
            "REDIS_URL": "rediss://redis.example/0",
            "FRONTEND_ORIGIN": "https://oracle.example",
            "MAIL_BACKEND": "smtp",
            "SMTP_HOST": "smtp.example",
            "MAIL_FROM": "oracle@example.test",
        }
    )
    assert app.config["SESSION_COOKIE_HTTPONLY"] is True
    assert app.config["SESSION_COOKIE_SECURE"] is True
    assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"


@pytest.mark.unit
def test_openapi_declares_auth_bodies_security_and_errors(client: Any) -> None:
    spec = client.get("/api/v1/openapi.json").get_json()
    login = spec["paths"]["/api/v1/auth/login"]["post"]
    assert login["requestBody"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/LoginInput"
    }
    assert "429" in login["responses"]
    assert login["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/LoginResponse"
    }
    me = spec["paths"]["/api/v1/auth/me"]["get"]
    assert me["security"] == [{"cookieAuth": []}]
    assert {"401", "403", "422"}.issubset(me["responses"])
    assert me["responses"]["200"]["content"]["application/json"]["schema"] == {
        "$ref": "#/components/schemas/MeResponse"
    }
    assert "204" in spec["paths"]["/api/v1/auth/logout"]["post"]["responses"]
