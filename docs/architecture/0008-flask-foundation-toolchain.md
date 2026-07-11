# ADR 0008 — Toolchain de la fundación Flask

- **Estado:** accepted
- **Fecha:** 2026-07-10

## Contexto

La fase 02 necesitaba fijar runtime, dependencias, OpenAPI, persistencia y calidad sin acoplar aún
autenticación ni dominio. El Python 3.9 del sistema no era una base soportable, pero existe Python
3.11 local. El repositorio no tenía gestor ni lockfile Python.

## Decisión

- Python 3.11 como mínimo y `uv` con `uv.lock` para resolución reproducible.
- APIFlask 2.4 sobre Flask 3.1 para schemas Marshmallow y OpenAPI 3.
- Flask-SQLAlchemy con SQLAlchemy 2, psycopg 3 y Flask-Migrate/Alembic.
- Ruff para lint/formato, mypy estricto con excepción limitada para decoradores sin tipos de
  APIFlask, y pytest con cobertura mínima del 85 %.
- JSON estructurado en producción y formato legible en local, ambos con redacción central.
- Gunicorn no registra la request line; Flask emite el acceso sin query string y aplica redacción
  recursiva a mensajes, excepciones, argumentos y campos estructurados.
- OpenAPI y documentación interactiva deshabilitados por defecto en producción.
- Un proxy confiable solo se habilita mediante `TRUSTED_PROXY_COUNT`; por defecto es cero.

La migración inicial solo crea `system_metadata`, tabla global de operación. No contiene datos de
tenant ni anticipa el modelo de dominio de la fase 03.

## Alternativas consideradas

- Python 3.12 descargado por `uv`: descartado para aprovechar el runtime 3.11 ya instalado.
- Flask-Smorest: viable, pero APIFlask ofrece una integración compacta de validación y contrato.
- Dependencias no fijadas o `requirements.txt` manual: descartadas frente al lock reproducible.
- SQLite como integración: se limita a unit tests; migraciones y readiness se validan contra
  PostgreSQL real.

## Consecuencias

- El cliente TypeScript podrá generarse desde `docs/api/openapi.json`.
- Cambiar de framework OpenAPI requeriría preservar el contrato y Problem Details.
- Docker usa el mismo Python 3.11 y lockfile, pero su build debe validarse con Docker disponible.
- Redis está inicializado como infraestructura; sesiones, límites y Celery llegarán en sus fases.
- Readiness usa timeout de checkout del pool, connect timeout, `statement_timeout` PostgreSQL y
  timeouts de socket/connect Redis; las pruebas de integración son opt-in y exigen una DB test.
