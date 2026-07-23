from __future__ import annotations

from opn_oracle.oracle.procurement_search_watch import (
    material_change_fields,
    material_tender_hash,
    material_tender_snapshot,
)


def test_material_tender_fingerprint_ignores_feed_timestamp_but_detects_analyst_changes() -> None:
    baseline = {
        "folder_id": "2026/0001",
        "title": "Suministro de equipos de protección",
        "summary_feed": "Equipamiento para emergencias.",
        "buyer": "Ayuntamiento de Zaragoza",
        "amount": "1200000.00",
        "deadline": "2026-08-01",
        "canonical_status": "open",
        "cpv": ["18100000"],
        "feed_updated_at": "2026-07-23T08:00:00Z",
    }
    refreshed_only = {**baseline, "feed_updated_at": "2026-07-24T08:00:00Z"}
    changed_deadline = {**refreshed_only, "deadline": "2026-08-08"}

    first = material_tender_snapshot(baseline)
    timestamp_only = material_tender_snapshot(refreshed_only)
    deadline_changed = material_tender_snapshot(changed_deadline)

    assert material_tender_hash(first) == material_tender_hash(timestamp_only)
    assert material_change_fields(first, timestamp_only) == []
    assert material_tender_hash(first) != material_tender_hash(deadline_changed)
    assert material_change_fields(first, deadline_changed) == ["deadline"]
