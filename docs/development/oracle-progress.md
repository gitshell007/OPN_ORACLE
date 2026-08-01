# Progreso de desarrollo vivo

Este historial es complementario al `history` de cada funcionalidad en
`oracle-roadmap.json`. Se registran snapshots y cambios significativos; las pruebas se nombran
con el comando real o con el archivo que las contiene.




## 2026-08-01  — ORC-MEM-001 / MDEV-01 REWORK

- Trabajo: cierre real del contrato bilateral memory.v1 tras REWORK Codex.
- Archivos: docs/contracts/memory_v1/**, memory_contract_v1.py, tests, ledger/STATUS.
- Pruebas: contract + openapi structural; Signal mutations A–F.
- Riesgos heredados: NO_ROLLBACK, beat drift.
- Estado: in_progress (validated contractual tests; runtime pack still stub).

## 2026-08-01  — ORC-MEM-001 / MDEV-01 contracts

- Funcionalidad: ORC-MEM-001.
- Trabajo: contratos memory.v1 bilaterales (schemas, fixtures, error catalog, ADR,
  OpenAPI proposal, migration matrix, precedence, credential-per-tenant, UX ES),
  módulo `memory_contract_v1.py`, tests contract, citabilidad y degradación.
- Archivos: `docs/contracts/memory_v1/**`, `apps/api/src/opn_oracle/integrations/memory_contract_v1.py`,
  `apps/api/tests/test_memory_v1_contract.py`, ledger/STATUS/roadmap.
- Migraciones: ninguna aplicada.
- Pruebas: pytest test_memory_v1_contract + test_memory_context (18 passed combined prior).
- Riesgos: NO_ROLLBACK / beat drift heredados.
- Estado: approved → in_progress (contratos congelados; runtime en MDEV-02+).

## 2026-08-01  — ORC-MEM-001 / MDEV-00 rework

- Funcionalidad: ORC-MEM-001 — Memoria dual Oracle↔Signal (Dev).
- Trabajo realizado: REWORK MDEV-00 — roadmap con diff mínimo, ledger corregido (sin
  autorreferencia), censo 8 Oracle + 9 Signal incl. d3804ba, evidencia RO durable bajo
  docs/implementation/evidence/mdev-00/, mutación pack BLOCKED_PACK_INTEGRITY, deploy Signal
  NO_ROLLBACK, beat drift, PR/integración master según AGENTS.
- Archivos: ledger, bilateral, evidence/*, STATUS, roadmap (patch), progress, decisions, dashboard.
- Migraciones: ninguna.
- Pruebas: pack verify; pytest memory_context 9; signal focused 31; dashboard --check.
- Resultado: baseline documentado; integración en master vía PR (ver Gate Packet).
- Riesgos: NO_ROLLBACK Signal Dev; memory 404 en Dev; lifecycle pendiente.
- Pendiente: PASS Codex; MDEV-01 solo tras master con ledger.
- Estado: `approved` (idea; no implemented).

## 2026-08-01 — ORC-SIG-001 y ORC-EVID-001 · producción validada

- Oracle desplegado en `20260801T114127Z-quick-b0a80eb` tras backup+restore aislado; health HTTPS,
  Celery, ClamAV y coherencia del release correctos.
- Canario: memoria de intake aceptada visible tras recarga; documento `ready/clean` con dos chunks y
  evidencia; pregunta durable con una cita y tres hechos; monitor Signal `active/active`, cuatro
  señales producidas/vinculadas y sync real.
- Signal `8973a09`: consumer 14 local-first (`qwen3.5:9b→qwen3.6:27b`), PostgreSQL ligado solo a
  loopback y servicios/health activos. Las dos preguntas medidas costaron 0 y no usaron fallback.
- Estado anterior/nuevo: `ORC-SIG-001 implemented→deployed`; `ORC-EVID-001 implemented→deployed`.
- Deuda explícita: sustituir el volumen documental local de UAT por S3 compatible antes de escalar.

## 2026-08-01 — ORC-SIG-001 · reconciliación de `query=null` en respuesta de monitor

- Canario real: `POST /api/v1/oracle/monitors` devolvió 201 en Signal y persistió un monitor activo,
  pero Oracle rechazó la respuesta porque Signal representa como `null` la consulta vacía de una
  vigilancia basada en keywords/entidades.
- Corrección: el modelo de respuesta `ProviderMonitor` normaliza `null→""`; el modelo de request y
  su invariante de alcance no se relajan. Readiness usa el provider canónico `signal-avanza`.
- Pruebas: contrato+HTTP **16 passed**; backend completo con PostgreSQL+Redis **859 passed** y
  cobertura **84.15%**; Ruff y mypy correctos. Las mutaciones reproducen tanto el `ValidationError`
  como el falso negativo de Signal.
- Estado anterior/nuevo: `implemented→deployed`; create idempotente reconciliado y sync productivo.

## 2026-08-01 — ORC-DOS-001, ORC-ACT-001, ORC-SIG-001 y ORC-EVID-001 · candidata de workflow completo

- Trabajo realizado: la creación UI acepta y versiona su intake; Actividad lo hace visible; el
  detalle de competidor prepara una vigilancia revisable; el runtime productivo recibe una opción
  UAT de documentos locales durables con ClamAV fijado por digest.
- Contratos: OpenAPI y cliente TypeScript regenerados; no hay migración nueva. La aceptación humana
  es opt-in en API y no autoactiva monitores.
- Pruebas ejecutadas: backend completo con PostgreSQL+Redis **858 passed**, cobertura **84.13%**;
  frontend completo **286 passed**; Ruff check/formato, mypy, ESLint sin errores, TypeScript, build,
  cliente OpenAPI y Compose productivo correctos. Audit productivo npm: 0 vulnerabilidades.
- Mutaciones: se retiraron, una por una, la materialización de intención, la navegación al monitor y
  el escape de storage local; cayeron respectivamente el test HTTP de mercado, el test UI del actor
  y el test de configuración documental. Todo fue restaurado y revalidado.
- Riesgo explícito: el volumen local de documentos es solo para esta UAT de servidor único; antes de
  escalar hay que migrar objetos a S3 compatible y verificar restore. OpenRouter queda fuera de Ask
  y Brief porque el primario/fallback local ya está validado y no necesita gasto cloud.
- Estado anterior/nuevo: las funcionalidades conservan su estado hasta completar despliegue y
  canario real; la candidata de código sí está validada.

## 2026-08-01 — ORC-DOS-001 · MEMSOL desplegado y canario local-only

- Release producción: `20260801T101526Z-quick-0331ae5`; commit de aplicación `0331ae5`.
- Gate: CI `30695007903` completo verde; control de release, HTTPS/readiness, Redis/PostgreSQL,
  worker y beat correctos. Sin migración nueva sobre el head `0028`.
- Canario HTTP real: intención aceptada + requisito + oferta → Preguntar `succeeded` con respuesta
  persistida de 1.032 caracteres → Informe libre `proposed` con 8 secciones. Duración total 84,175 s.
- Auditoría: ambos snapshots contienen `intent_revision_id`, `intent_content_hash`, un requisito y
  una oferta; Oracle y Signal registran `ollama/qwen3.5:9b`. OpenRouter 0 para las task keys MEMSOL y
  memory engine Signal apagado.
- Incidencia de rollout: el primer intento de activación detuvo el stack al no poder leer Redis los
  bind mounts de un release preparado con permisos demasiado restrictivos. Se igualaron los permisos
  al release precedente, Redis recuperó health y el forward-deploy oficial finalizó coherente.
- Higiene: ambos tenants canario, usuarios, membresías y políticas IA quedaron suspendidos/apagados.

## 2026-08-01 — ORC-DOS-001 · memoria de intención en Ask/Brief

- Funcionalidad: ORC-DOS-001 — expediente, intención y contexto durable.
- Trabajo realizado: `build_context()` incorpora la revisión aceptada, requisitos activos y oferta
  activa ligada a esa revisión; el manifiesto conserva IDs y hash del contenido aceptado.
- Pruebas: MEMSOL HTTP/PostgreSQL **3 passed** con `--no-cov`; ruff y mypy correctos en paths
  tocados. La ejecución focal con cobertura global falló únicamente el umbral agregado (3 tests no
  representan la suite), no los tests. Mutación de estado `accepted→rejected`: el test focal falla.
- Producción observada antes del hotfix: release `20260801T095500Z-quick-36fbed6`, 0027/0028 y
  servicios sanos. Primer canario: ambos jobs recibidos por Celery y fallidos antes de Signal porque
  el tenant sintético conservaba el cierre `public`; identidad suspendida y política apagada.
- Estado anterior/nuevo: validated → validated; falta desplegar este hotfix y repetir canario real.

## 2026-08-01 — MEMSOL release/memsol-local-only coverage gate

- Funcionalidad: Memoria Sol (Preguntar / Informe libre / intent) — candidata de release.
- Trabajo realizado: Suite de tests de comportamiento sobre conversations/custom_reports/jobs cancel-retry; corrección MockLLMProvider para schema estricto de brief; contrato OpenAPI intent; fixtures de integración reponen Alembic head 0028.
- Archivos modificados: `apps/api/tests/test_memsol_conversations_service.py` (nuevo), `apps/api/src/opn_oracle/ai/provider.py`, `apps/api/tests/test_contract.py`, `apps/api/tests/test_dossier_intent.py`, `apps/api/tests/test_memsol_workers.py`, fixtures integration teardown, `docs/implementation/STATUS.md`.
- Migraciones: ninguna nueva (0027/0028 ya en rama).
- Pruebas ejecutadas: `uv run pytest -q` con Postgres+Redis (`ORACLE_RUN_INTEGRATION=1`) → **858 passed**, cobertura **84.01%**; ruff en tests MEMSOL.
- Resultado: Gate local de cobertura superado sin bajar umbral.
- Riesgos detectados: CI remoto aún por verificar; producción sin deploy.
- Trabajo pendiente: CI PR #1 verde; autorización de canario prod.
- Estado anterior: under_review.
- Estado nuevo: under_review (candidato listo localmente).

## 2026-08-01 — ORC-PROC-002 y ORC-UX-003

- Funcionalidades: ORC-PROC-002 — Wizard de búsqueda multisector y CPV; ORC-UX-003 — Calidad UX, accesibilidad y responsive.
- Trabajo realizado: Se corrigió el E2E para que compruebe el interruptor ARIA real de vigilancia opcional, se hizo accesible por teclado la región desplazable de países y se elevó el área directa de selección de expedientes a 24 px.
- Archivos modificados: `tests/e2e/procurement-wizard.spec.ts`, `src/components/ui/eu-country-multiselect.tsx`, `src/components/ui/eu-country-multiselect.test.tsx`, `src/styles/concept-a.css`, `docs/development/oracle-roadmap.json`.
- Migraciones: Ninguna.
- Pruebas ejecutadas: `npm run test -- --run src/components/ui/eu-country-multiselect.test.tsx src/components/procurement/procurement-search-wizard.test.tsx` (26 passed); `npx playwright test tests/e2e/procurement-wizard.spec.ts tests/e2e/accessibility-security.spec.ts --project=desktop --project=mobile` (9 passed, 1 skipped).
- Resultado: El gate E2E observado en rojo queda reproducido y corregido para ambos viewports; Axe no informa violaciones en las rutas cubiertas.
- Riesgos detectados: Quedan criterios parciales de ORC-UX-003 y la validación completa de CI/producción.
- Trabajo pendiente: Esperar CI del candidato y hacer smoke autenticado tras el release local-only.
- Estado anterior: `under_review`.
- Estado nuevo: `under_review`.

## 2026-07-31  — ORC-GOV-001

- Funcionalidad: ORC-GOV-001 — Sistema vivo de planificación y desarrollo.
- Trabajo realizado: Auditoría read-only del repositorio; creación de roadmap estructurado, registro de decisiones, arquitectura, historial, validador/generador y dashboard HTML autónomo.
- Archivos modificados: `AGENTS.md`, `docs/development/oracle-roadmap.json`, `docs/development/oracle-decisions.md`, `docs/development/oracle-progress.md`, `docs/development/oracle-architecture.md`, `scripts/generate-development-dashboard.py`, `docs/development/oracle-development-dashboard.html`.
- Migraciones: Ninguna.
- Pruebas ejecutadas: `python3 scripts/generate-development-dashboard.py --check`; generación normal del dashboard; validación de HTML autónomo con parser estándar.
- Resultado: Roadmap válido, IDs y dependencias sin errores, dashboard generado de forma determinista y sin recursos externos.
- Riesgos detectados: Cambios funcionales ajenos sin commitear en `oracle-dev`; documentación histórica que aún dice `master`; E2E procurement-wizard rojo según STATUS.
- Trabajo pendiente: Seleccionar un ID de producto para la siguiente fase; actualizar roadmap y evidencias tras cada cambio.
- Estado anterior: `idea`.
- Estado nuevo: `validated`.

## 2026-07-31  — Snapshot de auditoría inicial

- Funcionalidad: ORC-PROJ-001 — Auditoría inicial del proyecto.
- Trabajo realizado: Inventario de Flask/blueprints, modelos, migraciones, Celery, frontend `/app`, cliente OpenAPI, tests, CI y runbooks; clasificación de comprobado, parcial, propuesto y desconocido.
- Archivos modificados: `docs/development/oracle-roadmap.json`, `docs/development/oracle-architecture.md`.
- Migraciones: Ninguna.
- Pruebas ejecutadas: No se ejecutó la suite completa de negocio en esta fase documental.
- Resultado: 10 módulos y 30 funcionalidades con IDs permanentes, dependencias y próximos pasos.
- Riesgos detectados: Activación externa de Signal/IA/documentos no demostrada en el árbol; cobertura nominal de participantes bloqueada; migración completa de Vector pendiente.
- Trabajo pendiente: Resolver los diez próximos puntos recomendados en el dashboard.
- Estado anterior: `proposed`.
- Estado nuevo: `validated`.
