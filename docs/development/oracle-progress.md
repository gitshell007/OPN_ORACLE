# Progreso de desarrollo vivo

Este historial es complementario al `history` de cada funcionalidad en
`oracle-roadmap.json`. Se registran snapshots y cambios significativos; las pruebas se nombran
con el comando real o con el archivo que las contiene.

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
