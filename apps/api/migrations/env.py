from __future__ import annotations

import logging
from logging.config import fileConfig

from alembic import context
from flask import current_app
from sqlalchemy import create_engine
from sqlalchemy.engine import make_url
from sqlalchemy.pool import NullPool

config = context.config
if config.config_file_name is not None:
    fileConfig(config.config_file_name)
logger = logging.getLogger("alembic.env")


def get_engine():  # type: ignore[no-untyped-def]
    return create_engine(current_app.config["DATABASE_MIGRATION_URL"], poolclass=NullPool)


def get_engine_url() -> str:
    return (
        make_url(current_app.config["DATABASE_MIGRATION_URL"])
        # Alembic only needs this URL for offline dialect configuration; online
        # migrations create their engine directly below. Keep credentials out
        # of Alembic config/log representations.
        .render_as_string(hide_password=True)
        .replace("%", "%%")
    )


config.set_main_option("sqlalchemy.url", get_engine_url())
target_db = current_app.extensions["migrate"].db


def get_metadata():  # type: ignore[no-untyped-def]
    return target_db.metadata


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=get_metadata(),
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = get_engine()
    try:
        with connectable.connect() as connection:
            context.configure(
                connection=connection, target_metadata=get_metadata(), compare_type=True
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        connectable.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
