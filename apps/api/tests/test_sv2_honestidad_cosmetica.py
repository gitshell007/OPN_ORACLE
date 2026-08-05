"""SV2-HONESTIDAD-COSMETICA · contrato público limpio (citas + memoria).

- Avisos de cita en español de producto (sin vector de tokens ni path JSON).
- Respuestas públicas de memoria sin deferred_blockers / actions_reliable / *-MDEV*.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, datetime
from types import SimpleNamespace

from opn_oracle.integrations.citation_support import (
    enforce_citation_support,
    format_support_rejection_summary,
    issue_to_public,
)
from opn_oracle.integrations.memory_context import capability_payload
from opn_oracle.integrations.memory_profile import profile_to_public
from opn_oracle.integrations.memory_routes import _effective_defaults

_MDEV_RE = re.compile(r"(RACE|DB|SEC|MIG)-MDEV")
_FORBIDDEN_KEYS = frozenset({"deferred_blockers", "actions_reliable", "missing_anchors"})


def _assert_public_clean(payload: object, *, path: str = "$") -> None:
    if isinstance(payload, dict):
        for key, value in payload.items():
            assert key not in _FORBIDDEN_KEYS, f"{path}.{key} no debe ser público"
            assert not _MDEV_RE.search(str(key)), f"clave MDEV en {path}.{key}"
            if isinstance(value, str):
                assert not _MDEV_RE.search(value), f"código MDEV en {path}.{key}"
                assert "faltan en el fragmento citado [" not in value
            _assert_public_clean(value, path=f"{path}.{key}")
    elif isinstance(payload, list):
        for i, item in enumerate(payload):
            _assert_public_clean(item, path=f"{path}[{i}]")


def test_capability_public_surfaces_healthy_and_unhealthy() -> None:
    healthy = capability_payload(host_mode="http", connection_healthy=True)
    assert healthy["publisher_reliable"] is True
    assert healthy["publisher_status"] == "ok"
    assert "message" in healthy
    _assert_public_clean(healthy)

    unhealthy = capability_payload(host_mode="disabled", connection_healthy=False)
    assert unhealthy["publisher_reliable"] is False
    assert unhealthy["publisher_status"] == "unavailable"
    _assert_public_clean(unhealthy)


def test_profile_and_defaults_public_without_internal_accounting() -> None:
    now = datetime.now(UTC)
    row = SimpleNamespace(
        id=uuid.uuid4(),
        tenant_id=uuid.uuid4(),
        dossier_id=uuid.uuid4(),
        connection_id=None,
        mode="augment",
        version=3,
        etag="etag-3",
        profile_config={
            "mode": "augment",
            "sources": ["document"],
            "kinds": ["fact"],
            "classifications_allowed": ["public"],
            "token_budget": 4000,
            "limit": 20,
            "status": "active",
            "provenance": "tenant_default",
        },
        last_test_at=now,
        last_test_status="ok",
        last_error=None,
        last_coverage={"used": 1},
        updated_at=now,
    )
    pub = profile_to_public(row)
    assert pub["publisher_reliable"] is True
    _assert_public_clean(pub)

    defaults = _effective_defaults(
        tenant_id=uuid.uuid4(), dossier_id=uuid.uuid4(), connection_id=None
    )
    assert defaults["publisher_reliable"] is True
    assert defaults["persisted"] is False
    _assert_public_clean(defaults)


def test_citation_public_payload_shape_no_raw_internals() -> None:
    statement = "La razón social del contratista no figura"
    result = enforce_citation_support(
        facts=[{"statement": statement, "evidence_ids": ["e1"]}],
        claims=[],
        evidence_text_by_id={
            "e1": "Licitación objeto suministro sin datos societarios."
        },
    )
    assert result.facts == []
    public_warnings = list(result.warnings)
    summary = format_support_rejection_summary(result)
    if summary:
        public_warnings.append(summary)
    public_support = {
        "withdrawn": result.withdrawn_count,
        "degraded": result.degraded_count,
        "kept": result.kept_count,
        "issues": [issue_to_public(i) for i in result.issues],
    }
    payload = {"warnings": public_warnings, "citation_support": public_support}
    _assert_public_clean(payload)
    blob = json.dumps(payload, ensure_ascii=False)
    assert "razón social" in blob
    assert "[razon" not in blob
    assert "Ejemplo:" not in blob
    assert "$.facts" not in blob
    # Sin duplicar el mismo warning: resumen ≠ primer detalle.
    if summary and result.warnings:
        assert summary != result.warnings[0]
