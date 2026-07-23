#!/usr/bin/env python3
"""Private, local Apple Vision OCR for the five INV-03 image-only PDFs.

The script is intentionally outside the Oracle runtime. It accepts only objects
already revalidated from the private quarantine and writes page text below that
private work directory. OCR remains candidate evidence, never an automatic fact.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from investigation_documents import load_reusable_quarantined_references
from investigation_harness import sha256_json

JsonObject = dict[str, Any]
OCR_SCHEMA_VERSION = "apple-vision-ocr/v1"
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORK_DIR = (
    REPO_ROOT / "docs" / "implementation" / "spikes" / ".work" / "79" / "default"
)
DEFAULT_VISION_SCRIPT = Path(__file__).with_name("vision_ocr.swift")


def _write_private_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    os.chmod(path, 0o600)


def ocr_fingerprint(
    *,
    document_sha256: str,
    vision_script_sha256: str,
    dpi: int,
    pages: int,
) -> str:
    return sha256_json(
        {
            "schema_version": OCR_SCHEMA_VERSION,
            "document_sha256": document_sha256,
            "vision_script_sha256": vision_script_sha256,
            "dpi": dpi,
            "pages": pages,
            "recognition_level": "accurate",
            "languages": ["es-ES", "en-US"],
        }
    )


def normalize_vision_page(value: Mapping[str, Any]) -> str:
    lines = value.get("lines")
    line_count = value.get("line_count")
    if not isinstance(lines, list) or not isinstance(line_count, int):
        raise ValueError("Vision OCR output lacks lines or line_count")
    if line_count != len(lines):
        raise ValueError("Vision OCR line_count does not match lines")
    if any(not isinstance(line, str) for line in lines):
        raise ValueError("Vision OCR lines must be strings")
    normalized = [line.strip() for line in lines if line.strip()]
    if not normalized:
        raise ValueError("Vision OCR page has no text")
    return "\n".join(normalized)


def build_ocr_document(
    *,
    source_ref_id: str,
    document_sha256: str,
    page_texts: Mapping[int, str],
    dpi: int,
    fingerprint: str,
) -> JsonObject:
    blocks = [
        {
            "text": text,
            "locator": {
                "page": page,
                "ocr": "apple_vision",
                "dpi": dpi,
            },
            "text_sha256": hashlib.sha256(text.encode()).hexdigest(),
        }
        for page, text in sorted(page_texts.items())
    ]
    return {
        "schema_version": OCR_SCHEMA_VERSION,
        "fingerprint": fingerprint,
        "source_ref_id": source_ref_id,
        "status": "parsed_ocr",
        "authorization": "internal_unscanned_authorized",
        "media_kind": "pdf",
        "document_sha256": document_sha256,
        "parser_name": "apple_vision",
        "parser_version": OCR_SCHEMA_VERSION,
        "blocks": blocks,
        "limitations": [
            "ocr_text_may_misrecognize",
            "candidate_only_human_review_required",
        ],
    }


def _pdf_page_count(pdf_path: Path) -> int:
    completed = subprocess.run(
        ["pdfinfo", str(pdf_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    for line in completed.stdout.splitlines():
        if line.startswith("Pages:"):
            pages = int(line.split(":", maxsplit=1)[1].strip())
            if pages > 0:
                return pages
    raise ValueError(f"pdfinfo returned no positive page count for {pdf_path.name}")


def _ocr_required_source_ids(
    *,
    work_dir: Path,
    references: Mapping[str, Mapping[str, Any]],
) -> list[str]:
    source_ids = []
    for source_ref_id, reference in sorted(references.items()):
        parsed_path = work_dir / "parsed" / f"{source_ref_id}.json"
        if not parsed_path.exists():
            continue
        parsed = json.loads(parsed_path.read_text(encoding="utf-8"))
        if (
            isinstance(parsed, dict)
            and parsed.get("status") == "ocr_required"
            and parsed.get("document_sha256") == reference.get("sha256")
        ):
            source_ids.append(source_ref_id)
    return source_ids


def _recognize_page(
    *,
    pdf_path: Path,
    page: int,
    dpi: int,
    vision_script: Path,
    timeout_seconds: float,
    temporary_dir: Path,
) -> str | None:
    prefix = temporary_dir / f"page-{page:04d}"
    subprocess.run(
        [
            "pdftoppm",
            "-f",
            str(page),
            "-l",
            str(page),
            "-r",
            str(dpi),
            "-png",
            str(pdf_path),
            str(prefix),
        ],
        check=True,
        capture_output=True,
        timeout=timeout_seconds,
    )
    images = sorted(temporary_dir.glob(f"{prefix.name}-*.png"))
    if len(images) != 1:
        raise ValueError(f"Expected one rendered page image for page {page}")
    completed = subprocess.run(
        ["/usr/bin/swift", str(vision_script), str(images[0])],
        check=True,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
    )
    try:
        value = json.loads(completed.stdout)
    except json.JSONDecodeError as error:
        raise ValueError(f"Vision OCR emitted invalid JSON for page {page}") from error
    if not isinstance(value, dict):
        raise ValueError(f"Vision OCR emitted a non-object for page {page}")
    try:
        return normalize_vision_page(value)
    except ValueError as error:
        if str(error) == "Vision OCR page has no text":
            return None
        raise


def run_local_vision_ocr(
    *,
    work_dir: Path,
    vision_script: Path,
    dpi: int,
    max_documents: int,
    max_pages_per_document: int,
    timeout_seconds: float,
) -> JsonObject:
    if dpi < 72:
        raise ValueError("dpi must be at least 72")
    if max_documents < 1 or max_pages_per_document < 1:
        raise ValueError("document and page limits must be positive")
    if shutil.which("pdftoppm") is None or not Path("/usr/bin/swift").is_file():
        raise RuntimeError("local PDF rendering or Apple Vision runtime is unavailable")
    if not vision_script.is_file():
        raise ValueError("Vision OCR script is unavailable")
    script_sha256 = hashlib.sha256(vision_script.read_bytes()).hexdigest()
    references = {
        item.source_ref_id: {
            "sha256": item.sha256,
            "path": item.object_path,
            "media_kind": item.media_kind,
        }
        for item in load_reusable_quarantined_references(work_dir / "quarantine")
        if item.sha256 is not None and item.object_path is not None
    }
    selected_ids = _ocr_required_source_ids(work_dir=work_dir, references=references)[
        :max_documents
    ]
    results = []
    for source_ref_id in selected_ids:
        reference = references[source_ref_id]
        if reference["media_kind"] != "pdf":
            continue
        pdf_path = Path(str(reference["path"]))
        page_count = _pdf_page_count(pdf_path)
        if page_count > max_pages_per_document:
            results.append(
                {
                    "source_ref_id": source_ref_id,
                    "status": "page_limit_exceeded",
                    "pages": page_count,
                }
            )
            continue
        fingerprint = ocr_fingerprint(
            document_sha256=str(reference["sha256"]),
            vision_script_sha256=script_sha256,
            dpi=dpi,
            pages=page_count,
        )
        cache_path = work_dir / "ocr_vision" / f"{source_ref_id}.json"
        cached: JsonObject | None = None
        if cache_path.exists():
            value = json.loads(cache_path.read_text(encoding="utf-8"))
            if isinstance(value, dict) and value.get("fingerprint") == fingerprint:
                cached = value
        reused = cached is not None
        if cached is None:
            with tempfile.TemporaryDirectory(prefix="inv-ocr-", dir=work_dir) as name:
                temporary_dir = Path(name)
                page_texts: dict[int, str] = {}
                empty_pages = 0
                for page in range(1, page_count + 1):
                    text = _recognize_page(
                        pdf_path=pdf_path,
                        page=page,
                        dpi=dpi,
                        vision_script=vision_script,
                        timeout_seconds=timeout_seconds,
                        temporary_dir=temporary_dir,
                    )
                    if text is None:
                        empty_pages += 1
                    else:
                        page_texts[page] = text
            if page_texts:
                cached = build_ocr_document(
                    source_ref_id=source_ref_id,
                    document_sha256=str(reference["sha256"]),
                    page_texts=page_texts,
                    dpi=dpi,
                    fingerprint=fingerprint,
                )
                cached["empty_pages"] = empty_pages
            else:
                cached = {
                    "schema_version": OCR_SCHEMA_VERSION,
                    "fingerprint": fingerprint,
                    "source_ref_id": source_ref_id,
                    "status": "ocr_no_text",
                    "blocks": [],
                    "empty_pages": empty_pages,
                    "limitations": ["ocr_no_text"],
                }
            _write_private_json(cache_path, cached)
        blocks = cached.get("blocks", [])
        results.append(
            {
                "source_ref_id": source_ref_id,
                "status": str(cached.get("status")),
                "reused": reused,
                "pages": len(blocks) if isinstance(blocks, list) else 0,
                "empty_pages": int(cached.get("empty_pages") or 0),
                "characters": sum(
                    len(str(block.get("text") or ""))
                    for block in blocks
                    if isinstance(block, dict)
                )
                if isinstance(blocks, list)
                else 0,
            }
        )
    return {
        "schema_version": OCR_SCHEMA_VERSION,
        "selected_documents": len(results),
        "ocr_documents": sum(result["status"] == "parsed_ocr" for result in results),
        "reused_documents": sum(result.get("reused", False) for result in results),
        "pages": sum(int(result.get("pages") or 0) for result in results),
        "empty_pages": sum(int(result.get("empty_pages") or 0) for result in results),
        "characters": sum(int(result.get("characters") or 0) for result in results),
        "results": results,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--vision-script", type=Path, default=DEFAULT_VISION_SCRIPT)
    parser.add_argument("--dpi", type=int, default=120)
    parser.add_argument("--max-documents", type=int, default=5)
    parser.add_argument("--max-pages-per-document", type=int, default=20)
    parser.add_argument("--timeout-seconds", type=float, default=90)
    return parser.parse_args()


if __name__ == "__main__":
    args = parse_args()
    result = run_local_vision_ocr(
        work_dir=args.work_dir.resolve(),
        vision_script=args.vision_script.resolve(),
        dpi=args.dpi,
        max_documents=args.max_documents,
        max_pages_per_document=args.max_pages_per_document,
        timeout_seconds=args.timeout_seconds,
    )
    print(
        json.dumps(
            {key: value for key, value in result.items() if key != "results"},
            ensure_ascii=False,
            sort_keys=True,
        )
    )
