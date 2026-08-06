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
    assert meta["organizations_with_tax_id"] == 2  # durable via column or identifiers
    assert meta["counts"]["tax_id"] == 1
    assert meta["counts"]["normalized_name"] >= 1
    tax_item = next(item for item in items if item["match_reason"] == "tax_id")
    assert tax_item["tax_id"] == "B08377715"
    assert tax_item["priority"] == 100
    assert {actor["name"] for actor in tax_item["actors"]} == {
        "CAPGEMINI ESPAÑA SL",
        "Capgemini España S.L.",
    }
    assert tax_item["suggested_target_id"] == str(cap_a.id)
    assert items[0]["match_reason"] == "tax_id"  # ordered first
    assert "limpio" not in (meta.get("empty_state_message") or "").lower()
    # person not in session org list → never mixed
    del person
