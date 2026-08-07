"""G-16-B / G-17 · unit gates: normalize S.L., tax-first candidates, merge tax rules."""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from opn_oracle.oracle.investigations import (
    actor_alias_candidates,
    normalize_identity_name,
)
from opn_oracle.oracle.service import (
    DomainValidationError,
    TaxIdFiscalReviewRequired,
    _assert_fiscal_merge_safe,
    _merge_identifiers_governed,
    merge_actors,
)


@pytest.mark.unit
def test_normalize_identity_name_equates_sl_and_punctuated_sl() -> None:
    assert normalize_identity_name("CAPGEMINI ESPAÑA SL", drop_legal_suffix=True) == (
        normalize_identity_name("Capgemini España S.L.", drop_legal_suffix=True)
    )
    assert normalize_identity_name("Capgemini España S.L.", drop_legal_suffix=True) == (
        "CAPGEMINI ESPANA"
    )
    assert normalize_identity_name("ACME S.A.", drop_legal_suffix=True) == "ACME"
    assert normalize_identity_name("ACME SA", drop_legal_suffix=True) == "ACME"
    assert normalize_identity_name("NTT DATA Spain S.L.U.", drop_legal_suffix=True) == (
        "NTT DATA SPAIN"
    )
    assert normalize_identity_name("NTT DATA Spain SLU", drop_legal_suffix=True) == (
        "NTT DATA SPAIN"
    )


@pytest.mark.unit
def test_merge_identifiers_preserves_target_lei_duns() -> None:
    target = SimpleNamespace(
        tax_id="B08377715",
        tax_id_scheme="ES_CIF",
        identifiers={
            "lei": "TARGETLEI",
            "duns": "111",
            "website": "t.example",
            "tax_id": "B08377715",
        },
    )
    source = SimpleNamespace(
        tax_id=None,
        tax_id_scheme=None,
        identifiers={"lei": "SOURCELEI", "duns": "999", "website": "s.example", "extra": 1},
    )
    merged = _merge_identifiers_governed(target, source)  # type: ignore[arg-type]
    assert merged["lei"] == "TARGETLEI"
    assert merged["duns"] == "111"
    assert merged["website"] == "t.example"
    assert merged["extra"] == 1
    assert merged["tax_id"] == "B08377715"


@pytest.mark.unit
def test_merge_actors_requires_confirm_and_versions() -> None:
    session = MagicMock()
    tid = uuid.uuid4()
    sid = uuid.uuid4()
    with pytest.raises(DomainValidationError, match="confirmación"):
        merge_actors(
            session,
            tid,
            sid,
            actor_id=uuid.uuid4(),
            reason="ok reason",
            expected_target_version=1,
            expected_source_version=1,
            confirm=False,
        )
    with pytest.raises(DomainValidationError, match="expected_target_version"):
        merge_actors(
            session,
            tid,
            sid,
            actor_id=uuid.uuid4(),
            reason="ok reason",
            confirm=True,
        )


@pytest.mark.unit
def test_actor_alias_candidates_tax_first_and_meta(monkeypatch: pytest.MonkeyPatch) -> None:
    tenant = uuid.uuid4()
    cap_a = SimpleNamespace(
        id=uuid.UUID(int=1),
        tenant_id=tenant,
        actor_type="organization",
        canonical_name="CAPGEMINI ESPAÑA SL",
        aliases=[],
        identifiers={"tax_id": "B08377715", "tax_id_source": {"kind": "award_hydration"}},
        tax_id="B08377715",
        tax_id_scheme="ES_CIF",
        tax_id_country="ES",
        version=1,
        provenance={},
        created_at=None,
    )
    cap_b = SimpleNamespace(
        id=uuid.UUID(int=2),
        tenant_id=tenant,
        actor_type="organization",
        canonical_name="Capgemini España S.L.",
        aliases=[],
        identifiers={"tax_id": "B08377715"},
        tax_id=None,
        tax_id_scheme=None,
        tax_id_country=None,
        version=1,
        provenance={},
        created_at=None,
    )
    other = SimpleNamespace(
        id=uuid.UUID(int=3),
        tenant_id=tenant,
        actor_type="organization",
        canonical_name="ITURRI SA",
        aliases=[],
        identifiers={},
        tax_id=None,
        tax_id_scheme=None,
        tax_id_country=None,
        version=1,
        provenance={},
        created_at=None,
    )
    twin_name = SimpleNamespace(
        id=uuid.UUID(int=4),
        tenant_id=tenant,
        actor_type="organization",
        canonical_name="Iturri S.L.",
        aliases=[],
        identifiers={},
        tax_id=None,
        tax_id_scheme=None,
        tax_id_country=None,
        version=1,
        provenance={},
        created_at=None,
    )
    person = SimpleNamespace(
        id=uuid.UUID(int=5),
        tenant_id=tenant,
        actor_type="person",
        canonical_name="CAPGEMINI ESPAÑA SL",
        aliases=[],
        identifiers={},
        tax_id=None,
        tax_id_scheme=None,
        tax_id_country=None,
        version=1,
        provenance={},
        created_at=None,
    )

    session = MagicMock()
    # actor_alias_candidates only loads organizations; person never appears.
    session.scalars.return_value = [cap_a, cap_b, other, twin_name]

    monkeypatch.setattr(
        "opn_oracle.oracle.investigations.require_tenant_id",
        lambda: tenant,
    )

    result = actor_alias_candidates(session)
    assert "items" in result and "meta" in result
    items = result["items"]
    meta = result["meta"]
    assert meta["organizations_evaluated"] == 4
    # Durable = column only; declared-only is separate (cap_b has JSON only).
    assert meta["organizations_with_tax_id"] == 1
    assert meta["organizations_with_declared_only_tax_id"] == 1
    assert meta["counts"]["tax_id"] == 1
    assert meta["counts"]["normalized_name"] >= 1
    tax_item = next(item for item in items if item["match_reason"] == "tax_id")
    assert tax_item["tax_id"] == "B08377715"
    assert tax_item["priority"] == 100
    assert tax_item["confidence"] == "high"
    assert {actor["name"] for actor in tax_item["actors"]} == {
        "CAPGEMINI ESPAÑA SL",
        "Capgemini España S.L.",
    }
    by_name = {actor["name"]: actor for actor in tax_item["actors"]}
    assert by_name["CAPGEMINI ESPAÑA SL"]["has_durable_tax_id_column"] is True
    assert by_name["CAPGEMINI ESPAÑA SL"]["durable_tax_id"] == "B08377715"
    assert by_name["Capgemini España S.L."]["has_durable_tax_id_column"] is False
    assert by_name["Capgemini España S.L."]["declared_tax_id"] == "B08377715"
    assert tax_item["suggested_target_id"] == str(cap_a.id)
    assert items[0]["match_reason"] == "tax_id"  # ordered first
    assert "limpio" not in (meta.get("empty_state_message") or "").lower()
    # person not in session org list → never mixed
    del person


@pytest.mark.unit
def test_declared_only_pair_is_review_not_high_confidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    tenant = uuid.uuid4()
    a = SimpleNamespace(
        id=uuid.UUID(int=10),
        tenant_id=tenant,
        actor_type="organization",
        canonical_name="Declared A SA",
        aliases=[],
        identifiers={"tax_id": "B08377715", "tax_id_declared": "B08377715"},
        tax_id=None,
        tax_id_scheme=None,
        tax_id_country=None,
        version=1,
        provenance={},
        created_at=None,
    )
    b = SimpleNamespace(
        id=uuid.UUID(int=11),
        tenant_id=tenant,
        actor_type="organization",
        canonical_name="Declared B SL",
        aliases=[],
        identifiers={"tax_id": "B08377715", "lei": "L1", "duns": "D1"},
        tax_id=None,
        tax_id_scheme=None,
        tax_id_country=None,
        version=1,
        provenance={},
        created_at=None,
    )
    session = MagicMock()
    session.scalars.return_value = [a, b]
    monkeypatch.setattr(
        "opn_oracle.oracle.investigations.require_tenant_id",
        lambda: tenant,
    )
    result = actor_alias_candidates(session)
    assert result["meta"]["organizations_with_tax_id"] == 0
    assert result["meta"]["organizations_with_declared_only_tax_id"] == 2
    assert result["meta"]["counts"]["tax_id"] == 0
    review = next(
        item for item in result["items"] if item["match_reason"] == "tax_id_declared_review"
    )
    assert review["status"] == "blocked"
    assert review["confidence"] == "low"
    assert review["suggested_target_id"] is None


@pytest.mark.unit
def test_merge_identifiers_never_drops_declared_nif_when_no_column() -> None:
    """B2 reproduction: both columns None + JSON tax_id must not vanish fiscal keys."""

    target = SimpleNamespace(
        tax_id=None,
        tax_id_scheme=None,
        identifiers={
            "tax_id": "B08377715",
            "tax_id_declared": "B08377715",
            "lei": "L1",
        },
    )
    source = SimpleNamespace(
        tax_id=None,
        tax_id_scheme=None,
        identifiers={
            "tax_id": "B08377715",
            "tax_id_declared": "B08377715",
            "duns": "D2",
        },
    )
    merged = _merge_identifiers_governed(target, source)  # type: ignore[arg-type]
    assert merged["tax_id"] == "B08377715"
    assert merged["tax_id_declared"] == "B08377715"
    assert merged["lei"] == "L1"
    assert merged["duns"] == "D2"


@pytest.mark.unit
def test_assert_fiscal_merge_safe_blocks_declared_only() -> None:
    target = SimpleNamespace(
        tax_id=None,
        identifiers={"tax_id": "B08377715", "tax_id_declared": "B08377715", "lei": "L1"},
    )
    source = SimpleNamespace(
        tax_id=None,
        identifiers={"tax_id": "B08377715", "tax_id_declared": "B08377715", "duns": "D2"},
    )
    with pytest.raises(TaxIdFiscalReviewRequired, match="solo declarado"):
        _assert_fiscal_merge_safe(target, source)  # type: ignore[arg-type]

    # Distinct declarations → strict block
    source.identifiers = {"tax_id": "A58818501"}
    with pytest.raises(TaxIdFiscalReviewRequired, match="distintas"):
        _assert_fiscal_merge_safe(target, source)  # type: ignore[arg-type]

    # Holder + equal declaration allowed
    target.tax_id = "B08377715"
    target.identifiers = {"tax_id": "B08377715", "tax_id_declared": "B08377715"}
    source.tax_id = None
    source.identifiers = {"tax_id": "B08377715", "tax_id_declared": "B08377715"}
    _assert_fiscal_merge_safe(target, source)  # type: ignore[arg-type]

    # Holder + different declaration blocked
    source.identifiers = {"tax_id": "A58818501"}
    with pytest.raises(TaxIdFiscalReviewRequired, match="declara"):
        _assert_fiscal_merge_safe(target, source)  # type: ignore[arg-type]
