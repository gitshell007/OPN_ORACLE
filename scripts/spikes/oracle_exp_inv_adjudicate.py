#!/usr/bin/env python3
"""Prepare a private, blind adjudication queue from completed INV-03 A/B reviews."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from oracle_exp_inv_reviewer import (
    LABEL_FIELDS,
    _by_annotation_id,
    _read_list,
    review_state,
    validate_blind_workspace,
)

JsonObject = dict[str, Any]
REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_WORK_DIR = REPO_ROOT / "docs" / "implementation" / "spikes" / ".work" / "79" / "default"
COMPARE_FIELDS = (*LABEL_FIELDS, "participants", "ambiguities")


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


def _load_coordinator(path: Path) -> list[JsonObject]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, list) or not all(isinstance(row, dict) for row in value):
        raise ValueError("coordinator mapping must be a JSON list of objects")
    return [dict(row) for row in value]


def _comparison_value(labels: Mapping[str, Any], field: str) -> str:
    value = labels.get(field)
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _material_references(material: Mapping[str, Any]) -> list[JsonObject]:
    references = material.get("references")
    if not isinstance(references, list):
        raise ValueError("reviewer material references must be a list")
    result = []
    for reference in references:
        if not isinstance(reference, Mapping):
            raise ValueError("reviewer material reference must be an object")
        result.append(dict(reference))
    return result


def build_adjudication_queue(
    *,
    coordinator: Sequence[Mapping[str, Any]],
    annotations_a: Sequence[Mapping[str, Any]],
    materials_a: Sequence[Mapping[str, Any]],
    annotations_b: Sequence[Mapping[str, Any]],
    materials_b: Sequence[Mapping[str, Any]],
) -> JsonObject:
    """Return only opaque A/B pairs and their factual disagreements.

    The coordinator map is used to match pairs but does not appear in the result, so
    the queue contains neither `sample_id` nor a structured winner/model output.
    """

    validate_blind_workspace(annotations_a, materials_a)
    validate_blind_workspace(annotations_b, materials_b)
    annotations_a_by_id = _by_annotation_id(annotations_a, name="annotator A annotations")
    annotations_b_by_id = _by_annotation_id(annotations_b, name="annotator B annotations")
    materials_a_by_id = _by_annotation_id(materials_a, name="annotator A materials")
    materials_b_by_id = _by_annotation_id(materials_b, name="annotator B materials")

    queue: list[JsonObject] = []
    paired = completed_pairs = agreed = awaiting = 0
    seen_a: set[str] = set()
    seen_b: set[str] = set()
    for mapping in coordinator:
        if mapping.get("double_blind") is not True:
            continue
        a_id = mapping.get("annotator_a_id")
        b_id = mapping.get("annotator_b_id")
        if not isinstance(a_id, str) or not isinstance(b_id, str):
            raise ValueError("double-blind coordinator row has invalid annotation ids")
        if a_id in seen_a or b_id in seen_b:
            raise ValueError("coordinator mapping repeats an annotator id")
        seen_a.add(a_id)
        seen_b.add(b_id)
        if a_id not in annotations_a_by_id or b_id not in annotations_b_by_id:
            raise ValueError("coordinator mapping points outside reviewer sheets")
        paired += 1
        a_row = annotations_a_by_id[a_id]
        b_row = annotations_b_by_id[b_id]
        if review_state(a_row) != "completed" or review_state(b_row) != "completed":
            awaiting += 1
            continue
        completed_pairs += 1
        a_labels = a_row.get("labels")
        b_labels = b_row.get("labels")
        if not isinstance(a_labels, Mapping) or not isinstance(b_labels, Mapping):
            raise ValueError("completed annotation labels must be objects")
        disagreements = {
            field: {"annotator_a": a_labels.get(field), "annotator_b": b_labels.get(field)}
            for field in COMPARE_FIELDS
            if _comparison_value(a_labels, field) != _comparison_value(b_labels, field)
        }
        if not disagreements:
            agreed += 1
            continue
        references_a = _material_references(materials_a_by_id[a_id])
        references_b = _material_references(materials_b_by_id[b_id])
        if references_a != references_b:
            raise ValueError("paired annotators received different reviewer materials")
        queue.append(
            {
                "adjudication_id": hashlib.sha256(f"{a_id}\0{b_id}".encode()).hexdigest()[:24],
                "annotator_a_id": a_id,
                "annotator_b_id": b_id,
                "references": references_a,
                "disagreements": disagreements,
                "adjudication_status": "pending",
            }
        )
    return {
        "summary": {
            "double_blind_pairs": paired,
            "completed_pairs": completed_pairs,
            "awaiting_pairs": awaiting,
            "agreed_pairs": agreed,
            "disagreement_pairs": len(queue),
            "adjudicated_pairs": 0,
        },
        "queue": queue,
    }


def execute(args: argparse.Namespace) -> JsonObject:
    annotations_a = _read_list(args.annotations_a, name="annotator A annotations")
    materials_a = _read_list(args.materials_a, name="annotator A materials")
    annotations_b = _read_list(args.annotations_b, name="annotator B annotations")
    materials_b = _read_list(args.materials_b, name="annotator B materials")
    result = build_adjudication_queue(
        coordinator=_load_coordinator(args.coordinator),
        annotations_a=annotations_a,
        materials_a=materials_a,
        annotations_b=annotations_b,
        materials_b=materials_b,
    )
    if args.write_queue:
        _private_write_json(args.output, result)
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument("--coordinator", type=Path)
    parser.add_argument("--annotations-a", type=Path)
    parser.add_argument("--materials-a", type=Path)
    parser.add_argument("--annotations-b", type=Path)
    parser.add_argument("--materials-b", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--write-queue", action="store_true")
    args = parser.parse_args()
    args.coordinator = args.coordinator or args.work_dir / "coordinator.json"
    args.annotations_a = args.annotations_a or args.work_dir / "gold" / "annotator_a" / "blank.json"
    args.materials_a = args.materials_a or args.work_dir / "gold" / "annotator_a" / "materials.json"
    args.annotations_b = args.annotations_b or args.work_dir / "gold" / "annotator_b" / "blank.json"
    args.materials_b = args.materials_b or args.work_dir / "gold" / "annotator_b" / "materials.json"
    args.output = args.output or args.work_dir / "gold" / "adjudication" / "queue.json"
    return args


if __name__ == "__main__":
    print(json.dumps(execute(parse_args()), ensure_ascii=False, indent=2, sort_keys=True))
