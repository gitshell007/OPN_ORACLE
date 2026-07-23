from __future__ import annotations

import inspect
import json
import re
import types
import uuid
from dataclasses import fields
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Literal, get_args, get_origin

import httpx
import pytest
from pydantic import BaseModel

from opn_oracle.ai.schemas import NextBestAction, SourceIndexEntry, StrictModel, WeeklyChangeOutput
from opn_oracle.config import FILE_BACKED_SETTINGS, Settings
from opn_oracle.integrations.entity_intel import EntityIntelClient, EntityIntelProviderError
from opn_oracle.integrations.procurement import ProcurementClient, ProcurementProviderError
from opn_oracle.integrations.signal_avanza import HttpSignalAvanzaAdapter, SignalTemporaryError
from opn_oracle.notifications.email import EmailTemporaryError, GraphEmailSender
from opn_oracle.oracle import entity_dossier_report

PROJECT_ROOT = Path(__file__).resolve().parents[3]
COMPOSE_PROD = PROJECT_ROOT / "compose.prod.yml"
ENV_EXAMPLE = PROJECT_ROOT / "infra" / "production" / "oracle.env.example"

HOT_OPERATION_LEVERS = frozenset(
    {
        "ENTITY_INTEL_MAX_REGISTRY_ACTS",
        "ENTITY_INTEL_MAX_AWARD_SOURCES",
        "ENTITY_INTEL_MAX_EVIDENCE_SOURCES",
        "DOCUMENT_ALLOW_OFFICIAL_UNSCANNED",
    }
)

KNOWN_ENTITY_EVIDENCE_SOURCE_KINDS = frozenset(
    {
        "registry_act",
        "web_mention",
        "patent",
        "disclosure",
        "procurement_award",
    }
)


def _app_environment_keys() -> set[str]:
    text = COMPOSE_PROD.read_text(encoding="utf-8")
    match = re.search(
        r"^x-app-environment: &app-environment\n(?P<body>.*?)(?=^\S)", text, re.S | re.M
    )
    assert match is not None, "compose.prod.yml no contiene x-app-environment"
    return {
        item.group("key")
        for item in re.finditer(r"^  (?P<key>[A-Z][A-Z0-9_]+):", match.group("body"), re.M)
    }


def _env_example_keys() -> set[str]:
    keys: set[str] = set()
    for line in ENV_EXAMPLE.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or "=" not in stripped:
            continue
        keys.add(stripped.split("=", maxsplit=1)[0])
    return keys


@pytest.mark.unit
def test_compose_application_environment_has_no_orphan_settings() -> None:
    settings_keys = {field.name.upper() for field in fields(Settings)}
    app_env_keys = _app_environment_keys()

    orphan_keys = sorted(
        key
        for key in app_env_keys
        if (key.removesuffix("_FILE") if key.endswith("_FILE") else key) not in settings_keys
    )
    file_backed_typos = sorted(
        key
        for key in app_env_keys
        if key.endswith("_FILE") and key.removesuffix("_FILE") not in FILE_BACKED_SETTINGS
    )

    assert orphan_keys == []
    assert file_backed_typos == []


@pytest.mark.unit
def test_hot_operation_levers_are_wired_in_compose_and_operator_env_example() -> None:
    app_env_keys = _app_environment_keys()
    env_example_keys = _env_example_keys()

    assert sorted(HOT_OPERATION_LEVERS - app_env_keys) == []
    assert sorted(HOT_OPERATION_LEVERS - env_example_keys) == []


@pytest.mark.unit
def test_json_body_routes_registered_by_apiflask_receive_json_data(app: Any) -> None:
    offenders: list[str] = []
    for rule in app.url_map.iter_rules():
        view = app.view_functions[rule.endpoint]
        spec = getattr(view, "_spec", {})
        if "body" not in spec:
            continue
        if "json_data" not in inspect.signature(view).parameters:
            offenders.append(f"{rule.endpoint} {rule.rule}")

    assert offenders == []


@pytest.mark.unit
def test_http_boundaries_classify_remote_protocol_errors_without_leaking_transport() -> None:
    def fail_transport(_request: httpx.Request) -> httpx.Response:
        raise httpx.RemoteProtocolError("server disconnected without response")

    transport = httpx.MockTransport(fail_transport)
    entity_client = EntityIntelClient(
        base_url="https://signal.example",
        api_key="secret",
        allowed_hosts=frozenset({"signal.example"}),
        transport=transport,
    )
    with pytest.raises(EntityIntelProviderError) as entity_error:
        try:
            entity_client.registry(name="ITURRI SA", kind="company", limit=1, offset=0)
        finally:
            entity_client.close()
    assert entity_error.value.status_code == 503
    assert entity_error.value.retryable is True
    assert "server disconnected" not in str(entity_error.value).lower()

    procurement_client = ProcurementClient(
        base_url="https://signal.example",
        api_key="secret",
        allowed_hosts=frozenset({"signal.example"}),
        transport=httpx.MockTransport(fail_transport),
    )
    with pytest.raises(ProcurementProviderError) as procurement_error:
        try:
            procurement_client.stats()
        finally:
            procurement_client.close()
    assert procurement_error.value.status_code == 503
    assert procurement_error.value.retryable is True
    assert "server disconnected" not in str(procurement_error.value).lower()

    adapter = HttpSignalAvanzaAdapter(
        base_url="https://signal.example",
        api_version="2026-07-01",
        token="secret",
        contract_confirmed=True,
        allowed_hosts=frozenset({"signal.example"}),
        transport=httpx.MockTransport(fail_transport),
    )
    with pytest.raises(SignalTemporaryError) as signal_error:
        try:
            adapter.health()
        finally:
            adapter.close()
    assert "server disconnected" not in str(signal_error.value).lower()

    sender = GraphEmailSender(
        tenant_id="11111111-1111-4111-8111-111111111111",
        client_id="22222222-2222-4222-8222-222222222222",
        client_secret="secret",
        sender_mailbox="oracle@example.test",
        transport=httpx.MockTransport(fail_transport),
    )
    with pytest.raises(EmailTemporaryError) as email_error:
        try:
            sender.send_security_alert(recipient="user@example.test", message="Aviso")
        finally:
            sender.close()
    assert "server disconnected" not in str(email_error.value).lower()


@pytest.mark.unit
def test_entity_evidence_source_kinds_are_all_counted_by_the_global_cap() -> None:
    sources: list[dict[str, Any]] = []
    for source_kind in KNOWN_ENTITY_EVIDENCE_SOURCE_KINDS:
        for index in range(12):
            sources.append({"id": f"{source_kind}-{index}", "source_kind": source_kind})

    capped = entity_dossier_report.balance_evidence_sources(sources, total_limit=45)

    assert len(capped) == 45
    assert {item["source_kind"] for item in capped} == KNOWN_ENTITY_EVIDENCE_SOURCE_KINDS
    assert capped == [item for item in sources if item in capped]

    extracted_source_kinds = {
        item["source_kind"]
        for item in entity_dossier_report.build_pending_entity_evidence_sources(
            entity_dossier={
                "entity": {"name": "ENTIDAD SA", "type": "company"},
                "registry": {
                    "items": [
                        {
                            "action": "nombramiento",
                            "date": "2026-07-01",
                            "source_url": "https://www.boe.es/borme/dias/2026/07/01/",
                        }
                    ]
                },
                "news": {
                    "items": [
                        {
                            "title": "ENTIDAD SA: mención externa",
                            "url": "https://example.test/news",
                        }
                    ]
                },
                "patents": {
                    "items": [
                        {
                            "pub_number": "EP1",
                            "title": "Patente",
                            "url": "https://example.test/patent",
                        }
                    ]
                },
                "disclosures": {
                    "items": [
                        {
                            "nreg": "1",
                            "type": "CNMV",
                            "link": "https://example.test/cnmv",
                        }
                    ]
                },
                "procurement": {
                    "award_sources": [
                        {
                            "folder_id": "EXP-1",
                            "buyer": "Organismo",
                            "award_date": "2026-07-03",
                            "source_url": "https://contrataciondelestado.es/exp/EXP-1",
                        }
                    ]
                },
            },
            corpus_hash="a" * 64,
        )
    }
    assert extracted_source_kinds == KNOWN_ENTITY_EVIDENCE_SOURCE_KINDS


def _strict_model_classes() -> list[type[StrictModel]]:
    pending: list[type[StrictModel]] = list(StrictModel.__subclasses__())
    seen: set[type[StrictModel]] = set()
    result: list[type[StrictModel]] = []
    while pending:
        model = pending.pop()
        if model in seen:
            continue
        seen.add(model)
        result.append(model)
        pending.extend(model.__subclasses__())
    return sorted(result, key=lambda item: item.__name__)


def _sample_value(annotation: Any, field_name: str) -> Any:
    origin = get_origin(annotation)
    args = get_args(annotation)
    if origin is Literal:
        return next(item for item in args if item is not None)
    if origin in {types.UnionType, getattr(types, "UnionType", object)} or (
        origin is not None and str(origin) == "typing.Union"
    ):
        return _sample_value(next(item for item in args if item is not type(None)), field_name)
    if origin is list:
        length = 2 if field_name == "evidence_ids" else 1
        return [_sample_value(args[0], field_name) for _ in range(length)]
    if origin is dict:
        return {"kind": _sample_value(args[1], field_name)}
    if inspect.isclass(annotation) and issubclass(annotation, BaseModel):
        return _sample_payload(annotation)
    if annotation is uuid.UUID:
        return uuid.uuid4()
    if annotation is datetime:
        return datetime(2026, 7, 19, 12, 0, tzinfo=UTC)
    if annotation is date:
        return date(2026, 7, 19)
    if annotation is str:
        return "sample-1" if field_name == "id" else "valor de prueba"
    if annotation is int:
        return 50
    if annotation is float:
        return 1.0
    if annotation is Decimal:
        return Decimal("1.00")
    if annotation is bool:
        return True
    if annotation is Any:
        return {"value": "test"}
    raise AssertionError(f"No sample for {annotation!r} in {field_name}")


def _sample_payload(model: type[BaseModel]) -> dict[str, Any]:
    return {
        name: _sample_value(field.annotation, name)
        for name, field in model.model_fields.items()
        if not name.startswith("_")
    }


@pytest.mark.unit
@pytest.mark.parametrize("model", _strict_model_classes(), ids=lambda model: model.__name__)
def test_strict_ai_models_roundtrip_after_json_storage(model: type[StrictModel]) -> None:
    instance = model.model_validate(_sample_payload(model))
    stored_payload = instance.model_dump(mode="json")

    restored = model.model_validate_json(json.dumps(stored_payload))

    assert restored == instance
    if model is SourceIndexEntry:
        assert isinstance(stored_payload["evidence_id"], str)
        assert isinstance(restored.evidence_id, uuid.UUID)
    if model is WeeklyChangeOutput:
        assert isinstance(stored_payload["period_start"], str)
        assert isinstance(restored.period_start, datetime)
    if model is NextBestAction:
        assert isinstance(stored_payload["due_date"], str)
        assert isinstance(restored.due_date, date)
