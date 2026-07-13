# 30 — Resumen estratégico de cambios (Weekly Change Agent) en «Qué ha cambiado» (P2)

> Lee `18_UX_REMEDIATION_OVERVIEW.md` (reglas comunes). Al terminar, **despliega** (modo rápido
> UAT, D-022) y **verifica en vivo**. Feature de IA: política gobernada por Signal (D-015), sin cloud.

## Problema (auditoría en vivo 2026-07-13)

«Qué ha cambiado» (`/app/changes`) muestra un **registro técnico de transiciones**: p. ej.
«dossier cambió de draft a active · Transición registrada sin motivo adicional». Es un audit-log,
no lo que promete el producto (memoria §9.7 y §14.9 Memory Curator; el Report Writer lista
«resúmenes de cambio semanal»): **qué ha cambiado estratégicamente desde la última revisión y por
qué importa** — nuevas señales relevantes, oportunidades/riesgos promovidos, movimientos de
actores, decisiones e hitos próximos, con evidencia.

## Estado real del código (verificado)

- El prompt de IA **`weekly_change`** YA existe en el registro
  (`apps/api/src/opn_oracle/ai/prompts/weekly_change/`).
- La ruta `GET /changes` (`oracle/routes.py:617`) devuelve transiciones crudas
  (`status_history`/audit), no un digest generado.
- **Blueprint a replicar (funciona):** el «Oráculo del expediente» (`dossier_situation_summary`) —
  mismo patrón gobernado por Signal, async en cola `ai`, evidencia citada, versión persistida y
  panel escaneable. Piezas: `oracle/summary.py`, `SignalGovernedLLMProvider` (`ai/provider.py`),
  `AIContextSnapshot`/`AIArtifact`/`AIAuditLog`, panel del Oráculo.

## Objetivo

Que «Qué ha cambiado» ofrezca, además del historial técnico, un **digest estratégico generado por
IA** por expediente (y opcionalmente agregado de la organización): «qué es nuevo o ha cambiado
desde la última revisión y por qué importa», con hechos/inferencias/recomendaciones separados y
`evidence_ids` verificados.

## Alcance

1. **Backend — digest por IA:** job Celery (cola `ai`) que construye el snapshot de cambios del
   periodo (nuevas/actualizadas señales, promociones a oportunidad/riesgo, cambios de estado,
   nuevos actores/candidatos, decisiones, tareas y reuniones próximas) acotado por tokens y con
   redacción/anti-inyección; invoca `weekly_change` vía `SignalGovernedLLMProvider`; valida schema
   estricto; persiste como artefacto versionado (`AIArtifact`/`AIAuditLog`, y una vista tipo
   `LivingSummary` de cambios). Idempotencia por snapshot/periodo; versión previa conservada ante
   fallo. Considera un disparo programado (Beat) análogo al resumen nocturno del Oráculo, más
   refresco manual con `Idempotency-Key`.
2. **Frontend — «Qué ha cambiado»:** añadir un panel de digest estratégico (titular, bloques
   escaneables con evidencia, confianza/cobertura, estado de refresco y feedback), conservando el
   historial técnico existente como detalle/trazabilidad. Sin mezclar ambos: el digest arriba,
   las transiciones crudas como respaldo auditable.
3. **Contrato:** regenerar OpenAPI y cliente si cambia (`api:client:check` sin drift).

## Dependencia Signal (gate, verificar primero)

Igual que el prompt 29: producción usa `AI_MODE=signal`. **Verifica que Signal gobierna la task
`weekly_change`** para `opn-oracle`. Si no, coordina el productor
(`/Users/gitshell/PycharmProjects/opn_signal`) replicando lo hecho para
`dossier_situation_summary`, o deja la feature **gated** con copy honesto. No actives cloud.

## Criterios de aceptación

- [ ] «Qué ha cambiado» muestra un digest estratégico citado a evidencia por expediente; sin
      cambios citables suficientes, lo dice honestamente (no inventa).
- [ ] El historial técnico de transiciones sigue disponible como respaldo auditable.
- [ ] Refresco idempotente por snapshot/periodo; fallo de proveedor conserva la versión previa.
- [ ] Tests backend (context builder de cambios, schema, idempotencia) y frontend (render del
      digest y del historial). Suite completa verde.
- [ ] Migración solo si el esquema lo exige; reutiliza artefactos IA existentes cuando sea posible.

## Despliegue y verificación en producción (obligatorio)

1. Si toca migración/seguridad/contrato: **CI completo manual** (`workflow_dispatch`, D-024) verde.
   Si no, checks locales proporcionales.
2. Modo rápido UAT (D-022): backup local + restore aislado, release inmutable,
   `sudo oracle-control update`, smoke + `oracle-control health`.
3. Verificación funcional autenticada (expediente CATL `292d85e5-…`, que ya tiene señales,
   oportunidad y tareas de promoción): generar el digest y confirmar que resume los cambios reales
   con fuentes; sin errores de consola.
4. Actualiza `STATUS.md` (release-id, comandos, resultado) y `DECISIONS.md`/`OPEN_QUESTIONS.md`
   (incluida la dependencia Signal).

## No hacer

- No llamar a proveedores IA directamente desde Oracle ni activar cloud.
- No sustituir el historial técnico auditable; el digest lo complementa, no lo reemplaza.
- No publicar un digest que no valide el schema.
