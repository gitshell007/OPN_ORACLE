# 57 — Cobertura del informe de entidad y del wizard: el gate de 84 % está en rojo (P1)

> Contexto: los 107 tests de integración se han ejecutado por primera vez y **pasan los 426**.
> Lo que queda en rojo es el umbral de cobertura: `--cov-fail-under=84` y estamos en **80,70 %**.
> No es un umbral caprichoso: `scripts/api-test.sh --unit` corre a propósito sin cobertura porque
> el umbral cuenta con los tests de integración, así que la tirada completa (la que ejecuta el CI
> en «Backend, migrations and integration») falla hoy.

## Dónde está el hueco, medido

Tirada completa con `ORACLE_RUN_INTEGRATION=1` (Postgres 17 + Redis locales):

| Módulo | Cobertura | Sentencias sin cubrir |
|---|---|---|
| `oracle/entity_dossier_report.py` | **47 %** | 322 |
| `ai/context.py` | 74 % | 63 |
| `oracle/competitive_procurement_report.py` | 26 % | 41 |

Los tramos sin cubrir de `entity_dossier_report.py` son los que de verdad importan, porque son
justo los que han fallado en producción durante los últimos días:

- **809-906**: `process_entity_dossier_report`, el job completo. Ningún test lo ejecuta.
- **919-1258**: `_run_waiting_area_agent`, incluida la reserva de cuota, el lease y el manejo de
  fallo del proveedor.
- **1302-1624**: `incorporate_entity_dossier_report`, la materialización de `Evidence` y el
  render de la revisión.

Ese 47 % explica por qué se nos escaparon en producción, y no en los tests, el `json_data` vs
`payload`, el `model_validate` en modo Python sobre UUID serializados, y el truncado por exceso
de fuentes citables.

## Qué hay que cubrir (por valor, no por porcentaje)

No persigas el número: cubre estos caminos y el número llegará solo.

**1. El job de punta a punta (`process_entity_dossier_report`).** Con el cliente de Signal y el
proveedor de IA falseados, comprueba: que los checkpoints avanzan; que `computed_metrics`,
`source_limits` y `pending_evidence_sources` quedan en `result_ref`; que el `corpus_hash` es
estable entre dos ejecuciones con el mismo payload; y que el tope global de fuentes se aplica y
se declara.

**2. Degradación de la contratación dentro del job real.** Ya hay test de
`load_entity_procurement_context`, pero no de que el job **entero** sobreviva: con la fuente de
adjudicaciones caída, el informe debe generarse igual, con `section_status` y `source_limits`
declarándolo. Es la garantía que más caro sale si se rompe: el job es `retryable=False`.

**3. Incorporación (`incorporate_entity_dossier_report`).** Que se materializan las `Evidence`
con `source_kind='entity_intel'` —el CHECK de la tabla solo admite ciertos valores, y por ahí
circulan ahora `registry_act`, `news`, `patent`, `disclosure` y `procurement_award` como
subtipo—, que se enlazan al expediente, que la operación es idempotente (incorporar dos veces no
duplica evidencias ni informes) y que un informe sin citas también se incorpora.

**4. `_run_waiting_area_agent`.** Que un fallo del proveedor libera la reserva de cuota y marca
el intento como fallido, y que el `AIAuditLog` registra proveedor, modelo y `error_code`.

**5. `ai/context.py` (wizard, líneas 503-737).** Le corresponde al track del asistente de
expediente, pero arrastra el mismo gate. Cubre al menos el recorte por `max_tokens` y el camino
con `answers` vacías.

## Criterios de aceptación

- `uv run pytest` con `ORACLE_RUN_INTEGRATION=1` pasa **sin** `--cov-fail-under` desactivado:
  cobertura ≥ 84 %.
- `oracle/entity_dossier_report.py` por encima del 75 %.
- Los tests nuevos son de comportamiento, no de texto: nada de comprobar el código fuente con
  `inspect.getsource` ni de afirmar sobre cadenas de docstrings. (Escarmiento reciente: un test
  que miraba el fuente pasaba aunque el arreglo estuviera deshecho, porque lo satisfacía un
  comentario que mencionaba la propia excepción.)
- Cada test nuevo debe fallar si se revierte el comportamiento que cubre. Verifícalo mutando.

## Cómo ejecutar la suite completa sin Docker

Docker no está disponible en el equipo; con Postgres 17 y Redis por Homebrew basta:

```bash
createdb oracle_test
POSTGRES_DB=oracle_test POSTGRES_USER="$(whoami)" \
  ORACLE_MIGRATOR_PASSWORD=ci-migrator-only ORACLE_APP_PASSWORD=ci-app-only \
  sh infra/postgres/init/10-oracle-roles.sh

cd apps/api
export ORACLE_RUN_INTEGRATION=1
export TEST_DATABASE_URL="postgresql+psycopg://oracle_migrator:ci-migrator-only@127.0.0.1:5432/oracle_test"
export TEST_RUNTIME_DATABASE_URL="postgresql+psycopg://oracle_app:ci-app-only@127.0.0.1:5432/oracle_test"
export TEST_REDIS_URL="redis://127.0.0.1:6379/14"
uv run pytest -q
```

Aviso de aislamiento que ya nos ha mordido: al arrancar el worker real, Celery reconfigura el
logging con `disable_existing_loggers` y deja loggers de módulo en `disabled=True`; y
`configure_logging` hace `root.handlers.clear()` al construir la app, que se lleva el handler de
`caplog`. Si un test tuyo depende de logs, engancha tu propio handler y reactiva el logger,
restaurando ambos estados al terminar (hay un ejemplo en `tests/test_procurement.py`).

## No hacer

- No bajes `--cov-fail-under`. El umbral es la señal de que este módulo está poco probado.
- No añadas tests que solo ejecuten líneas para subir el porcentaje sin comprobar nada.
- No toques el comportamiento de producción para hacerlo más testeable sin decirlo: si algo
  necesita refactor para poder probarse, hazlo explícito en la entrega.
