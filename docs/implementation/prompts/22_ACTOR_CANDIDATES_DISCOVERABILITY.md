# 22 — Descubribilidad de «Candidatos detectados» de actor (P2)

> Lee `18_UX_REMEDIATION_OVERVIEW.md` y las reglas comunes. Severidad **P2**.

## Problema observado (evidencia de auditoría)

La pestaña **Actores** de un expediente con una señal que menciona explícitamente a **CATL** y
**Stellantis** muestra solo «Aún no hay actores / Usa "Vincular actor"». La vista de
**«Candidatos detectados»** (decisiones D-018/D-019) no se ofrece en el estado vacío, de modo
que un pilar del producto —convertir menciones en actores revisables— queda **invisible** para
el usuario que acaba de recibir señales con entidades.

## Contexto de código

- Frontend: `src/components/dossiers/dossier-actor-candidates.tsx` (ya implementa listar,
  revisar/importar, descartar y restaurar candidatos) y la pestaña Actores del expediente.
- Backend: `oracle/actor_candidates.py`, rutas en `oracle/routes.py`
  (`GET .../actor-candidates`, `.../import`, `.../review`), migración
  `20260712_0015_actor_candidate_reviews`.
- Derivación: los candidatos salen de las **entidades estructuradas** de las señales vinculadas y,
  en su ausencia, de patrones textuales conservadores (D-019).

## Objetivo

Que, cuando existan señales con entidades, el usuario **vea** y pueda actuar sobre los candidatos
de actor; y que, cuando no existan, la UI **explique** la función en lugar de ocultarla.

## Alcance e implementación sugerida

1. **Siempre presente:** renderizar la sección «Candidatos detectados» en la pestaña Actores (o
   como sub-vista clara), con estado vacío explicativo cuando no haya candidatos («Aún no hay
   candidatos; aparecerán aquí las empresas, personas y organismos mencionados en las señales
   vinculadas»). No esconder la sección entera cuando la lista está vacía.
2. **Investigar por qué la señal de CATL/Stellantis no generó candidatos** en el caso de prueba
   (expediente `292d85e5-3dc1-4c2f-81a5-8a73a29e1fb4`, señal de `elespanol.com`): ¿la señal traía
   `entities` estructuradas?, ¿corrió la recuperación textual conservadora?, ¿el triaje debe
   ejecutarse antes? Corrige el eslabón que impide que menciones evidentes afloren como
   candidatos, sin crear actores automáticamente (mantener revisión humana).
3. **Enganche desde la señal:** enlazar desde el detalle de la señal a los candidatos derivados de
   ella (coordinado con el prompt 20, «Registrar actor»).
4. Respetar `PermissionGate` (`actor.write`) y la procedencia/auditoría existentes.

## Criterios de aceptación

- [ ] La pestaña Actores muestra la sección de candidatos con estado vacío explicativo aunque no
      haya ninguno.
- [ ] Una señal vinculada que nombra organizaciones produce candidatos revisables (con su fuente),
      sin convertirse automáticamente en actor.
- [ ] Importar un candidato crea/reutiliza el actor canónico y lo vincula, con auditoría.
- [ ] Tests: frontend del estado vacío + import; backend/integración de derivación desde una señal
      con y sin `entities`.

## Verificación

`apps/api`: `make lint typecheck test` (+ integración de candidatos con `TEST_*`). Raíz:
`lint typecheck test build`; `api:client:check`. Smoke visual de Actores. Actualiza `STATUS.md`.

## No hacer

- No crees actores automáticamente ni dupliques una tabla de candidatos (D-018/D-019).
- No ejecutes NER remoto por cada visita; respeta la derivación reproducible existente.
