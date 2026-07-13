# 27 — Promoción accionable: siguiente acción y tarea al promover (P2)

> Lee `18_UX_REMEDIATION_OVERVIEW.md` (reglas comunes) antes de empezar. Al terminar, **despliega
> a producción** con el modo rápido UAT (D-022) y verifica en vivo. El release incluirá también el
> commit ya mergeado `4fc6acb` (candidatos de actor por coordinación) — verifica su efecto según
> la sección final.

## Problema (auditoría en vivo 2026-07-13)

El arco señal→oportunidad ya funciona, pero la oportunidad creada **nace inerte**: solo tiene
título/descripción y valores por defecto (Identificada · 40 · 50 %). En el Resumen del expediente,
el bloque **«Siguientes acciones» queda vacío** («No hay elementos accesibles»), y en Inicio no
aparece nada que hacer. La fórmula del producto (memoria §7: *qué decisión se puede tomar ahora,
qué siguiente acción conviene*) exige que promover deje **trabajo accionable**, no solo un registro.

## Estado real del código (punteros verificados)

- `Opportunity.next_action` existe (`apps/api/src/opn_oracle/oracle/models.py:448`, Text, default
  vacío) y `RiskItem.mitigation` (`models.py:510`) + `RiskItem.due_date` (`models.py:514`).
  **La promoción no los rellena**: `promote_signal_link`
  (`apps/api/src/opn_oracle/oracle/service.py:502`) solo usa título, descripción y scores por
  defecto.
- El bloque «Siguientes acciones» del Resumen se alimenta de **tareas**
  (`src/components/navigation/product-dossier.tsx:133`: tasks no terminadas, con prioridad y
  `due_date`). Nadie crea una tarea en el flujo de promoción.
- El diálogo de promoción está en `src/components/dossiers/dossier-intelligence-section.tsx`
  (estado `promotionOpen`/`promotionKind`/`promotionTitle`, submit en `promote()` ~línea 428).
- `Task` tiene `due_date` (`models.py:756`) y alta manual ya existente en la pestaña Tareas.

## Objetivo

Que al promover una señal, el usuario pueda dejar en el mismo paso: **la siguiente acción**
(oportunidad) o **la mitigación** (riesgo), con **fecha objetivo opcional**, y opcionalmente una
**tarea** creada y vinculada — de modo que «Siguientes acciones» (Resumen) e Inicio muestren
trabajo real inmediatamente después de promover.

## Alcance

1. **Diálogo de promoción (frontend):** añadir campos opcionales «Siguiente acción» (oportunidad) /
   «Mitigación» (riesgo), «Fecha objetivo» y un checkbox «Crear tarea con esta acción» (marcado por
   defecto solo si el campo de acción tiene contenido). Mantenerlo ligero: el flujo debe seguir
   siendo de un paso; los campos vacíos no bloquean.
2. **Backend:** `promote_signal_link` acepta `next_action`/`mitigation` y `due_date` en el payload
   (validados, longitudes acotadas) y los persiste en el recurso. Si `create_task` es verdadero y
   hay acción, crear en la **misma transacción** una `Task` vinculada al expediente con título
   derivado de la acción, `due_date`, prioridad razonable y trazabilidad (metadata/description con
   referencia a la oportunidad/riesgo y señal de origen). Sin task si no hay acción.
3. **Idempotencia:** la operación ya es idempotente por `Idempotency-Key`; la creación de la tarea
   debe quedar cubierta por la misma garantía (replay no duplica la tarea).
4. **Visibilidad:** verificar que la tarea aparece en «Siguientes acciones» del Resumen, en la
   pestaña Tareas y en «Trabajo que requiere atención» de Inicio (ya tipificado desde el prompt 23).
5. **Contrato:** regenerar OpenAPI y cliente TS (`api:openapi` → `api:client:generate` →
   `api:client:check` sin drift).

## Criterios de aceptación

- [ ] Promover con acción+fecha+tarea deja: recurso con `next_action`/`mitigation` y `due_date`,
      y una tarea pendiente vinculada visible en Resumen/Tareas/Inicio.
- [ ] Promover sin rellenar los campos nuevos funciona exactamente como hoy.
- [ ] Replay con la misma `Idempotency-Key` no duplica ni recurso ni tarea.
- [ ] Tests backend (promoción con/sin acción, idempotencia con tarea) y frontend (diálogo, envío
      del payload). Suite completa verde.
- [ ] Sin migración nueva (los campos existen). Si algo la exigiera, replantear antes de migrar.

## Despliegue y verificación en producción (obligatorio)

1. CI verde en el commit final.
2. Modo rápido UAT (D-022): backup local + restore aislado (`sudo oracle-control backup` /
   `restore-test`), release inmutable nuevo, `sudo oracle-control update <release-id>`, smoke +
   `oracle-control health`.
3. Verificación funcional autenticada (expediente CATL `292d85e5-3dc1-4c2f-81a5-8a73a29e1fb4`):
   promover una señal con siguiente acción y tarea → comprobar Resumen («Siguientes acciones»
   poblado), Tareas e Inicio. Sin errores de consola.
4. **Verificación extra del release** (arrastra `4fc6acb`): en Actores → «Candidatos detectados»
   del expediente CATL deben aparecer ahora **Stellantis y CATL** (el segundo vía coordinación).
5. Actualizar `docs/implementation/STATUS.md` (release-id, comandos, resultados) y registrar en
   `DECISIONS.md` solo si se toma alguna decisión no trivial.

## No hacer

- No crear tareas automáticas sin acción del usuario.
- No convertir el diálogo en un formulario largo: campos opcionales y compactos.
- No introducir migraciones ni tocar el esquema.
