"""Malware scanner boundary. Production never silently falls back to noop."""

from __future__ import annotations

import socket
import struct
from dataclasses import dataclass
from typing import BinaryIO, Protocol


@dataclass(frozen=True, slots=True)
class ScanResult:
    status: str
    engine: str
    signature: str | None = None


class MalwareScanner(Protocol):
    def scan(self, source: BinaryIO) -> ScanResult: ...


class NoopScanner:
    """Explicit development/test scanner; this is not antivirus."""

    def scan(self, source: BinaryIO) -> ScanResult:
        del source
        return ScanResult("not_configured", "noop")


class ScannerUnavailable(RuntimeError):
    pass


class ClamAVScanner:
    """Bounded clamd INSTREAM client; ambiguous results fail closed."""

    def __init__(self, host: str, port: int, timeout_seconds: float, max_bytes: int) -> None:
        self.host = host
        self.port = port
        self.timeout_seconds = timeout_seconds
        self.max_bytes = max_bytes

    def scan(self, source: BinaryIO) -> ScanResult:
        scanned = 0
        try:
            with socket.create_connection(
                (self.host, self.port), timeout=self.timeout_seconds
            ) as connection:
                connection.settimeout(self.timeout_seconds)
                connection.sendall(b"zINSTREAM\0")
                while chunk := source.read(64 * 1024):
                    scanned += len(chunk)
                    if scanned > self.max_bytes:
                        raise ScannerUnavailable("El archivo supera el límite de scan.")
                    connection.sendall(struct.pack("!I", len(chunk)) + chunk)
                connection.sendall(struct.pack("!I", 0))
                response = connection.recv(4096).decode("utf-8", errors="replace")
        except (OSError, TimeoutError) as exc:
            raise ScannerUnavailable("El scanner requerido no está disponible.") from exc
        response = response.strip("\0\r\n")
        if response.endswith(" OK"):
            return ScanResult("clean", "clamav")
        if response.endswith(" FOUND"):
            signature = response.rsplit(":", 1)[-1].removesuffix(" FOUND").strip()[:200]
            return ScanResult("infected", "clamav", signature)
        raise ScannerUnavailable("El scanner devolvió un resultado no válido.")
