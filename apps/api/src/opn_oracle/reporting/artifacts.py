"""Short-lived, session-bound artifact download authorization."""

from __future__ import annotations

import hashlib
import hmac
import json
import time
import uuid
from dataclasses import dataclass
from typing import BinaryIO

from flask import current_app

from opn_oracle.documents.storage import ObjectStorage, StorageError
from opn_oracle.reporting.models import DataExport, ReportArtifact


class ArtifactAccessError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class DownloadArtifact:
    kind: str
    id: uuid.UUID
    storage_key: str
    checksum: bytes
    byte_size: int
    media_type: str
    filename: str


def artifact_fingerprint(artifact: DownloadArtifact) -> str:
    """Return a stable fingerprint for the exact stored artifact being authorized."""

    payload = {
        "byte_size": artifact.byte_size,
        "checksum": artifact.checksum.hex(),
        "filename": artifact.filename,
        "id": str(artifact.id),
        "kind": artifact.kind,
        "media_type": artifact.media_type,
        "storage_key": artifact.storage_key,
        "version": 1,
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(canonical).hexdigest()


def _message(
    *,
    kind: str,
    artifact_id: uuid.UUID,
    artifact_fingerprint: str,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    expires: int,
) -> bytes:
    return (
        f"{kind}:{artifact_id}:{artifact_fingerprint}:{tenant_id}:{user_id}:{session_id}:{expires}"
    ).encode()


def create_download_signature(
    *,
    kind: str,
    artifact_id: uuid.UUID,
    artifact_fingerprint: str,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    now: int | None = None,
) -> tuple[int, str]:
    if kind not in {"report", "export"}:
        raise ArtifactAccessError("Tipo de artefacto no permitido.")
    if len(artifact_fingerprint) != 64:
        raise ArtifactAccessError("Fingerprint de artefacto no válido.")
    ttl = min(max(int(current_app.config["REPORT_DOWNLOAD_TTL_SECONDS"]), 10), 300)
    expires = (now if now is not None else int(time.time())) + ttl
    signature = hmac.new(
        current_app.config["SECRET_KEY"].encode(),
        _message(
            kind=kind,
            artifact_id=artifact_id,
            artifact_fingerprint=artifact_fingerprint,
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            expires=expires,
        ),
        hashlib.sha256,
    ).hexdigest()
    return expires, signature


def verify_download_signature(
    *,
    kind: str,
    artifact_id: uuid.UUID,
    artifact_fingerprint: str,
    tenant_id: uuid.UUID,
    user_id: uuid.UUID,
    session_id: uuid.UUID,
    expires: int,
    signature: str,
    now: int | None = None,
) -> None:
    current = now if now is not None else int(time.time())
    ttl = min(max(int(current_app.config["REPORT_DOWNLOAD_TTL_SECONDS"]), 10), 300)
    if (
        expires < current
        or expires > current + ttl + 5
        or len(signature) != 64
        or len(artifact_fingerprint) != 64
    ):
        raise ArtifactAccessError("El enlace de descarga ha caducado.")
    expected = hmac.new(
        current_app.config["SECRET_KEY"].encode(),
        _message(
            kind=kind,
            artifact_id=artifact_id,
            artifact_fingerprint=artifact_fingerprint,
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=session_id,
            expires=expires,
        ),
        hashlib.sha256,
    ).hexdigest()
    if not hmac.compare_digest(expected, signature):
        raise ArtifactAccessError("Firma de descarga no válida.")


def report_artifact(row: ReportArtifact) -> DownloadArtifact:
    if row.status != "available":
        raise ArtifactAccessError("Artefacto no disponible.")
    extension = {"html": "html", "json": "json", "pdf": "pdf"}[row.format]
    return DownloadArtifact(
        kind="report",
        id=row.id,
        storage_key=row.storage_key,
        checksum=row.checksum,
        byte_size=row.byte_size,
        media_type=row.media_type,
        filename=f"oracle-report-{row.report_id}.{extension}",
    )


def export_artifact(row: DataExport) -> DownloadArtifact:
    if row.status != "ready" or row.expires_at is None:
        raise ArtifactAccessError("Exportación no disponible.")
    if row.storage_key is None or row.checksum is None or row.byte_size is None:
        raise ArtifactAccessError("Exportación no disponible.")
    if row.media_type is None:
        raise ArtifactAccessError("Exportación no disponible.")
    return DownloadArtifact(
        kind="export",
        id=row.id,
        storage_key=row.storage_key,
        checksum=row.checksum,
        byte_size=row.byte_size,
        media_type=row.media_type,
        filename=f"oracle-export-{row.id}.csv",
    )


def read_artifact(row: DownloadArtifact) -> bytes:
    storage: ObjectStorage = current_app.extensions["object_storage"]
    source: BinaryIO | None = None
    try:
        source = storage.get(row.storage_key)
        payload = source.read(row.byte_size + 1)
    except (OSError, StorageError) as error:
        raise ArtifactAccessError("Artefacto no disponible.") from error
    finally:
        if source is not None:
            source.close()
    if len(payload) != row.byte_size or hashlib.sha256(payload).digest() != row.checksum:
        raise ArtifactAccessError("La integridad del artefacto no es válida.")
    return payload
