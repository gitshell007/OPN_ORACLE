"""One-way handling for opaque invitation, reset and session values."""

from __future__ import annotations

import hashlib
import secrets


def generate_opaque_token(*, bytes_length: int = 32) -> str:
    if bytes_length < 32:
        raise ValueError("Los tokens opacos deben tener al menos 256 bits.")
    return secrets.token_urlsafe(bytes_length)


def hash_opaque_token(token: str) -> bytes:
    if not token:
        raise ValueError("El token no puede estar vacío.")
    return hashlib.sha256(token.encode("utf-8")).digest()
