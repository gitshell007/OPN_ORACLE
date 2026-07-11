"""Argon2id password hashing and a deliberately simple length policy."""

from __future__ import annotations

from dataclasses import dataclass

from argon2 import PasswordHasher as Argon2PasswordHasher
from argon2.exceptions import InvalidHashError, VerifyMismatchError
from argon2.low_level import Type


class PasswordPolicyError(ValueError):
    """A password is unsafe or cannot be processed safely."""


@dataclass(frozen=True, slots=True)
class PasswordPolicy:
    min_length: int = 12
    max_bytes: int = 1024

    def validate(self, password: str) -> None:
        if len(password.encode("utf-8")) > self.max_bytes:
            raise PasswordPolicyError("La contraseña supera el tamaño máximo permitido.")
        if len(password) < self.min_length:
            raise PasswordPolicyError(
                f"La contraseña debe tener al menos {self.min_length} caracteres."
            )
        normalized = "".join(password.casefold().split())
        if normalized in {"password", "contraseña", "123456789012", "opnoracle", "qwertyuiop"}:
            raise PasswordPolicyError("Elige una contraseña menos predecible.")


class PasswordHasher:
    """Argon2id wrapper with parameter-upgrade support."""

    def __init__(self, policy: PasswordPolicy | None = None) -> None:
        self.policy = policy or PasswordPolicy()
        self._hasher = Argon2PasswordHasher(type=Type.ID)

    def hash(self, password: str) -> str:
        self.policy.validate(password)
        return self._hasher.hash(password)

    def verify(self, encoded: str | None, password: str) -> bool:
        if not encoded or len(password.encode("utf-8")) > self.policy.max_bytes:
            return False
        try:
            return self._hasher.verify(encoded, password)
        except (VerifyMismatchError, InvalidHashError):
            return False

    def needs_rehash(self, encoded: str) -> bool:
        return self._hasher.check_needs_rehash(encoded)
