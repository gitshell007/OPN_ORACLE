"""Versioned AES-256-GCM envelope encryption for integration secrets."""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
from dataclasses import dataclass

from cryptography.hazmat.primitives.ciphers.aead import AESGCM


class EncryptionConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class EncryptedValue:
    ciphertext: bytes
    nonce: bytes
    key_version: int
    fingerprint: str


class IntegrationKeyring:
    """Parse ``version:base64key`` entries separated by commas."""

    def __init__(self, encoded_keys: str, primary_version: int) -> None:
        keys: dict[int, bytes] = {}
        for entry in filter(None, (part.strip() for part in encoded_keys.split(","))):
            try:
                raw_version, encoded = entry.split(":", 1)
                version = int(raw_version)
                key = base64.b64decode(encoded, validate=True)
            except (ValueError, TypeError) as exc:
                raise EncryptionConfigurationError("Keyring de integraciones no válido.") from exc
            if version < 1 or len(key) != 32 or version in keys:
                raise EncryptionConfigurationError("Cada clave debe ser AES-256 y versionada.")
            keys[version] = key
        if primary_version not in keys:
            raise EncryptionConfigurationError("La versión primaria no existe en el keyring.")
        self._keys = keys
        self.primary_version = primary_version

    def encrypt(self, value: str, *, aad: bytes) -> EncryptedValue:
        nonce = os.urandom(12)
        ciphertext = AESGCM(self._keys[self.primary_version]).encrypt(
            nonce, value.encode("utf-8"), aad
        )
        return EncryptedValue(
            ciphertext=ciphertext,
            nonce=nonce,
            key_version=self.primary_version,
            fingerprint=hmac.new(
                self._keys[self.primary_version], aad + b"\0" + value.encode(), hashlib.sha256
            ).hexdigest()[:32],
        )

    def decrypt(self, ciphertext: bytes, nonce: bytes, key_version: int, *, aad: bytes) -> str:
        key = self._keys.get(key_version)
        if key is None:
            raise EncryptionConfigurationError("Versión de clave no disponible.")
        return AESGCM(key).decrypt(nonce, ciphertext, aad).decode("utf-8")


def credential_aad(*, tenant_id: str, connection_id: str, kind: str, version: int) -> bytes:
    return f"opn-oracle|{tenant_id}|{connection_id}|{kind}|{version}".encode()
