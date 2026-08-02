"""Oracle→Signal adapter for surveillance ingest (MDEV-07).

Deuda MDEV-05: el store in-process de Signal no es productivo. Este adapter:
- exige consumer + external_tenant + dossier + scope/provenance;
- por defecto está OFF / fail-closed;
- si se fuerza enable sin persistencia durable, devuelve degraded sin fingir E2E.

No usa Ask (MDEV-06) como prueba de vigilancia ni autoactiva augment.
"""

from __future__ import annotations

import os
from typing import Any

from opn_oracle.oracle.surveillance import (
    DossierSurveillanceAction,
    SurveillanceValidationError,
    build_oracle_to_signal_scope,
)


class SurveillanceSignalAdapterError(RuntimeError):
    def __init__(self, message: str, *, code: str, degraded: bool = True) -> None:
        super().__init__(message)
        self.code = code
        self.degraded = degraded


def surveillance_signal_enabled() -> bool:
    return os.getenv("MEMORY_SURVEILLANCE_SIGNAL_ENABLED", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def durable_memory_store_available() -> bool:
    """Productive durable store is not available under known MDEV-05 debt."""

    # Explicit opt-in for a future durable backend; default false.
    return os.getenv("MEMORY_DURABLE_STORE_READY", "0").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def publish_surveillance_scope(
    action: DossierSurveillanceAction,
    *,
    consumer_id: str,
    external_tenant_id: str,
    transport: Any | None = None,
) -> dict[str, Any]:
    """Publish monitor scope to Signal. Fail-closed when durable store is not ready."""

    if not consumer_id or not external_tenant_id:
        raise SurveillanceValidationError(
            "consumer_id y external_tenant_id son obligatorios.",
            errors={
                "consumer_id": ["Obligatorio."],
                "external_tenant_id": ["Obligatorio."],
            },
        )
    envelope = build_oracle_to_signal_scope(
        action,
        consumer_id=consumer_id,
        external_tenant_id=external_tenant_id,
    )
    # Guard: no signal may enter memory without dossier+tenant+consumer links.
    for key in ("consumer_id", "external_tenant_id", "dossier_id", "tenant_id"):
        if not envelope.get(key):
            raise SurveillanceSignalAdapterError(
                f"Contrato incompleto: falta {key}.",
                code="contract_incomplete",
                degraded=False,
            )
    if not envelope.get("scope") or not envelope.get("provenance"):
        raise SurveillanceSignalAdapterError(
            "Contrato incompleto: scope/provenance requeridos.",
            code="contract_incomplete",
            degraded=False,
        )

    if not surveillance_signal_enabled():
        return {
            "status": "disabled",
            "error_code": "surveillance_signal_disabled",
            "degraded": True,
            "envelope": envelope,
            "published": False,
        }

    if not durable_memory_store_available():
        # Honest fail-closed: do not pretend in-process store is productive.
        return {
            "status": "degraded",
            "error_code": "DUR-MDEV05-001",
            "degraded": True,
            "detail": (
                "Persistencia Signal no durable (store in-process). "
                "No se publica vigilancia como memoria productiva."
            ),
            "envelope": envelope,
            "published": False,
        }

    if transport is None:
        raise SurveillanceSignalAdapterError(
            "Transport Signal no configurado.",
            code="transport_missing",
        )
    result = transport.publish_surveillance_scope(envelope)
    return {
        "status": "accepted",
        "degraded": False,
        "envelope": envelope,
        "published": True,
        "result": result,
    }
