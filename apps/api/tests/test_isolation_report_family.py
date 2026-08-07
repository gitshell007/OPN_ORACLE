"""SV2-TESTS-AISLADOS · regresión de acoplamiento entre tests de la familia informes.

Documenta y cierra la clase de contaminación:

* **A** (polución): construir una app Flask (``configure_logging`` hace
  ``root.handlers.clear()``) y/o dejar el logger del módulo con
  ``disabled=True`` (efecto típico de Celery ``disable_existing_loggers``).
* **B** (víctima histórica): aserción de warning de claves PLACSP no
  clasificadas que dependía de ``caplog`` sobre el logger raíz.

El arreglo de producto en tests es captura con handler propio + reactivar el
logger (ya en ``test_procurement_award_snapshot_warns_about_unclassified_provider_keys``)
más el autouse de ``conftest`` que limpia cachés process-local y re-habilita
loggers tras cada test.

Este módulo falla si alguien reintroduce la dependencia de orden.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest

from opn_oracle import create_app
from opn_oracle.integrations import entity_intel, procurement
from opn_oracle.oracle import procurement_items


def _pollute_logging_like_integration() -> None:
    """Reproduce el residuo de A: app real + logger de módulo deshabilitado."""

    create_app(
        {
            "APP_ENV": "test",
            "SECRET_KEY": "isolation-pollution-only-key",
            "DATABASE_URL": "sqlite+pysqlite:///:memory:",
            "REDIS_URL": "redis://127.0.0.1:6379/15",
            "LOG_FORMAT": "console",
            "OPENAPI_ENABLED": False,
        }
    )
    logging.getLogger(procurement_items.__name__).disabled = True


def _capture_unclassified_warning() -> list[logging.LogRecord]:
    """Camino B seguro (no caplog / no root handler)."""

    capturados: list[logging.LogRecord] = []

    class _Coleccionador(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            capturados.append(record)

    handler = _Coleccionador(level=logging.WARNING)
    modulo_logger = logging.getLogger(procurement_items.__name__)
    nivel_previo = modulo_logger.level
    desactivado_previo = modulo_logger.disabled
    modulo_logger.addHandler(handler)
    modulo_logger.setLevel(logging.WARNING)
    modulo_logger.disabled = False
    try:
        unknown_keys = procurement_items._unclassified_snapshot_keys(
            "award",
            {"folder_id": "P_6_26", "signal_new_field": "value"},
        )
        snapshot = procurement_items._snapshot(
            "award",
            {"folder_id": "P_6_26", "signal_new_field": "value"},
            "P_6_26",
        )
    finally:
        modulo_logger.removeHandler(handler)
        modulo_logger.setLevel(nivel_previo)
        modulo_logger.disabled = desactivado_previo

    assert unknown_keys == {"signal_new_field"}
    assert snapshot["folder_id"] == "P_6_26"
    return capturados


@pytest.mark.unit
def test_b_isolated_unclassified_warning_is_visible() -> None:
    """B solo: el warning se observa sin polución previa."""

    capturados = _capture_unclassified_warning()
    assert len(capturados) == 1
    assert capturados[0].unclassified_keys == ["signal_new_field"]


@pytest.mark.unit
def test_a_then_b_unclassified_warning_survives_logging_pollution() -> None:
    """A→B: tras polución de logging, el camino seguro sigue viendo el warning."""

    _pollute_logging_like_integration()
    capturados = _capture_unclassified_warning()
    assert len(capturados) == 1
    assert capturados[0].unclassified_keys == ["signal_new_field"]


@pytest.mark.unit
def test_a_then_b_unclassified_warning_survives_logging_pollution_repeat() -> None:
    """Repetición del par A→B (no flake)."""

    _pollute_logging_like_integration()
    capturados = _capture_unclassified_warning()
    assert len(capturados) == 1


@pytest.mark.unit
def test_caplog_is_blind_after_a_proves_previous_coupling(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Demuestra el acoplamiento antiguo: caplog no ve el warning tras A.

    Si este test fallara (caplog de repente viera el warning), el arreglo por
    handler propio dejaría de ser necesario — y habría que re-evaluar. Mientras
    caplog quede ciego, la familia no debe depender de él tras crear apps.
    """

    _pollute_logging_like_integration()
    caplog.set_level(logging.WARNING, logger=procurement_items.__name__)
    procurement_items._snapshot(
        "award",
        {"folder_id": "P_6_26", "signal_new_field": "value"},
        "P_6_26",
    )
    # Camino frágil: 0 records aunque el warning se emitió (logger disabled o
    # handler de caplog eliminado del root).
    assert caplog.records == []


@pytest.mark.unit
def test_process_local_caches_clear_between_tests_boundary() -> None:
    """Las cachés process-local no deben arrastrar hits entre tests."""

    # Seed real module caches (no monkeypatch) — el autouse del conftest debe
    # vaciarlas al terminar ESTE test; el siguiente lo comprueba.
    procurement._AWARDS_CACHE.set(("seed",), {"items": [], "total": 0})
    procurement._SUGGEST_CACHE.set(("seed",), {"items": []})
    entity_intel._CACHE.set(("seed",), {"ok": True})
    assert procurement._AWARDS_CACHE.get(("seed",)) is not None
    assert procurement._SUGGEST_CACHE.get(("seed",)) is not None
    assert entity_intel._CACHE.get(("seed",)) is not None


@pytest.mark.unit
def test_process_local_caches_were_cleared_by_autouse() -> None:
    """Companion del test anterior: tras el autouse no queda el seed."""

    assert procurement._AWARDS_CACHE.get(("seed",)) is None
    assert procurement._SUGGEST_CACHE.get(("seed",)) is None
    assert entity_intel._CACHE.get(("seed",)) is None


@pytest.mark.unit
def test_disposable_db_guard_rejects_non_test_names() -> None:
    """El guard de conftest no deja apuntar TEST_DATABASE_URL a bases no desechables."""

    from tests.conftest import _assert_disposable_database_url

    with pytest.raises(RuntimeError, match="not unambiguously disposable"):
        _assert_disposable_database_url(
            "postgresql+psycopg://oracle_app:x@127.0.0.1:5432/oracle_dev",
            env_name="TEST_DATABASE_URL",
        )
    with pytest.raises(RuntimeError, match="not a local/CI disposable host"):
        _assert_disposable_database_url(
            "postgresql+psycopg://oracle_app:x@db.prod.example:5432/oracle_test",
            env_name="TEST_DATABASE_URL",
        )
    # Positive: canonical CI / local disposable names
    _assert_disposable_database_url(
        "postgresql+psycopg://oracle_migrator:x@127.0.0.1:5432/oracle_test",
        env_name="TEST_DATABASE_URL",
    )
    _assert_disposable_database_url(
        "postgresql+psycopg://oracle_migrator:x@127.0.0.1:5432/oracle_test_aislados_147",
        env_name="TEST_DATABASE_URL",
    )


@pytest.mark.unit
def test_app_fixture_still_uses_sqlite_memory(app: Any) -> None:
    """El fixture unitario no se redirige a Postgres aunque haya TEST_* en el entorno."""

    assert (
        "sqlite" in str(app.config["SQLALCHEMY_DATABASE_URI"]).lower()
        or "sqlite"
        in str(
            app.config.get("DATABASE_URL", app.config.get("SQLALCHEMY_DATABASE_URI", ""))
        ).lower()
    )
