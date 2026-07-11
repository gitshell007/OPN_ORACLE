"""Explicit request/job tenant context; never populated from untrusted tenant input."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from uuid import UUID


class TenantContextMissing(RuntimeError):
    """Raised before a tenant-scoped repository executes without context."""


@dataclass(frozen=True, slots=True)
class TenantContext:
    tenant_id: UUID | None
    actor_id: UUID | None
    access_reason: str | None = None
    platform_access: bool = False


_tenant_context: ContextVar[TenantContext | None] = ContextVar(
    "opn_oracle_tenant_context", default=None
)


def get_tenant_context(*, required: bool = True) -> TenantContext | None:
    context = _tenant_context.get()
    if required and (context is None or context.tenant_id is None):
        raise TenantContextMissing("Se requiere un contexto de tenant validado.")
    return context


def require_tenant_id() -> UUID:
    context = get_tenant_context()
    assert context is not None and context.tenant_id is not None
    return context.tenant_id


@contextmanager
def tenant_context(context: TenantContext) -> Iterator[TenantContext]:
    token: Token[TenantContext | None] = _tenant_context.set(context)
    try:
        yield context
    finally:
        _tenant_context.reset(token)


@contextmanager
def actor_context(actor_id: UUID) -> Iterator[TenantContext]:
    """Establish authenticated identity before a tenant is selected."""

    with tenant_context(TenantContext(tenant_id=None, actor_id=actor_id)) as context:
        yield context
