"""Object storage boundary with safe local and S3-compatible implementations."""

from __future__ import annotations

import hashlib
import ipaddress
import os
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO, Protocol, cast
from urllib.parse import urlsplit

import boto3
from botocore.client import Config

SAFE_KEY = re.compile(r"^[0-9a-f-]{36}/[0-9a-f-]{36}/[0-9a-f-]{36}$")


class StorageError(RuntimeError):
    """Safe storage failure without provider details."""


@dataclass(frozen=True, slots=True)
class StoredObject:
    key: str
    byte_size: int
    checksum: bytes


@dataclass(frozen=True, slots=True)
class StorageObjectRef:
    key: str
    modified_at: datetime


class ObjectStorage(Protocol):
    def put(
        self, key: str, source: BinaryIO, *, max_bytes: int, media_type: str
    ) -> StoredObject: ...
    def get(self, key: str) -> BinaryIO: ...
    def delete(self, key: str) -> None: ...
    def signed_download(self, key: str, *, expires_seconds: int = 60) -> str | None: ...
    def health(self) -> bool: ...
    def iter_objects(self, tenant_id: uuid.UUID) -> tuple[StorageObjectRef, ...]: ...


def object_key(tenant_id: uuid.UUID, dossier_id: uuid.UUID, document_id: uuid.UUID) -> str:
    return f"{tenant_id}/{dossier_id}/{document_id}"


def validate_key(key: str) -> str:
    if not SAFE_KEY.fullmatch(key):
        raise StorageError("Clave de almacenamiento inválida.")
    return key


class LimitedReader:
    def __init__(self, source: BinaryIO, limit: int) -> None:
        self.source = source
        self.limit = limit
        self.read_bytes = 0
        self.digest = hashlib.sha256()

    def read(self, size: int = -1) -> bytes:
        allowed = self.limit + 1 - self.read_bytes
        if allowed <= 0:
            raise StorageError("El archivo supera el límite permitido.")
        requested = allowed if size < 0 else min(size, allowed)
        chunk = self.source.read(requested)
        self.read_bytes += len(chunk)
        if self.read_bytes > self.limit:
            raise StorageError("El archivo supera el límite permitido.")
        self.digest.update(chunk)
        return chunk


class LocalObjectStorage:
    """Private filesystem storage; keys never contain user-controlled filenames."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        self.root.mkdir(mode=0o700, parents=True, exist_ok=True)
        os.chmod(self.root, 0o700)

    def _path(self, key: str) -> Path:
        raw = self.root / validate_key(key)
        if any(parent.is_symlink() for parent in raw.parents if parent != self.root):
            raise StorageError("Clave de almacenamiento inválida.")
        candidate = raw.resolve()
        if self.root not in candidate.parents:
            raise StorageError("Clave de almacenamiento inválida.")
        return candidate

    def put(self, key: str, source: BinaryIO, *, max_bytes: int, media_type: str) -> StoredObject:
        del media_type
        path = self._path(key)
        path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        temp = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
        reader = LimitedReader(source, max_bytes)
        try:
            with temp.open("xb", buffering=0) as target:
                while chunk := reader.read(64 * 1024):
                    target.write(chunk)
                os.fsync(target.fileno())
            os.chmod(temp, 0o600)
            os.replace(temp, path)
        except Exception:
            temp.unlink(missing_ok=True)
            raise
        return StoredObject(key, reader.read_bytes, reader.digest.digest())

    def get(self, key: str) -> BinaryIO:
        path = self._path(key)
        if path.is_symlink() or not path.is_file():
            raise StorageError("Objeto no disponible.")
        return path.open("rb")

    def delete(self, key: str) -> None:
        path = self._path(key)
        if path.is_symlink():
            raise StorageError("Objeto no disponible.")
        path.unlink(missing_ok=True)

    def signed_download(self, key: str, *, expires_seconds: int = 60) -> str | None:
        del key, expires_seconds
        return None

    def health(self) -> bool:
        return self.root.is_dir() and os.access(self.root, os.R_OK | os.W_OK)

    def iter_objects(self, tenant_id: uuid.UUID) -> tuple[StorageObjectRef, ...]:
        tenant_root = self.root / str(tenant_id)
        if not tenant_root.exists() or tenant_root.is_symlink():
            return ()
        return tuple(
            StorageObjectRef(
                path.relative_to(self.root).as_posix(),
                datetime.fromtimestamp(path.stat().st_mtime, UTC),
            )
            for path in tenant_root.glob("*/*")
            if path.is_file()
            and not path.is_symlink()
            and SAFE_KEY.fullmatch(path.relative_to(self.root).as_posix())
        )


class S3ObjectStorage:
    """S3-compatible adapter using provider-side AES-256 encryption."""

    def __init__(
        self,
        *,
        endpoint_url: str,
        region: str,
        bucket: str,
        access_key: str,
        secret_key: str,
        allowed_hosts: frozenset[str],
    ) -> None:
        parsed = urlsplit(endpoint_url)
        host = (parsed.hostname or "").lower()
        if (
            parsed.scheme != "https"
            or not host
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
            or parsed.path not in {"", "/"}
            or host not in allowed_hosts
        ):
            raise StorageError("Endpoint S3 no permitido.")
        try:
            address = ipaddress.ip_address(host)
        except ValueError as exc:
            raise StorageError(
                "S3 HTTP requiere endpoint IP global fijado para evitar DNS rebinding."
            ) from exc
        if not address.is_global:
            raise StorageError("Endpoint S3 no permitido.")
        self.bucket = bucket
        self.client = boto3.client(
            "s3",
            endpoint_url=endpoint_url,
            region_name=region,
            aws_access_key_id=access_key,
            aws_secret_access_key=secret_key,
            config=Config(
                signature_version="s3v4", retries={"max_attempts": 3, "mode": "standard"}
            ),
        )

    def put(self, key: str, source: BinaryIO, *, max_bytes: int, media_type: str) -> StoredObject:
        validate_key(key)
        reader = LimitedReader(source, max_bytes)
        self.client.upload_fileobj(
            reader,
            self.bucket,
            key,
            ExtraArgs={"ContentType": media_type, "ServerSideEncryption": "AES256"},
        )
        return StoredObject(key, reader.read_bytes, reader.digest.digest())

    def get(self, key: str) -> BinaryIO:
        validate_key(key)
        body = self.client.get_object(Bucket=self.bucket, Key=key)["Body"]
        return cast(BinaryIO, body)

    def delete(self, key: str) -> None:
        validate_key(key)
        self.client.delete_object(Bucket=self.bucket, Key=key)

    def signed_download(self, key: str, *, expires_seconds: int = 60) -> str | None:
        validate_key(key)
        return str(
            self.client.generate_presigned_url(
                "get_object",
                Params={"Bucket": self.bucket, "Key": key},
                ExpiresIn=min(max(expires_seconds, 10), 300),
            )
        )

    def health(self) -> bool:
        try:
            self.client.head_bucket(Bucket=self.bucket)
        except Exception:
            return False
        return True

    def iter_objects(self, tenant_id: uuid.UUID) -> tuple[StorageObjectRef, ...]:
        prefix = f"{tenant_id}/"
        paginator = self.client.get_paginator("list_objects_v2")
        rows: list[StorageObjectRef] = []
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            for item in page.get("Contents", []):
                key = str(item.get("Key", ""))
                modified = item.get("LastModified")
                if SAFE_KEY.fullmatch(key) and isinstance(modified, datetime):
                    rows.append(StorageObjectRef(key, modified))
        return tuple(rows)
