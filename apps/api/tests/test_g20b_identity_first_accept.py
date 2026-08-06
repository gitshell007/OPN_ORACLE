"""G-20-B corrective: identity-first helpers (pure unit, no DB)."""

from __future__ import annotations

from opn_oracle.ai.market_materialize import (
    _fill_missing_identifiers_only,
    _identifier_conflicts,
    _merge_actor_identifiers,
    _strong_ids_only,
    actor_identity_canonical_key,
)


def test_actor_identity_canonical_key_prefers_strong_id() -> None:
    assert actor_identity_canonical_key({"ror": "04dbzz632"}, "Institut Néel") == "ror:04dbzz632"
    assert actor_identity_canonical_key({"rnsr": "200717524X"}, "X") == "rnsr:200717524x"
    # Name fallback is stable and casefolded.
    key = actor_identity_canonical_key({}, "Institut Néel")
    assert "institut" in key
    assert ":" not in key or not key.startswith(("ror:", "rnsr:"))


def test_identifier_conflicts_detects_incompatible() -> None:
    c = _identifier_conflicts({"ror": "AAAA"}, {"ror": "BBBB", "rnsr": "1"})
    assert any(x["key"] == "ror" for x in c)
    assert _identifier_conflicts({"ror": "AAAA"}, {"ror": "AAAA", "rnsr": "1"}) == []


def test_strong_ids_only_filters() -> None:
    assert _strong_ids_only({"ror": "x", "evil": "y", "rnsr": ""}) == {"ror": "x"}
    assert _strong_ids_only(None) == {}


def test_fill_missing_never_overwrites_or_records_conflicts() -> None:
    base = {"ror": "AAAA"}
    out = _fill_missing_identifiers_only(base, {"ror": "BBBB", "rnsr": "1"})
    assert out["ror"] == "AAAA"
    assert out["rnsr"] == "1"
    assert "identifier_conflicts" not in out


def test_merge_still_records_conflicts_for_legacy_callers() -> None:
    merged = _merge_actor_identifiers({"rnsr": "200717524X"}, {"rnsr": "OTHER", "hal_structure": "1"})
    assert merged["rnsr"] == "200717524X"
    assert merged["hal_structure"] == "1"
    assert any(c["key"] == "rnsr" for c in merged.get("identifier_conflicts") or [])
