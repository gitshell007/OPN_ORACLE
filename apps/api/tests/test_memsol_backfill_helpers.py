"""Pure helpers of the IntentRevision backfill script."""

from __future__ import annotations

import importlib.util
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "memsol_backfill_intent_revisions.py"
_spec = importlib.util.spec_from_file_location("memsol_backfill_intent_revisions", _SCRIPT)
assert _spec and _spec.loader
_mod = importlib.util.module_from_spec(_spec)
# Load only top-level helpers: execute until main definition by loading full module
# (main imports app only when called).
_spec.loader.exec_module(_mod)


def test_canonical_hash_stable() -> None:
    a = _mod._canonical_hash("market", "v1", "texto", {"own_offer": "x"})
    b = _mod._canonical_hash("market", "v1", "texto", {"own_offer": "x"})
    assert a == b
    assert len(a) == 64


def test_schema_for_dossier_type_mapping() -> None:
    assert _mod._schema_for_dossier_type("market", {}) == ("market", "v1")
    key, ver = _mod._schema_for_dossier_type(
        "competitive_intelligence",
        {"version": "competitive-intelligence.v1"},
    )
    assert key == "competitive-intelligence"
    assert ver == "v1"
    assert _mod._schema_for_dossier_type("custom", {})[0] == "custom"
