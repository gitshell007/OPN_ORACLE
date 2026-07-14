# 32 — Cerrar el arco de la reunión: resultados, decisiones y tareas de seguimiento (P2)

> Lee `18_UX_REMEDIATION_OVERVIEW.md` (reglas comunes). Al terminar, **despliega** (modo rápido UAT,
> D-022) y **verifica en vivo**. No es feature de IA: es dominio + UX.

## Problema (auditoría en vivo + código, 2026-07-13/14)

El arco de reunión se prepara (briefing, ya operativo tras el prompt 31) pero **no se cierra**.
Al abrir una reunión, «Siguientes acciones permitidas» solo ofrece **Completada / Cancelada**:
marcar «Completada» únicamente cambia el estado (`oracle/routes.py:2098`
`"planned": {"completed","cancelled"}`), **sin capturar resultados, decisiones ni tareas de
seguimiento**. El producto (memoria §9.4 «tareas posteriores»; §9.7 «qué se decidió, por qué»)
exige que una reunión deje trabajo y memoria: decisiones y siguientes acciones trazables.

## Estado real del código (verificado)

- `Meeting` (`oracle/models.py`): tiene `status (planned/completed/cancelled)`, `scheduled_at`,
  `objective`, **`notes`** (Text). No hay captura estructurada de resultados al completar.
- `Decision` (`oracle/models.py`): existe con `status (proposed/approved/rejected/superseded)`,
  `rationale`, `decided_by_user_id`, `decided_at` y evidencia (`DecisionEvidence`). Permiso
  `task.read`/`task.write`. Rutas en `oracle/routes.py` (registro genérico de recursos ~1515/1906;
  evidencia ~2290).
- Creación de **tarea vinculada** ya resuelta y probada en el prompt 27 (`promote_signal_link` en
  `oracle/service.py` crea `Task` con `content` de traza, `linked_resource_type/id`,
  `origin`). **Reutiliza ese patrón**, no lo reinventes.

## Objetivo

Que al **completar** una reunión el usuario pueda, en el mismo paso: registrar **resultados/notas**,
**una o varias decisiones** (con motivo y, opcionalmente, evidencia del expediente) y **tareas de
seguimiento** con responsable y fecha — todo vinculado a la reunión y visible en Decisiones, Tareas,
«Siguientes acciones» del Resumen e Inicio.

## Alcance

1. **Auditar primero** los flujos actuales de Decisiones y Tareas (pestañas del expediente) y
   **reutilizarlos**; si Decisiones aún no permite crear/listar/vincular evidencia desde la UI,
   complétalo con el patrón existente de recursos del expediente.
2. **Completar reunión con resultados:** el diálogo/acción «Completada» acepta `notes`
   (resultados) y, opcionalmente, N decisiones (título + `rationale` + estado inicial `proposed`) y
   N tareas de seguimiento (título + responsable + `due_date`). Todo en una transacción; los campos
   vacíos no bloquean (completar sin resultados sigue permitido).
3. **Trazabilidad:** decisiones y tareas creadas quedan vinculadas a la reunión de origen
   (metadata/`content` con `meeting_id`), y las tareas usan `origin`/`linked_resource_*` como en el
   prompt 27 para aparecer en «Siguientes acciones» e Inicio.
4. **Vínculo reunión→decisión visible:** el detalle de la reunión completada muestra sus decisiones
   y tareas resultantes; la pestaña Decisiones muestra la reunión de origen.
5. **Contrato:** regenerar OpenAPI y cliente si cambia (`api:client:check` sin drift).

## Criterios de aceptación

- [ ] Completar una reunión permite dejar resultados + ≥1 decisión + ≥1 tarea de seguimiento en un
      paso; los vacíos no bloquean.
- [ ] Las decisiones aparecen en la pestaña Decisiones con su motivo y su reunión de origen; las
      tareas en Tareas y en «Siguientes acciones» del Resumen e Inicio.
- [ ] Concurrencia optimista respetada (`version`/If-Match) y permisos (`meeting.write`,
      `task.write`) aplicados; sin duplicación en reintentos.
- [ ] Tests backend (completar con/sin resultados, creación vinculada, idempotencia) y frontend
      (diálogo, envío, render). Suite completa verde.
- [ ] Migración solo si el esquema lo exige (Meeting.notes/Decision/Task ya existen).

## Despliegue y verificación en producción (obligatorio)

1. Si toca migración/seguridad/contrato: **CI completo manual** (`workflow_dispatch`, D-024) verde.
   Si no, checks locales proporcionales (recuerda `ruff format --check .` sobre todo el árbol, que
   ha fallado en releases anteriores).
2. Modo rápido UAT (D-022): backup local + restore aislado, release inmutable,
   `sudo oracle-control update`, smoke + `oracle-control health`.
3. Verificación funcional (expediente CATL `292d85e5-…`, reunión «Reunión de posicionamiento con
   Gobierno de Aragón»): completarla con una decisión y una tarea; confirmar que aparecen en
   Decisiones, Tareas, Resumen e Inicio, con vínculo a la reunión. Sin errores de consola.
4. Actualiza `docs/implementation/STATUS.md` (release-id, comandos, resultado).

## No hacer

- No reinventar la creación de tareas: reutiliza el patrón del prompt 27.
- No forzar la captura de resultados/decisiones para completar (deben ser opcionales).
- No introducir migraciones innecesarias.
