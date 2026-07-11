"""Bounded, non-executing parsers with structural provenance."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from dataclasses import dataclass
from typing import BinaryIO, Protocol
from xml.etree import ElementTree

from pypdf import PdfReader

PARSER_VERSION = "documents-parser-v1"
CHUNKER_VERSION = "structure-800-v1"
MAX_ZIP_ENTRIES = 2_000
MAX_ZIP_UNCOMPRESSED = 50 * 1024 * 1024
MAX_ZIP_ENTRY_BYTES = 20 * 1024 * 1024
MAX_ZIP_RATIO = 100
MAX_CSV_ROWS = 20_000
MAX_CSV_COLUMNS = 200
MAX_PDF_PAGES = 500
MAX_EXTRACTED_CHARS = 5_000_000
MAX_TRANSCRIPT_SEGMENTS = 50_000


class ParseError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class ParsedBlock:
    text: str
    locator: dict[str, int | str]


@dataclass(frozen=True, slots=True)
class ParsedDocument:
    parser_name: str
    parser_version: str
    blocks: tuple[ParsedBlock, ...]


@dataclass(frozen=True, slots=True)
class ChunkData:
    sequence: int
    text: str
    locator: dict[str, int | str]
    char_start: int
    char_end: int
    checksum: bytes


class DocumentParser(Protocol):
    media_types: frozenset[str]

    def parse(self, source: BinaryIO) -> ParsedDocument: ...


def normalize_text(value: str) -> str:
    value = value.replace("\x00", "").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in value.splitlines()).strip()


class TextParser:
    media_types = frozenset({"text/plain", "text/markdown", "text/vtt", "application/x-subrip"})

    def parse(self, source: BinaryIO) -> ParsedDocument:
        try:
            text = source.read().decode("utf-8-sig", errors="strict")
        except UnicodeDecodeError as exc:
            raise ParseError("El texto debe estar codificado en UTF-8.") from exc
        blocks: list[ParsedBlock] = []
        for number, paragraph in enumerate(re.split(r"\n\s*\n", text), start=1):
            clean = normalize_text(paragraph)
            if clean:
                locator: dict[str, int | str] = {"paragraph": number}
                timestamp = re.search(
                    r"(\d\d:\d\d(?::\d\d)?[.,]\d{3})\s*-->\s*(\d\d:\d\d(?::\d\d)?[.,]\d{3})", clean
                )
                if timestamp:
                    locator.update(
                        {"time_start": timestamp.group(1), "time_end": timestamp.group(2)}
                    )
                blocks.append(ParsedBlock(clean, locator))
        return ParsedDocument("text", PARSER_VERSION, tuple(blocks))


class CSVParser:
    media_types = frozenset({"text/csv"})

    def parse(self, source: BinaryIO) -> ParsedDocument:
        wrapper = io.TextIOWrapper(source, encoding="utf-8-sig", errors="strict", newline="")
        blocks: list[ParsedBlock] = []
        try:
            rows = csv.reader(wrapper)
            for number, row in enumerate(rows, start=1):
                if number > MAX_CSV_ROWS:
                    raise ParseError("El CSV supera el máximo de filas.")
                if len(row) > MAX_CSV_COLUMNS:
                    raise ParseError("El CSV supera el máximo de columnas.")
                # Prefix formulas so later spreadsheet exports cannot execute them.
                safe = [
                    f"'{cell}" if cell.startswith(("=", "+", "-", "@")) else cell for cell in row
                ]
                text = normalize_text(" | ".join(safe))
                if text:
                    blocks.append(ParsedBlock(text, {"row": number}))
        except (UnicodeDecodeError, csv.Error) as exc:
            raise ParseError("CSV inválido.") from exc
        return ParsedDocument("csv", PARSER_VERSION, tuple(blocks))


class PDFParser:
    media_types = frozenset({"application/pdf"})

    def parse(self, source: BinaryIO) -> ParsedDocument:
        try:
            reader = PdfReader(source, strict=True)
            if reader.is_encrypted:
                raise ParseError("No se admiten PDF cifrados.")
            if len(reader.pages) > MAX_PDF_PAGES:
                raise ParseError("El PDF supera el máximo de páginas.")
            blocks_list: list[ParsedBlock] = []
            extracted_chars = 0
            for page_number, page in enumerate(reader.pages, start=1):
                text = normalize_text(page.extract_text() or "")
                extracted_chars += len(text)
                if extracted_chars > MAX_EXTRACTED_CHARS:
                    raise ParseError("El PDF supera el máximo de texto extraído.")
                if text:
                    blocks_list.append(ParsedBlock(text, {"page": page_number}))
            blocks = tuple(blocks_list)
        except ParseError:
            raise
        except Exception as exc:
            raise ParseError("PDF inválido o no procesable.") from exc
        return ParsedDocument("pypdf", PARSER_VERSION, blocks)


class DOCXParser:
    media_types = frozenset(
        {"application/vnd.openxmlformats-officedocument.wordprocessingml.document"}
    )

    def parse(self, source: BinaryIO) -> ParsedDocument:
        try:
            with zipfile.ZipFile(source) as archive:
                infos = archive.infolist()
                if (
                    len(infos) > MAX_ZIP_ENTRIES
                    or sum(item.file_size for item in infos) > MAX_ZIP_UNCOMPRESSED
                    or any(item.file_size > MAX_ZIP_ENTRY_BYTES for item in infos)
                    or any(
                        item.file_size > max(1, item.compress_size) * MAX_ZIP_RATIO
                        for item in infos
                    )
                ):
                    raise ParseError("DOCX excede los límites de descompresión.")
                if any(item.filename.startswith("word/vbaProject") for item in infos):
                    raise ParseError("No se admite contenido activo.")
                xml = archive.read("word/document.xml")
        except ParseError:
            raise
        except (KeyError, zipfile.BadZipFile) as exc:
            raise ParseError("DOCX inválido.") from exc
        root = ElementTree.fromstring(xml)
        ns = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"
        blocks: list[ParsedBlock] = []
        for number, paragraph in enumerate(root.iter(f"{ns}p"), start=1):
            text = normalize_text("".join(node.text or "" for node in paragraph.iter(f"{ns}t")))
            if text:
                blocks.append(ParsedBlock(text, {"paragraph": number}))
        return ParsedDocument("docx-openxml", PARSER_VERSION, tuple(blocks))


class TranscriptJSONParser:
    media_types = frozenset({"application/vnd.opn.transcript+json"})

    def parse(self, source: BinaryIO) -> ParsedDocument:
        try:
            value = json.load(io.TextIOWrapper(source, encoding="utf-8-sig", errors="strict"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ParseError("Transcripción JSON inválida.") from exc
        segments = value.get("segments") if isinstance(value, dict) else None
        if not isinstance(segments, list) or len(segments) > MAX_TRANSCRIPT_SEGMENTS:
            raise ParseError("La transcripción no contiene segmentos válidos.")
        blocks: list[ParsedBlock] = []
        total = 0
        for number, segment in enumerate(segments, start=1):
            if not isinstance(segment, dict):
                raise ParseError("Segmento de transcripción inválido.")
            text = normalize_text(str(segment.get("text", "")))
            total += len(text)
            if total > MAX_EXTRACTED_CHARS:
                raise ParseError("La transcripción supera el máximo de texto.")
            if not text:
                continue
            locator: dict[str, int | str] = {"segment": number}
            for source_key, target_key in (
                ("speaker", "speaker"),
                ("start_ms", "time_start_ms"),
                ("end_ms", "time_end_ms"),
            ):
                if source_key in segment and isinstance(segment[source_key], (str, int)):
                    locator[target_key] = segment[source_key]
            blocks.append(ParsedBlock(text, locator))
        return ParsedDocument("transcript-json", PARSER_VERSION, tuple(blocks))


PARSERS: tuple[DocumentParser, ...] = (
    PDFParser(),
    DOCXParser(),
    CSVParser(),
    TranscriptJSONParser(),
    TextParser(),
)


def parser_for(media_type: str) -> DocumentParser:
    for parser in PARSERS:
        if media_type in parser.media_types:
            return parser
    raise ParseError("Formato no admitido.")


def chunk_document(
    parsed: ParsedDocument, *, target_chars: int = 800, overlap_chars: int = 100
) -> tuple[ChunkData, ...]:
    if target_chars < 200 or not 0 <= overlap_chars < target_chars:
        raise ValueError("Configuración de chunking inválida.")
    chunks: list[ChunkData] = []
    global_offset = 0
    for block in parsed.blocks:
        text = block.text
        start = 0
        while start < len(text):
            end = min(len(text), start + target_chars)
            if end < len(text):
                boundary = text.rfind(" ", start + target_chars // 2, end)
                if boundary > start:
                    end = boundary
            raw_piece = text[start:end]
            left_trim = len(raw_piece) - len(raw_piece.lstrip())
            piece = raw_piece.strip()
            if piece:
                char_start = global_offset + start + left_trim
                char_end = char_start + len(piece)
                locator = {
                    **block.locator,
                    "char_start": start + left_trim,
                    "char_end": start + left_trim + len(piece),
                }
                chunks.append(
                    ChunkData(
                        len(chunks),
                        piece,
                        locator,
                        char_start,
                        char_end,
                        hashlib.sha256(piece.encode()).digest(),
                    )
                )
            if end >= len(text):
                break
            start = max(start + 1, end - overlap_chars)
        global_offset += len(text) + 2
    return tuple(chunks)
