#!/usr/bin/env python3
"""Run a private, blind human-review session for INV-03 material.

This helper stays outside Oracle runtime and never calls a model, a network source
or Signal. It only joins an annotator's opaque blank sheet to their opaque material
index, opens already quarantined local objects on request, and writes the sheet
atomically under the ignored private workdir.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from collections.abc import Callable, Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

JsonObject = dict[str, Any]
Prompt = Callable[[str], str]
OpenCommand = Callable[..., subprocess.CompletedProcess[str]]

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORK_DIR = REPO_ROOT / "docs" / "implementation" / "spikes" / ".work" / "79" / "default"
LABEL_FIELDS = (
    "reference_published",
    "download_valid",
    "relevant_for_participation",
    "nominal_content",
    "role_by_lot",
    "list_complete_or_reconcilable",
)
FORBIDDEN_BLIND_KEYS = frozenset(
    {
        "sample_id",
        "winner_names",
        "url",
        "candidate_output",
        "ollama_output",
    }
)
ALLOWED_OBJECT_SUFFIXES = frozenset({".pdf", ".docx"})


def _read_list(path: Path, *, name: str) -> list[JsonObject]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(item, dict) for item in value):
        raise ValueError(f"{name} must be a JSON list of objects")
    return [dict(item) for item in value]


def _private_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path.parent, 0o700)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True), encoding="utf-8"
    )
    os.chmod(temporary, 0o600)
    temporary.replace(path)
    os.chmod(path, 0o600)


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, Mapping):
        for key, child in value.items():
            yield str(key)
            yield from _walk_keys(child)
    elif isinstance(value, list):
        for child in value:
            yield from _walk_keys(child)


def _by_annotation_id(rows: Sequence[Mapping[str, Any]], *, name: str) -> dict[str, JsonObject]:
    indexed: dict[str, JsonObject] = {}
    for row in rows:
        annotation_id = row.get("annotation_id")
        if not isinstance(annotation_id, str) or not annotation_id:
            raise ValueError(f"{name} contains an invalid annotation_id")
        if annotation_id in indexed:
            raise ValueError(f"{name} repeats annotation_id {annotation_id}")
        indexed[annotation_id] = dict(row)
    return indexed


def validate_blind_workspace(
    annotations: Sequence[Mapping[str, Any]], materials: Sequence[Mapping[str, Any]]
) -> None:
    """Reject an incomplete, mismatched or contaminated reviewer workspace."""

    annotation_index = _by_annotation_id(annotations, name="annotations")
    material_index = _by_annotation_id(materials, name="materials")
    if annotation_index.keys() != material_index.keys():
        raise ValueError("annotations and materials must contain the same annotation_id set")
    forbidden = FORBIDDEN_BLIND_KEYS.intersection(_walk_keys(materials))
    if forbidden:
        raise ValueError(f"reviewer materials contain forbidden blind keys: {sorted(forbidden)}")
    for material in materials:
        references = material.get("references")
        if not isinstance(references, list):
            raise ValueError("reviewer material references must be a list")
        for reference in references:
            if not isinstance(reference, Mapping):
                raise ValueError("reviewer material reference must be an object")
            source_ref_id = reference.get("source_ref_id")
            if not isinstance(source_ref_id, str) or len(source_ref_id) != 64:
                raise ValueError("reviewer material source_ref_id must be an opaque SHA-256")
            availability = reference.get("availability")
            if availability not in {"available", "not_acquired"}:
                raise ValueError("reviewer material availability is invalid")
            object_name = reference.get("object_name")
            if availability == "available":
                if not isinstance(object_name, str):
                    raise ValueError("available material must name its local object")
                object_path = Path(object_name)
                if (
                    object_path.name != object_name
                    or object_path.suffix not in ALLOWED_OBJECT_SUFFIXES
                ):
                    raise ValueError("reviewer material object_name is unsafe")
                if object_path.stem != source_ref_id:
                    raise ValueError("reviewer material object_name does not match source_ref_id")
            elif object_name is not None:
                raise ValueError("not_acquired material must not name a local object")


def review_state(annotation: Mapping[str, Any]) -> str:
    state = annotation.get("review_status", "pending")
    if state not in {"pending", "completed"}:
        raise ValueError("review_status must be pending or completed")
    return str(state)


def reviewer_progress(annotations: Sequence[Mapping[str, Any]]) -> JsonObject:
    completed = sum(review_state(row) == "completed" for row in annotations)
    return {
        "total": len(annotations),
        "completed": completed,
        "pending": len(annotations) - completed,
    }


def next_pending_annotation_id(annotations: Sequence[Mapping[str, Any]]) -> str | None:
    for row in annotations:
        if review_state(row) == "pending":
            annotation_id = row.get("annotation_id")
            if isinstance(annotation_id, str):
                return annotation_id
    return None


def resolve_available_objects(material: Mapping[str, Any], *, quarantine_dir: Path) -> list[Path]:
    root = quarantine_dir.resolve()
    if not root.is_dir():
        raise ValueError("quarantine directory is not available")
    objects: list[Path] = []
    references = material.get("references", [])
    if not isinstance(references, list):
        raise ValueError("reviewer material references must be a list")
    for reference in references:
        if not isinstance(reference, Mapping) or reference.get("availability") != "available":
            continue
        object_name = reference.get("object_name")
        if not isinstance(object_name, str):
            raise ValueError("available material has no object_name")
        path = (root / object_name).resolve()
        if path.parent != root or not path.is_file():
            raise ValueError("available reviewer object is missing or escaped quarantine")
        objects.append(path)
    return objects


def _parse_tristate(raw: str) -> bool | None:
    normalized = raw.strip().casefold()
    if normalized in {"s", "si", "sí", "yes", "y"}:
        return True
    if normalized in {"n", "no"}:
        return False
    if normalized in {"?", "unknown", "desconocido", "no determinable"}:
        return None
    raise ValueError("responde s, n o ?")


def _parse_json_list(raw: str, *, field: str) -> list[Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as error:
        raise ValueError(f"{field} debe ser JSON válido") from error
    if not isinstance(value, list):
        raise ValueError(f"{field} debe ser una lista JSON")
    return value


def complete_annotation(
    annotation: Mapping[str, Any],
    *,
    labels: Mapping[str, bool | None],
    participants: list[Any],
    ambiguities: list[Any],
    notes: str,
    now: datetime | None = None,
) -> JsonObject:
    if set(labels) != set(LABEL_FIELDS):
        raise ValueError("the completed review must provide every label field")
    result = dict(annotation)
    existing_labels = result.get("labels")
    if not isinstance(existing_labels, Mapping):
        raise ValueError("annotation labels must be an object")
    result["labels"] = {
        **dict(existing_labels),
        **dict(labels),
        "participants": participants,
        "ambiguities": ambiguities,
        "notes": notes or None,
    }
    result["review_status"] = "completed"
    timestamp = now or datetime.now(UTC)
    result["review_completed_at_utc"] = timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z")
    return result


def run_interactive_review(annotation: Mapping[str, Any], *, prompt: Prompt = input) -> JsonObject:
    print("Responde s (sí), n (no) o ? (no determinable).")
    labels: dict[str, bool | None] = {}
    for field in LABEL_FIELDS:
        while True:
            try:
                labels[field] = _parse_tristate(prompt(f"{field}: "))
                break
            except ValueError as error:
                print(error)
    while True:
        try:
            participants = _parse_json_list(
                prompt("participants JSON ([] si ninguno): "), field="participants"
            )
            break
        except ValueError as error:
            print(error)
    while True:
        try:
            ambiguities = _parse_json_list(
                prompt("ambiguities JSON ([] si ninguna): "), field="ambiguities"
            )
            break
        except ValueError as error:
            print(error)
    notes = prompt("notas (opcional): ").strip()
    return complete_annotation(
        annotation,
        labels=labels,
        participants=participants,
        ambiguities=ambiguities,
        notes=notes,
    )


def execute(args: argparse.Namespace, *, open_command: OpenCommand = subprocess.run) -> JsonObject:
    annotations = _read_list(args.annotations, name="annotations")
    materials = _read_list(args.materials, name="materials")
    validate_blind_workspace(annotations, materials)
    annotation_index = _by_annotation_id(annotations, name="annotations")
    material_index = _by_annotation_id(materials, name="materials")
    progress = reviewer_progress(annotations)
    if args.status:
        return {"progress": progress, "next_annotation_id": next_pending_annotation_id(annotations)}
    annotation_id = args.annotation_id or next_pending_annotation_id(annotations)
    if annotation_id is None:
        return {"progress": progress, "status": "all_completed"}
    if annotation_id not in annotation_index:
        raise ValueError("annotation_id is not assigned to this reviewer")
    objects = resolve_available_objects(
        material_index[annotation_id], quarantine_dir=args.quarantine_dir
    )
    if args.open:
        for path in objects:
            open_command(["open", str(path)], check=True, text=True)
    if not args.review:
        return {
            "progress": progress,
            "annotation_id": annotation_id,
            "available_objects": len(objects),
            "status": review_state(annotation_index[annotation_id]),
        }
    if review_state(annotation_index[annotation_id]) == "completed" and not args.reopen_completed:
        raise ValueError("annotation is already completed; pass --reopen-completed to edit it")
    updated = run_interactive_review(annotation_index[annotation_id])
    updated_rows = [
        updated if row["annotation_id"] == annotation_id else row for row in annotations
    ]
    _private_write_json(args.annotations, updated_rows)
    return {
        "progress": reviewer_progress(updated_rows),
        "annotation_id": annotation_id,
        "available_objects": len(objects),
        "status": "completed",
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--annotator", choices=("a", "b"), required=True)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--annotations", type=Path)
    parser.add_argument("--materials", type=Path)
    parser.add_argument("--quarantine-dir", type=Path)
    parser.add_argument("--annotation-id")
    parser.add_argument("--status", action="store_true")
    parser.add_argument(
        "--open",
        action="store_true",
        help="Open only verified local objects for the selected row.",
    )
    parser.add_argument(
        "--review", action="store_true", help="Prompt and save one completed human review."
    )
    parser.add_argument("--reopen-completed", action="store_true")
    args = parser.parse_args()
    reviewer_dir = args.work_dir / "gold" / f"annotator_{args.annotator}"
    args.annotations = args.annotations or reviewer_dir / "blank.json"
    args.materials = args.materials or reviewer_dir / "materials.json"
    args.quarantine_dir = args.quarantine_dir or args.work_dir / "quarantine"
    if args.status and (args.open or args.review or args.annotation_id):
        parser.error("--status cannot be combined with --open, --review or --annotation-id")
    if args.reopen_completed and not args.review:
        parser.error("--reopen-completed requires --review")
    return args


if __name__ == "__main__":
    print(json.dumps(execute(parse_args()), ensure_ascii=False, indent=2, sort_keys=True))
