#!/usr/bin/env python3
"""Counted dry-run / apply for profile_config → DossierIntentRevision (MEMSOL residual).

Usage (from apps/api, with DB URL env as for other scripts):

  uv run python scripts/memsol_backfill_intent_revisions.py --dry-run
  uv run python scripts/memsol_backfill_intent_revisions.py --apply

Never invents zero: prints measured pre/post counts. Default is dry-run.
Does not activate monitores or call Signal.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import uuid
from datetime import UTC, datetime
from typing import Any


def _canonical_hash(schema_key: str, schema_version: str, request_text: str, spec: dict[str, Any]) -> str:
    material = json.dumps(
        {
            "schema_key": schema_key,
            "schema_version": schema_version,
            "request_text": request_text,
            "structured_spec": spec,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(material.encode("utf-8")).hexdigest()


def _schema_for_dossier_type(dossier_type: str, profile: dict[str, Any]) -> tuple[str, str]:
    version = str(profile.get("version") or "")
    if dossier_type == "market" or version.startswith("market"):
        return "market", "v1"
    if dossier_type == "competitive_intelligence" or "competitive" in version:
        # v1 projection; IntentRevision schema_key uses competitive-intelligence
        return "competitive-intelligence", "v1" if "v2" not in version else "v2"
    if dossier_type == "tender_or_grant":
        return "procurement", "v1"
    return "custom", "v1"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", default=True)
    parser.add_argument("--apply", action="store_true", help="Write IntentRevision rows")
    parser.add_argument(
        "--json-out",
        default="",
        help="Optional path to write the count report JSON",
    )
    args = parser.parse_args(argv)
    apply = bool(args.apply)
    dry_run = not apply

    from opn_oracle.app import create_app
    from opn_oracle.extensions import db
    from opn_oracle.oracle.intent import DossierIntentRevision
    from opn_oracle.oracle.models import StrategicDossier
    from sqlalchemy import func, select, text

    app = create_app()
    report: dict[str, Any] = {
        "mode": "apply" if apply else "dry-run",
        "measured_at": datetime.now(UTC).isoformat(),
        "pre": {},
        "would_create": 0,
        "created": 0,
        "skipped_empty_profile": 0,
        "skipped_has_current": 0,
        "by_type": {},
    }

    with app.app_context():
        total_dossiers = db.session.scalar(select(func.count()).select_from(StrategicDossier)) or 0
        with_profile = db.session.scalar(
            text(
                """
                SELECT count(*) FROM strategic_dossiers
                WHERE profile_config IS NOT NULL
                  AND profile_config::text NOT IN ('{}', 'null', '[]')
                """
            )
        )
        with_current = db.session.scalar(
            text(
                "SELECT count(*) FROM strategic_dossiers WHERE current_intent_revision_id IS NOT NULL"
            )
        )
        intent_rows = db.session.scalar(select(func.count()).select_from(DossierIntentRevision)) or 0
        report["pre"] = {
            "strategic_dossiers": int(total_dossiers),
            "with_nonempty_profile_config": int(with_profile or 0),
            "with_current_intent_revision": int(with_current or 0),
            "dossier_intent_revisions": int(intent_rows),
        }

        candidates = db.session.scalars(
            select(StrategicDossier).where(
                StrategicDossier.profile_config.is_not(None),
                StrategicDossier.current_intent_revision_id.is_(None),
            )
        ).all()

        for dossier in candidates:
            profile = dict(dossier.profile_config or {})
            if not profile:
                report["skipped_empty_profile"] += 1
                continue
            dtype = str(dossier.dossier_type or "custom")
            report["by_type"][dtype] = report["by_type"].get(dtype, 0) + 1
            schema_key, schema_version = _schema_for_dossier_type(dtype, profile)
            request_text = (
                str(dossier.description or "").strip()
                or str(dossier.strategic_goal or "").strip()
                or f"Backfill desde profile_config ({schema_key})"
            )[:20000]
            content_hash = _canonical_hash(schema_key, schema_version, request_text, profile)
            report["would_create"] += 1
            if dry_run:
                continue
            revision = DossierIntentRevision(
                id=uuid.uuid4(),
                tenant_id=dossier.tenant_id,
                dossier_id=dossier.id,
                version=1,
                schema_key=schema_key,
                schema_version=schema_version,
                request_text=request_text,
                structured_spec=profile,
                status="accepted",
                source_refs=[],
                content_hash=content_hash,
                row_version=1,
                proposed_by_user_id=dossier.owner_user_id,
                accepted_by_user_id=dossier.owner_user_id,
                accepted_at=datetime.now(UTC),
            )
            db.session.add(revision)
            db.session.flush()
            dossier.current_intent_revision_id = revision.id
            report["created"] += 1

        if apply:
            db.session.commit()
        else:
            db.session.rollback()

        post_intent = db.session.scalar(select(func.count()).select_from(DossierIntentRevision)) or 0
        post_current = db.session.scalar(
            text(
                "SELECT count(*) FROM strategic_dossiers WHERE current_intent_revision_id IS NOT NULL"
            )
        )
        report["post"] = {
            "dossier_intent_revisions": int(post_intent),
            "with_current_intent_revision": int(post_current or 0),
        }

    print(json.dumps(report, indent=2, ensure_ascii=False))
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
