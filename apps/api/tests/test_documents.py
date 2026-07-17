from __future__ import annotations

import io
import json
import shutil
import stat
import uuid
import zipfile
from datetime import UTC, datetime
from pathlib import Path

import pytest

from opn_oracle.config import ConfigError, Settings
from opn_oracle.documents.parsers import (
    CSVParser,
    DOCXParser,
    ParsedBlock,
    ParsedDocument,
    ParseError,
    PDFParser,
    TextParser,
    TranscriptJSONParser,
    chunk_document,
    parser_for,
)
from opn_oracle.documents.scanner import (
    ClamAVScanner,
    NoopScanner,
    ScannerUnavailable,
    ScanResult,
)
from opn_oracle.documents.service import DocumentError, safe_filename, verify_magic
from opn_oracle.documents.storage import (
    LocalObjectStorage,
    S3ObjectStorage,
    StorageError,
    object_key,
)


@pytest.mark.unit
def test_local_storage_rejects_traversal_symlink_and_enforces_limits(tmp_path: Path) -> None:
    storage = LocalObjectStorage(tmp_path / "private")
    tenant, dossier, document = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    key = object_key(tenant, dossier, document)
    stored = storage.put(key, io.BytesIO(b"trusted"), max_bytes=7, media_type="text/plain")
    assert stored.byte_size == 7
    path = tmp_path / "private" / key
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert storage.get(key).read() == b"trusted"
    with pytest.raises(StorageError):
        storage.put(key, io.BytesIO(b"oversized"), max_bytes=4, media_type="text/plain")
    with pytest.raises(StorageError):
        storage.get("../outside")
    storage.delete(key)
    shutil.rmtree(tenant_dir := tmp_path / "private" / str(tenant))
    (tmp_path / "outside").mkdir()
    tenant_dir.parent.mkdir(exist_ok=True)
    tenant_dir.symlink_to(tmp_path / "outside", target_is_directory=True)
    with pytest.raises(StorageError):
        storage.put(key, io.BytesIO(b"x"), max_bytes=2, media_type="text/plain")


@pytest.mark.unit
def test_filename_and_magic_spoof_are_rejected() -> None:
    assert safe_filename("../../cabecera\r\nX-Evil: yes.pdf") == "cabeceraX-Evil: yes.pdf"
    with pytest.raises(DocumentError):
        verify_magic(io.BytesIO(b"not a pdf"), "application/pdf")
    with pytest.raises(DocumentError):
        verify_magic(io.BytesIO(b"MZ\x00payload"), "text/plain")


@pytest.mark.unit
def test_docx_parser_rejects_zip_bomb_ratio() -> None:
    payload = io.BytesIO()
    with zipfile.ZipFile(payload, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("word/document.xml", b"a" * (2 * 1024 * 1024))
    payload.seek(0)
    with pytest.raises(ParseError, match="descompresión"):
        DOCXParser().parse(payload)


@pytest.mark.unit
def test_transcript_and_chunk_locators_are_exact_and_structured() -> None:
    raw = {
        "segments": [
            {"speaker": "Ana", "start_ms": 10, "end_ms": 20, "text": "  decisión trazable  "}
        ]
    }
    parsed = TranscriptJSONParser().parse(io.BytesIO(json.dumps(raw).encode()))
    assert parsed.blocks[0].locator == {
        "segment": 1,
        "speaker": "Ana",
        "time_start_ms": 10,
        "time_end_ms": 20,
    }
    source = ParsedDocument("test", "v1", (ParsedBlock("  " + "palabra " * 80, {"page": 2}),))
    chunks = chunk_document(source, target_chars=220, overlap_chars=20)
    assert chunks
    normalized = source.blocks[0].text
    for chunk in chunks:
        local_start = int(chunk.locator["char_start"])
        assert normalized[local_start : local_start + len(chunk.text)] == chunk.text


@pytest.mark.unit
def test_production_documents_fail_closed_without_s3_and_scanner() -> None:
    base = {
        "APP_ENV": "production",
        "SECRET_KEY": "x" * 40,
        "DATABASE_URL": "postgresql+psycopg://db/oracle",
        "DATABASE_MIGRATION_URL": "postgresql+psycopg://db/oracle",
        "REDIS_URL": "redis://redis/0",
        "FRONTEND_ORIGIN": "https://oracle.example",
        "FLASK_DEBUG": False,
        "MAIL_BACKEND": "smtp",
        "SMTP_HOST": "smtp.example",
        "MAIL_FROM": "oracle@example.test",
        "CELERY_TASK_ALWAYS_EAGER": False,
        "DOCUMENTS_ENABLED": True,
    }
    with pytest.raises(ConfigError, match="DOCUMENT_STORAGE_BACKEND"):
        Settings.load(base)
    s3_ready = {
        **base,
        "RLS_ENABLED": True,
        "DOCUMENT_STORAGE_BACKEND": "s3",
        "DOCUMENT_S3_ENDPOINT_URL": "https://s3.example.test",
        "DOCUMENT_S3_REGION": "eu-west-1",
        "DOCUMENT_S3_BUCKET": "oracle-documents",
        "DOCUMENT_S3_ACCESS_KEY_ID": "access",
        "DOCUMENT_S3_SECRET_ACCESS_KEY": "secret",
        "DOCUMENT_S3_ALLOWED_HOSTS": "s3.example.test",
    }
    with pytest.raises(ConfigError, match="DOCUMENT_SCANNER_MODE=clamav"):
        Settings.load(s3_ready)
    settings = Settings.load({**s3_ready, "DOCUMENT_ALLOW_OFFICIAL_UNSCANNED": True})
    assert settings.document_scanner_mode == "noop"
    assert settings.document_allow_official_unscanned is True


@pytest.mark.unit
def test_text_csv_docx_and_pdf_parsers_cover_safe_paths(monkeypatch: pytest.MonkeyPatch) -> None:
    text = TextParser().parse(
        io.BytesIO(b"00:00:01.000 --> 00:00:03.000\nAna: acuerdo\n\nSegundo bloque")
    )
    assert text.blocks[0].locator["time_start"] == "00:00:01.000"
    with pytest.raises(ParseError, match="UTF-8"):
        TextParser().parse(io.BytesIO(b"\xff"))
    csv = CSVParser().parse(io.BytesIO(b"nombre,valor\nuno,=2+2"))
    assert csv.blocks[1].text.endswith("'=2+2")
    monkeypatch.setattr("opn_oracle.documents.parsers.MAX_CSV_COLUMNS", 1)
    with pytest.raises(ParseError, match="columnas"):
        CSVParser().parse(io.BytesIO(b"a,b"))
    docx = io.BytesIO()
    with zipfile.ZipFile(docx, "w") as archive:
        archive.writestr(
            "word/document.xml",
            '<w:document xmlns:w="http://schemas.openxmlformats.org/'
            'wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>Texto trazable</w:t>'
            "</w:r></w:p></w:body></w:document>",
        )
    docx.seek(0)
    assert DOCXParser().parse(docx).blocks[0].locator == {"paragraph": 1}
    active = io.BytesIO()
    with zipfile.ZipFile(active, "w") as archive:
        archive.writestr("word/document.xml", "<x/>")
        archive.writestr("word/vbaProject.bin", b"macro")
    active.seek(0)
    with pytest.raises(ParseError, match="activo"):
        DOCXParser().parse(active)
    from pypdf import PdfWriter

    pdf = io.BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.write(pdf)
    pdf.seek(0)
    assert PDFParser().parse(pdf).blocks == ()
    assert parser_for("text/plain").media_types
    with pytest.raises(ParseError, match="Formato"):
        parser_for("application/octet-stream")
    with pytest.raises(ValueError, match="chunking"):
        chunk_document(text, target_chars=10)


@pytest.mark.unit
def test_clamav_protocol_clean_infected_and_unavailable(monkeypatch: pytest.MonkeyPatch) -> None:
    class Socket:
        def __init__(self, response: bytes) -> None:
            self.response = response
            self.sent = b""

        def __enter__(self) -> Socket:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def settimeout(self, value: float) -> None:
            assert value == 1

        def sendall(self, value: bytes) -> None:
            self.sent += value

        def recv(self, size: int) -> bytes:
            return self.response[:size]

    clean = Socket(b"stream: OK\0")
    monkeypatch.setattr("socket.create_connection", lambda *args, **kwargs: clean)
    scanner = ClamAVScanner("clamav", 3310, 1, 20)
    assert scanner.scan(io.BytesIO(b"safe")) == ScanResult("clean", "clamav")
    infected = Socket(b"stream: Test-Signature FOUND\0")
    monkeypatch.setattr("socket.create_connection", lambda *args, **kwargs: infected)
    assert scanner.scan(io.BytesIO(b"bad")).status == "infected"
    unknown = Socket(b"stream: ERROR\0")
    monkeypatch.setattr("socket.create_connection", lambda *args, **kwargs: unknown)
    with pytest.raises(ScannerUnavailable):
        scanner.scan(io.BytesIO(b"bad"))
    monkeypatch.setattr(
        "socket.create_connection", lambda *args, **kwargs: (_ for _ in ()).throw(OSError())
    )
    with pytest.raises(ScannerUnavailable):
        scanner.scan(io.BytesIO(b"bad"))


@pytest.mark.unit
def test_s3_adapter_is_pinned_streaming_and_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    class Body(io.BytesIO):
        pass

    class Paginator:
        def paginate(self, **kwargs: object) -> list[dict[str, object]]:
            return [{"Contents": [{"Key": key, "LastModified": datetime.now(UTC)}]}]

    class Client:
        uploaded = b""

        def upload_fileobj(
            self, source: object, bucket: str, key_value: str, ExtraArgs: object
        ) -> None:
            self.uploaded = source.read()  # type: ignore[attr-defined]

        def get_object(self, **kwargs: object) -> dict[str, object]:
            return {"Body": Body(b"stored")}

        def delete_object(self, **kwargs: object) -> None:
            return None

        def generate_presigned_url(self, *args: object, **kwargs: object) -> str:
            return "https://8.8.8.8/signed"

        def head_bucket(self, **kwargs: object) -> None:
            return None

        def get_paginator(self, name: str) -> Paginator:
            return Paginator()

    client = Client()
    monkeypatch.setattr("boto3.client", lambda *args, **kwargs: client)
    tenant, dossier, document = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    key = object_key(tenant, dossier, document)
    storage = S3ObjectStorage(
        endpoint_url="https://8.8.8.8",
        region="eu-test-1",
        bucket="oracle",
        access_key="key",
        secret_key="secret",
        allowed_hosts=frozenset({"8.8.8.8"}),
    )
    assert (
        storage.put(key, io.BytesIO(b"stream"), max_bytes=10, media_type="text/plain").byte_size
        == 6
    )
    assert storage.get(key).read() == b"stored"
    assert storage.signed_download(key) == "https://8.8.8.8/signed"
    assert storage.health() is True and storage.iter_objects(tenant)[0].key == key
    storage.delete(key)
    with pytest.raises(StorageError):
        S3ObjectStorage(
            endpoint_url="https://user:pass@s3.example",
            region="eu",
            bucket="oracle",
            access_key="key",
            secret_key="secret",
            allowed_hosts=frozenset({"s3.example"}),
        )


@pytest.mark.unit
def test_additional_fail_closed_parser_scanner_and_storage_branches(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert NoopScanner().scan(io.BytesIO(b"x")).status == "not_configured"
    with pytest.raises(ParseError, match="JSON"):
        TranscriptJSONParser().parse(io.BytesIO(b"{"))
    with pytest.raises(ParseError, match="segmentos"):
        TranscriptJSONParser().parse(io.BytesIO(b"{}"))
    with pytest.raises(ParseError, match="Segmento"):
        TranscriptJSONParser().parse(io.BytesIO(b'{"segments":[1]}'))
    with pytest.raises(ParseError, match="PDF"):
        PDFParser().parse(io.BytesIO(b"not-pdf"))

    class TooLargeSocket:
        def __enter__(self) -> TooLargeSocket:
            return self

        def __exit__(self, *args: object) -> None:
            return None

        def settimeout(self, value: float) -> None:
            return None

        def sendall(self, value: bytes) -> None:
            return None

        def recv(self, size: int) -> bytes:
            return b"stream: OK\0"

    monkeypatch.setattr("socket.create_connection", lambda *args, **kwargs: TooLargeSocket())
    with pytest.raises(ScannerUnavailable, match="límite"):
        ClamAVScanner("clamav", 3310, 1, 1).scan(io.BytesIO(b"too large"))
    storage = LocalObjectStorage(tmp_path / "more-local")
    assert storage.health() is True
    assert storage.signed_download(object_key(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())) is None
    assert storage.iter_objects(uuid.uuid4()) == ()
    missing = object_key(uuid.uuid4(), uuid.uuid4(), uuid.uuid4())
    storage.delete(missing)
    with pytest.raises(StorageError, match="disponible"):
        storage.get(missing)
    assert safe_filename("...\r\n") == "documento"
    with pytest.raises(DocumentError, match="Formato"):
        verify_magic(io.BytesIO(b"data"), "application/octet-stream")
    with pytest.raises(DocumentError, match="DOCX"):
        verify_magic(
            io.BytesIO(b"not-a-zip"),
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )
    with pytest.raises(StorageError, match="Endpoint"):
        S3ObjectStorage(
            endpoint_url="https://127.0.0.1",
            region="eu",
            bucket="oracle",
            access_key="key",
            secret_key="secret",
            allowed_hosts=frozenset({"127.0.0.1"}),
        )
