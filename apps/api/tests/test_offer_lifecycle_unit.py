"""Unit tests for G-10 opportunity offer lifecycle (validations + serialization)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from opn_oracle.oracle.offer_lifecycle import (
    DEFAULT_STATUS,
    OFFER_LIFECYCLE_STATUSES,
    OfferLifecycleError,
    _date,
    _lotes,
    _money,
    _percent,
    _status,
    apply_offer_lifecycle_payload,
    make_etag,
    parse_expected_version,
    serialize_offer_lifecycle,
    virtual_offer_lifecycle,
)


def _row(**overrides):
    base = {
        "id": uuid4(),
        "tenant_id": uuid4(),
        "dossier_id": uuid4(),
        "opportunity_id": uuid4(),
        "status": DEFAULT_STATUS,
        "importe_ofertado": None,
        "baja_porcentaje": None,
        "lotes": [],
        "garantia_provisional": None,
        "fecha_mesa": None,
        "motivo_exclusion": None,
        "version": 1,
        "last_edited_by_user_id": uuid4(),
        "created_at": date(2026, 8, 6),  # will be overridden with datetime in serialize
        "updated_at": date(2026, 8, 6),
    }
    base.update(overrides)
    # serialize expects datetime isoformat on created/updated
    from datetime import UTC, datetime

    if not hasattr(base["created_at"], "isoformat") or isinstance(base["created_at"], date):
        base["created_at"] = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
        base["updated_at"] = datetime(2026, 8, 6, 12, 0, tzinfo=UTC)
    return SimpleNamespace(**base)


@pytest.mark.unit
def test_statuses_and_labels_cover_contract() -> None:
    assert {
        "preparando",
        "presentada",
        "en_evaluacion",
        "adjudicada",
        "perdida",
        "excluida",
    } == OFFER_LIFECYCLE_STATUSES


@pytest.mark.unit
def test_money_rejects_negative_and_serializes_quantum() -> None:
    assert _money("1234.5", field="importe_ofertado") == Decimal("1234.50")
    assert _money(None, field="importe_ofertado") is None
    with pytest.raises(OfferLifecycleError) as neg:
        _money("-1", field="importe_ofertado")
    assert "importe_ofertado" in neg.value.errors
    with pytest.raises(OfferLifecycleError):
        _money("nope", field="garantia_provisional")


@pytest.mark.unit
def test_percent_range_0_to_100() -> None:
    assert _percent("12.5", field="baja_porcentaje") == Decimal("12.50")
    assert _percent("0", field="baja_porcentaje") == Decimal("0.00")
    assert _percent("100", field="baja_porcentaje") == Decimal("100.00")
    with pytest.raises(OfferLifecycleError):
        _percent("-0.01", field="baja_porcentaje")
    with pytest.raises(OfferLifecycleError):
        _percent("100.01", field="baja_porcentaje")


@pytest.mark.unit
def test_date_iso_and_lotes_dedupe() -> None:
    assert _date("2026-09-15", field="fecha_mesa") == date(2026, 9, 15)
    assert _date(None, field="fecha_mesa") is None
    with pytest.raises(OfferLifecycleError):
        _date("15/09/2026", field="fecha_mesa")
    assert _lotes(["Lote 1", "lote 1", "Lote 2"]) == ["Lote 1", "Lote 2"]
    assert _lotes("Lote A, Lote B\nLote C") == ["Lote A", "Lote B", "Lote C"]


@pytest.mark.unit
def test_motivo_exclusion_required_only_when_excluida() -> None:
    row = _row(status="preparando")
    with pytest.raises(OfferLifecycleError) as missing:
        apply_offer_lifecycle_payload(row, {"status": "excluida"}, partial=True)
    assert "motivo_exclusion" in missing.value.errors

    ok = apply_offer_lifecycle_payload(
        row,
        {"status": "excluida", "motivo_exclusion": "No cumple solvencia económica."},
        partial=True,
    )
    assert ok["status"] == "excluida"
    assert ok["motivo_exclusion"] == "No cumple solvencia económica."

    with pytest.raises(OfferLifecycleError) as leftover:
        apply_offer_lifecycle_payload(
            _row(status="presentada"),
            {"status": "presentada", "motivo_exclusion": "no debería"},
            partial=True,
        )
    assert "motivo_exclusion" in leftover.value.errors

    cleared = apply_offer_lifecycle_payload(
        _row(status="excluida", motivo_exclusion="antes"),
        {"status": "perdida"},
        partial=True,
    )
    assert cleared["status"] == "perdida"
    assert cleared["motivo_exclusion"] is None


@pytest.mark.unit
def test_apply_partial_preserves_unmentioned_fields() -> None:
    row = _row(
        status="presentada",
        importe_ofertado=Decimal("1000.00"),
        baja_porcentaje=Decimal("5.00"),
        lotes=["L1"],
        garantia_provisional=Decimal("50.00"),
        fecha_mesa=date(2026, 10, 1),
    )
    fields = apply_offer_lifecycle_payload(row, {"baja_porcentaje": "7.5"}, partial=True)
    assert fields["status"] == "presentada"
    assert fields["importe_ofertado"] == Decimal("1000.00")
    assert fields["baja_porcentaje"] == Decimal("7.50")
    assert fields["lotes"] == ["L1"]
    assert fields["fecha_mesa"] == date(2026, 10, 1)


@pytest.mark.unit
def test_serialize_decimals_and_dates_as_strings() -> None:
    row = _row(
        status="en_evaluacion",
        importe_ofertado=Decimal("250000.50"),
        baja_porcentaje=Decimal("3.25"),
        lotes=["Lote 1", "Lote 3"],
        garantia_provisional=Decimal("5000"),
        fecha_mesa=date(2026, 11, 2),
        version=4,
    )
    data = serialize_offer_lifecycle(row)
    assert data["status"] == "en_evaluacion"
    assert data["status_label"] == "En evaluación"
    assert data["importe_ofertado"] == "250000.5"
    assert data["baja_porcentaje"] == "3.25"
    assert data["garantia_provisional"] == "5000"
    assert data["fecha_mesa"] == "2026-11-02"
    assert data["lotes"] == ["Lote 1", "Lote 3"]
    assert data["version"] == 4
    assert data["etag"] == make_etag(4)
    assert "CRM" in data["crm_status_note"] or "crm" in data["crm_status_note"].lower()
    assert data["motivo_exclusion"] is None


@pytest.mark.unit
def test_serialize_clears_motivo_when_not_excluida() -> None:
    row = _row(status="adjudicada", motivo_exclusion="residual")
    data = serialize_offer_lifecycle(row)
    assert data["motivo_exclusion"] is None


@pytest.mark.unit
def test_parse_expected_version_body_and_if_match() -> None:
    assert parse_expected_version(body_version=3) == 3
    assert parse_expected_version(if_match='W/"ool-v7"') == 7
    assert parse_expected_version(if_match='W/"5"') == 5
    assert parse_expected_version() is None
    with pytest.raises(OfferLifecycleError):
        parse_expected_version(body_version="x")


@pytest.mark.unit
def test_invalid_status_rejected() -> None:
    with pytest.raises(OfferLifecycleError):
        _status("qualified")  # CRM status must not be accepted as offer status
    with pytest.raises(OfferLifecycleError):
        _status("won")


@pytest.mark.unit
def test_virtual_contract_is_explicit_and_not_persisted_shape() -> None:
    tenant_id = uuid4()
    dossier_id = uuid4()
    opportunity_id = uuid4()
    virtual = virtual_offer_lifecycle(
        tenant_id=tenant_id,
        dossier_id=dossier_id,
        opportunity_id=opportunity_id,
    )
    assert virtual["materialized"] is False
    assert virtual["version"] == 0
    assert virtual["etag"] == make_etag(0)
    assert virtual["id"] is None
    assert virtual["last_edited_by_user_id"] is None
    assert virtual["created_at"] is None
    assert virtual["updated_at"] is None
    assert virtual["status"] == DEFAULT_STATUS
    assert virtual["importe_ofertado"] is None
    assert virtual["lotes"] == []
    assert virtual["tenant_id"] == str(tenant_id)
    assert virtual["dossier_id"] == str(dossier_id)
    assert virtual["opportunity_id"] == str(opportunity_id)


@pytest.mark.unit
def test_serialize_marks_materialized_true() -> None:
    data = serialize_offer_lifecycle(_row(version=2))
    assert data["materialized"] is True
    assert data["version"] == 2
    assert data["id"] is not None


@pytest.mark.unit
def test_parse_expected_version_accepts_zero_for_first_write() -> None:
    assert parse_expected_version(body_version=0) == 0
    assert parse_expected_version(if_match='W/"ool-v0"') == 0


@pytest.mark.unit
def test_first_write_payload_applies_against_virtual_defaults() -> None:
    from types import SimpleNamespace

    virtual_row = SimpleNamespace(
        status=DEFAULT_STATUS,
        importe_ofertado=None,
        baja_porcentaje=None,
        lotes=[],
        garantia_provisional=None,
        fecha_mesa=None,
        motivo_exclusion=None,
    )
    fields = apply_offer_lifecycle_payload(
        virtual_row,
        {"status": "presentada", "importe_ofertado": "10"},
        partial=True,
    )
    assert fields["status"] == "presentada"
    assert fields["importe_ofertado"] == Decimal("10.00")
    assert fields["lotes"] == []
