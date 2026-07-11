"""Opaque single-use token primitives; plaintext is returned only at issue time."""

from __future__ import annotations

import base64
import hashlib
import hmac
import secrets
import uuid


def generate_token() -> str:
    return secrets.token_urlsafe(32)


def hash_token(token: str) -> bytes:
    return hashlib.sha256(token.encode("utf-8")).digest()


def token_matches(token: str, expected_hash: bytes) -> bool:
    return hmac.compare_digest(hash_token(token), expected_hash)


def stable_invitation_token(*, invitation_id: uuid.UUID, secret_key: str) -> str:
    """Derive a non-stored invitation token for durable, retry-safe email delivery."""

    digest = hmac.new(
        secret_key.encode("utf-8"),
        f"invitation:{invitation_id}".encode("ascii"),
        hashlib.sha256,
    ).digest()
    return base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
