"""Unit tests for company tax-id (CIF) identity helpers — SV2-NIF."""

from __future__ import annotations

import uuid
from unittest.mock import MagicMock

import pytest

from opn_oracle.oracle.investigations import (
    ResearchEntity,
    _merge_entity_identifiers,
    _upsert_entity,
    extract_company_tax_id,
    normalize_spanish_company_tax_id,
)


@pytest.mark.unit
def test_normalize_spanish_company_tax_id_accepts_cif_rejects_person_nif() -> None:
    assert normalize_spanish_company_tax_id("b-47.509.591") == "B47509591"
    assert normalize_spanish_company_tax_id("A88264155") == "A88264155"
    assert normalize_spanish_company_tax_id("12345678Z") is None
    assert normalize_spanish_company_tax_id("") is None
    assert normalize_spanish_company_tax_id(None) is None


@pytest.mark.unit
def test_extract_company_tax_id_from_graph_node_and_identifiers() -> None:
    assert extract_company_tax_id({"tax_id": "B47509591"}) == "B47509591"
    assert extract_company_tax_id({"identifiers": {"cif": "B88844014"}}) == "B88844014"
    assert extract_company_tax_id({"profile": {"tax_id": "A88264155"}}) == "A88264155"
    assert extract_company_tax_id({"nif": "12345678Z"}) is None
    assert extract_company_tax_id({"label": "ACME SL", "type": "company"}) is None


@pytest.mark.unit
def test_upsert_entity_dedupes_companies_by_tax_id_not_by_name_similarity() -> None:
    session = MagicMock()
    run = MagicMock()
    run.id = uuid.uuid4()
    run.tenant_id = uuid.uuid4()

    existing = ResearchEntity(
        tenant_id=run.tenant_id,
        run_id=run.id,
        exact_name="Servicios Logísticos del Duero SL",
        normalized_name="SERVICIOS LOGISTICOS DEL DUERO",
        entity_kind="company",
        identifiers={"tax_id": "B47509591", "tax_id_scheme": "ES_CIF"},
        depth=1,
        discovery_path=[],
        resolution_status="candidate",
        identity_confidence=90,
    )
    existing.id = uuid.uuid4()

    # First scalars() call: scan companies for tax_id match.
    # Second path shouldn't need name lookup if tax_id hits.
    session.scalars.return_value = [existing]
    session.scalar.return_value = None

    entity = _upsert_entity(
        session,
        run=run,
        name="SERVICIOS LOGISTICOS DEL DUERO SOCIEDAD LIMITADA",
        kind="company",
        depth=2,
        discovery_path=[{"via": "test"}],
        identifiers={"tax_id": "B47509591"},
    )
    assert entity is existing
    assert entity.identifiers["tax_id"] == "B47509591"
    session.add.assert_not_called()


@pytest.mark.unit
def test_merge_entity_identifiers_never_stores_person_nif_as_company_tax_id() -> None:
    entity = ResearchEntity(
        tenant_id=uuid.uuid4(),
        run_id=uuid.uuid4(),
        exact_name="ACME SL",
        normalized_name="ACME",
        entity_kind="company",
        identifiers={},
        depth=1,
        discovery_path=[],
        resolution_status="candidate",
        identity_confidence=0,
    )
    _merge_entity_identifiers(entity, {"nif": "12345678Z", "tax_id": "not-a-cif"})
    assert "tax_id" not in (entity.identifiers or {})
    _merge_entity_identifiers(entity, {"tax_id": "B40517823"})
    assert entity.identifiers["tax_id"] == "B40517823"
    assert entity.identity_confidence == 90
