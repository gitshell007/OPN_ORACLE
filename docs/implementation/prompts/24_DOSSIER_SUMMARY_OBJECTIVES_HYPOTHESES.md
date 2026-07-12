# 24 — Visibilidad de objetivos e hipótesis del expediente (P3)

> Lee `18_UX_REMEDIATION_OVERVIEW.md` y las reglas comunes. Severidad **P3**.

## Problema observado (evidencia de auditoría)

Al crear un expediente con «Crear una base inicial editable» activada, el diálogo promete crear
«un objetivo de análisis, **dos hipótesis** y una vigilancia inicial». Pero:

- El **Resumen** del expediente no muestra objetivos ni hipótesis (solo Oráculo, situación,
  Salud/Oportunidad/Riesgo y bloques «No hay elementos accesibles»).
- **Configuración** solo expone Título / Objetivo / Descripción / Estado y los monitores; **no
  hay UI para ver ni editar las hipótesis** que la base inicial dice haber creado.

Resultado: el usuario no sabe si la base inicial hizo algo, ni puede trabajar sus objetivos e
hipótesis — piezas centrales del expediente (OPN_Oracle_Codex_Memory.md §4).

## Contexto de código

- Resumen: `src/components/navigation/product-dossier.tsx` (SummaryList «Oportunidades
  principales», etc.).
- Dominio: `DossierObjective` y `Hypothesis` existen en el modelo (`oracle/models.py`,
  migraciones `20260710_0004/0005`). Verifica endpoints de lectura/escritura de objetivos e
  hipótesis en `oracle/routes.py`; si no existen, este prompt incluye crearlos (con permiso,
  tenant scoping, validación) y regenerar OpenAPI/cliente.

## Objetivo

Que los objetivos y las hipótesis del expediente sean **visibles** y **gestionables**, y que la
«base inicial» tenga un efecto observable.

## Alcance e implementación sugerida

1. **Mostrar** objetivos e hipótesis en el Resumen del expediente (bloques propios, escaneables,
   con estado y evidencia si aplica).
2. **Gestionar** hipótesis: UI para listar, crear, editar estado (p. ej. activa/validada/
   descartada) y vincular evidencia, respetando `PermissionGate`. Igual para objetivos si aún no
   se pueden editar más allá del principal.
3. Verificar que el starter profile (D-014) efectivamente crea el objetivo y las dos hipótesis y
   que quedan enlazados y visibles; si no, corregir la creación.
4. Backend: exponer/consolidar endpoints de objetivos e hipótesis con validación y auditoría.
   Regenera OpenAPI/cliente si cambia contrato.

## Criterios de aceptación

- [ ] Tras crear un expediente con base inicial, el Resumen muestra su objetivo y sus dos
      hipótesis.
- [ ] El usuario puede crear/editar hipótesis y cambiar su estado desde la UI.
- [ ] Los cambios persisten con permiso, tenant scoping y auditoría.
- [ ] Tests: backend de objetivos/hipótesis; frontend del render y edición.

## Verificación

`apps/api`: `make lint typecheck test` (+ integración). Raíz: `lint typecheck test build`;
`api:client:check`. Smoke visual del Resumen. Actualiza `STATUS.md` (y `DECISIONS.md` si añades
contrato).

## No hacer

- No hardcodees hipótesis por sector; el modelo es transversal.
