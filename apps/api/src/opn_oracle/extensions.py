"""Application extensions created without binding to a global Flask app."""

from __future__ import annotations

from typing import Any

from flask_limiter import Limiter
from flask_limiter.util import get_remote_address
from flask_login import LoginManager
from flask_migrate import Migrate
from flask_session import Session as FlaskSession
from flask_sqlalchemy import SQLAlchemy
from redis import Redis
from sqlalchemy import MetaData, event, text
from sqlalchemy.orm import DeclarativeBase, Session

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


db = SQLAlchemy(model_class=Base)
migrate = Migrate(compare_type=True)
login_manager = LoginManager()
server_session = FlaskSession()
limiter = Limiter(key_func=get_remote_address, default_limits=[])
SESSION_CONTEXT_KEY = "opn_oracle_transaction_context"


class TenantContextChanged(RuntimeError):
    """Raised when one transaction is reused under a different tenant or actor."""


def _context_fingerprint() -> tuple[str, str]:
    from opn_oracle.tenants.context import get_tenant_context

    context = get_tenant_context(required=False)
    return (
        str(context.tenant_id) if context and context.tenant_id else "",
        str(context.actor_id) if context and context.actor_id else "",
    )


def _assert_transaction_context(session: Session) -> None:
    expected = session.info.get(SESSION_CONTEXT_KEY)
    if expected is not None and expected != _context_fingerprint():
        raise TenantContextChanged(
            "TenantContext cambió dentro de una transacción; finaliza la transacción antes."
        )


@event.listens_for(Session, "after_begin")
def set_postgres_transaction_context(session: Session, transaction: Any, connection: Any) -> None:
    """Set tenant and actor only for the current PostgreSQL transaction."""

    if connection.dialect.name != "postgresql":
        return
    from opn_oracle.tenants.context import get_tenant_context

    context = get_tenant_context(required=False)
    tenant_id = str(context.tenant_id) if context and context.tenant_id else ""
    actor_id = str(context.actor_id) if context and context.actor_id else ""
    fingerprint = (tenant_id, actor_id)
    previous = session.info.get(SESSION_CONTEXT_KEY)
    if previous is not None and previous != fingerprint:
        raise TenantContextChanged("La transacción ya pertenece a otro TenantContext.")
    if transaction.parent is None:
        session.info[SESSION_CONTEXT_KEY] = fingerprint
    connection.execute(
        text("SELECT set_config('app.tenant_id', :tenant_id, true)"),
        {"tenant_id": tenant_id},
    )
    connection.execute(
        text("SELECT set_config('app.actor_id', :actor_id, true)"),
        {"actor_id": actor_id},
    )


@event.listens_for(Session, "do_orm_execute")
def guard_orm_execute(orm_execute_state: Any) -> None:
    _assert_transaction_context(orm_execute_state.session)


@event.listens_for(Session, "before_flush")
def guard_flush(session: Session, flush_context: Any, instances: Any) -> None:
    del flush_context, instances
    _assert_transaction_context(session)


@event.listens_for(Session, "after_transaction_end")
def clear_transaction_context(session: Session, transaction: Any) -> None:
    if transaction.parent is None:
        session.info.pop(SESSION_CONTEXT_KEY, None)


def create_redis_client(url: str, *, timeout: float) -> Redis:
    """Create a lazy Redis client; no network call is made during app import."""

    return Redis.from_url(
        url,
        socket_connect_timeout=timeout,
        socket_timeout=timeout,
        decode_responses=True,
    )


def init_extensions(app: Any) -> None:
    from opn_oracle import models  # local import keeps extension construction acyclic

    _ = models.MODEL_REGISTRY
    db.init_app(app)
    migrate.init_app(app, db)
    app.config["SESSION_REDIS"] = Redis.from_url(
        app.config["SESSION_REDIS_URL"],
        socket_connect_timeout=app.config["DEPENDENCY_TIMEOUT_SECONDS"],
        socket_timeout=app.config["DEPENDENCY_TIMEOUT_SECONDS"],
    )
    server_session.init_app(app)
    login_manager.init_app(app)
    limiter.init_app(app)
    app.extensions["oracle_redis"] = create_redis_client(
        app.config["REDIS_URL"], timeout=app.config["DEPENDENCY_TIMEOUT_SECONDS"]
    )
