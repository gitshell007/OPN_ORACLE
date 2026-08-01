"""Oracle adapter for Signal opn_memory context retrieval (MEMSOL-05).

Oracle never opens SQL to Signal. Retrieval is HTTP (or mock/disabled).
Answers and custom reports may *read* context; they must not mutate intent
or promote memory facts from this boundary alone (ADR-0009 sections 8-11).
"""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any, Literal, Protocol, runtime_checkable

from flask import current_app

Purpose = Literal["question", "report", "summary", "wizard"]
MemoryContextMode = Literal["disabled", "mock", "http"]

COVERAGE_MANIFEST_VERSION = "coverage_manifest.v1"
MEMORY_RETRIEVAL_API_VERSION = "memory.retrieve.v1"


class MemoryContextError(RuntimeError):
    """Non-retryable adapter failure without secret-bearing detail."""


class MemoryContextDisabled(MemoryContextError):
    """MEMORY_CONTEXT_MODE=disabled; retrieval is intentionally off."""


def empty_coverage_manifest(
    *,
    requested: list[str] | None = None,
    token_budget: int = 0,
) -> dict[str, Any]:
    """Build a valid coverage_manifest.v1 object (ADR-0009 §9 / JSON schema)."""

    return {
        "version": COVERAGE_MANIFEST_VERSION,
        "requested": list(requested or []),
        "consulted": [],
        "failed": [],
        "excluded": [],
        "used": [],
        "truncated": False,
        "truncation_notes": [],
        "cutoff_at": None,
        "token_budget": int(token_budget),
        "token_used_estimate": 0,
    }


def empty_memory_retrieval_response(
    *,
    request_id: str | None = None,
    policy_version: str = "disabled",
    requested: list[str] | None = None,
) -> dict[str, Any]:
    """Shape compatible with memory_retrieval_response.schema.json."""

    return {
        "api_version": MEMORY_RETRIEVAL_API_VERSION,
        "request_id": request_id or str(uuid.uuid4()),
        "policy_version": policy_version,
        "items": [],
        "coverage_manifest": empty_coverage_manifest(requested=requested),
    }


@runtime_checkable
class MemoryContextAdapter(Protocol):
    """Anti-corruption boundary Oracle → opn_memory (Signal)."""

    def retrieve(
        self,
        scope_hint: Mapping[str, Any] | None,
        query: str,
        purpose: str,
        limit: int,
    ) -> dict[str, Any]:
        """Return MemoryRetrievalResponse dict (items + coverage_manifest)."""


class DisabledMemoryContextAdapter:
    """Fail closed when memory context is not activated."""

    def retrieve(
        self,
        scope_hint: Mapping[str, Any] | None,
        query: str,
        purpose: str,
        limit: int,
    ) -> dict[str, Any]:
        del scope_hint, query, purpose, limit
        raise MemoryContextDisabled("Recuperación de memoria desactivada.")


class MockMemoryContextAdapter:
    """Deterministic empty retrieval with a valid coverage_manifest.v1."""

    def __init__(self, *, policy_version: str = "mock.v1") -> None:
        self.policy_version = policy_version
        self.calls: list[dict[str, Any]] = []

    def retrieve(
        self,
        scope_hint: Mapping[str, Any] | None,
        query: str,
        purpose: str,
        limit: int,
    ) -> dict[str, Any]:
        if not isinstance(query, str):
            raise MemoryContextError("query debe ser texto.")
        if purpose not in {"question", "report", "summary", "wizard"}:
            raise MemoryContextError("purpose no es válido.")
        if not isinstance(limit, int) or limit < 1 or limit > 100:
            raise MemoryContextError("limit debe estar entre 1 y 100.")
        scope = dict(scope_hint or {})
        requested = ["mock.memory"]
        if scope.get("dossier_id") is not None:
            requested.append(f"dossier:{scope['dossier_id']}")
        self.calls.append(
            {
                "scope_hint": scope,
                "query": query,
                "purpose": purpose,
                "limit": limit,
            }
        )
        return empty_memory_retrieval_response(
            policy_version=self.policy_version,
            requested=requested,
        )


class HttpMemoryContextAdapter:
    """HTTP consumer stub (Signal memory API). Not activated in MEMSOL-05."""

    def __init__(
        self,
        *,
        base_url: str,
        timeout_seconds: float = 10.0,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def retrieve(
        self,
        scope_hint: Mapping[str, Any] | None,
        query: str,
        purpose: str,
        limit: int,
    ) -> dict[str, Any]:
        del scope_hint, query, purpose, limit
        if not self.base_url.startswith("https://"):
            raise MemoryContextError("MEMORY_CONTEXT_BASE_URL debe usar HTTPS en modo http.")
        # Full HTTP retrieve lands with Signal memory contract (MEMSOL-02/05 remote).
        raise MemoryContextError(
            "El adaptador HTTP de memoria aún no está habilitado en este despliegue."
        )


def build_memory_context_adapter(
    mode: str,
    *,
    base_url: str = "",
    timeout_seconds: float = 10.0,
) -> MemoryContextAdapter:
    """Build adapter. Unknown/empty/typo never become http/shadow/augment."""
    normalized = str(mode or "disabled").strip().lower() or "disabled"
    if normalized == "disabled":
        return DisabledMemoryContextAdapter()
    if normalized == "mock":
        return MockMemoryContextAdapter()
    if normalized == "http":
        return HttpMemoryContextAdapter(base_url=base_url, timeout_seconds=timeout_seconds)
    raise MemoryContextError(
        "MEMORY_CONTEXT_MODE debe ser disabled, mock o http "
        f"(recibido {normalized!r}; fail-closed, never shadow/augment)."
    )


def get_memory_context_adapter() -> MemoryContextAdapter:
    """Resolve adapter from Flask config (defaults fail closed)."""

    mode = (
        str(current_app.config.get("MEMORY_CONTEXT_MODE", "disabled") or "disabled").strip().lower()
    )
    if mode not in {"disabled", "mock", "http"}:
        # Fail closed to disabled rather than raising at request time for typos in runtime config
        mode = "disabled"
    base_url = str(current_app.config.get("MEMORY_CONTEXT_BASE_URL", "") or "")
    timeout = float(current_app.config.get("MEMORY_CONTEXT_TIMEOUT_SECONDS", 10.0) or 10.0)
    return build_memory_context_adapter(mode, base_url=base_url, timeout_seconds=timeout)
