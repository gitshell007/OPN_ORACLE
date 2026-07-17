# 36 — Idempotency-Key en el informe documental + fidelidad del snapshot fijado (P1)

> Prompt de corrección para Codex. Hallazgos de la auditoría en vivo del 2026-07-17 sobre
> producción (`2ed3edb`), con el flujo completo ejercitado desde la UI autenticada de Vector.
> Independiente del prompt 35 (este toca `packages/api-client` y serialización de snapshots;
> el 35 toca decoradores de entity-intel y `oracle-control`). Coordina el despliegue: si el 35
> aún no se ha activado, un solo release puede llevar ambos.

## Contexto: el informe documental NUNCA ha sido generable

El fix de las barras (`0b5ee58` en Signal + `2ed3edb` en Oracle) funciona de punta a punta,
verificado en producción con la UI real: buscar adjudicaciones de «ITURRI, S.A», fijar
`EMERGENCIACR2026/671` (folder con barra) al expediente de prueba → «Referencia fijada al
expediente», con evidencia creada. Ese tapón ocultaba el siguiente:

Al pulsar **«Informe documental»** la UI muestra:

> «Idempotency-Key debe tener entre 8 y 200 caracteres.»

**Cadena causal, confirmada en código:**

1. `POST /api/v1/dossiers/<id>/procurement/reports` (`apps/api/src/opn_oracle/oracle/routes.py:1580`)
   pasa `request.headers.get("Idempotency-Key", "")` a `create_report_request`.
2. `reporting/service.py:580` rechaza claves de menos de 8 caracteres → 422 con ese mensaje.
   El backend está BIEN: exige idempotencia donde hay riesgo de duplicado (AGENTS.md §6.3).
3. El cliente `createDocumentReport` (`packages/api-client/src/transport.ts:1602`) hace el POST
   **sin** `idempotencyKey`, cuando el transporte ya lo soporta (`RequestOptions.idempotencyKey`,
   línea 144) y otros lo usan: `platform-backup-${Date.now()}` (línea 373).

Como este flujo estuvo siempre bloqueado por las barras, ningún test lo ejercitó end-to-end:
dos bloqueos independientes apilados, y el segundo solo se ve al quitar el primero.

**Fixture ya preparado en producción para verificar:** el expediente «Concurso bomberos»
(`e3519e18-f7f7-4486-9359-8d2ce2f23110`) tiene fijada la adjudicación `EMERGENCIACR2026/671`
(ITURRI S.A, SCIS Ciudad Real, 2 lotes). No lo desfijes: es el caso de prueba.

## Fuentes de verdad

`AGENTS.md` (§6.3 idempotencia, §13 microcopy en español, §16 testing, §20 definición de
terminado), `docs/implementation/STATUS.md`, prompt 35 (en curso). Repo en `master` = `2ed3edb`.

---

## Alcance A — Enviar la Idempotency-Key (el desbloqueo, P1)

1. En `createDocumentReport` (`transport.ts:1602`), envía `idempotencyKey` siguiendo el patrón
   existente (p. ej. `procurement-report-${dossierId}-${Date.now()}`). Ojo al contrato del
   backend: si el usuario reintenta tras un fallo, una clave nueva debe permitir una solicitud
   nueva; si el POST se duplica (doble clic, retry de red), la misma clave debe replay
   (`replayed: true`). Decide dónde generar la clave (por intento de usuario, no por render).
2. **Barrido sistemático**: hay 63 POSTs en `transport.ts` y solo 11 envían clave. Cruza cada
   mutación del cliente contra los endpoints backend que validan `Idempotency-Key` (busca
   `Idempotency-Key` en `apps/api/src`) y corrige los que falten. Documenta en el resumen la
   tabla endpoint → requiere clave → cliente la envía.
3. Test que falle si `createDocumentReport` deja de enviar la cabecera (patrón de
   `api-transport.test.ts:142`).

## Alcance B — Fidelidad del snapshot fijado (datos)

La tarjeta fijada muestra **«Sin fecha»** e **«Importe no publicado»** cuando la búsqueda
mostraba `6/7/2026` y `130.939 €` para la misma adjudicación. El snapshot pierde datos que el
proveedor sí dio. Diagnostica dónde se pierden (¿el lookup por `folder_id` devuelve el
expediente agregado sin fecha/importe por lote, mientras la búsqueda devuelve filas por lote?)
y haz que el snapshot conserve fecha e importe — si hay varios lotes, decide y documenta la
regla (suma de importes, rango de fechas, o desglose por lote).

Relacionado, mismo origen de datos: en la búsqueda de adjudicaciones, dos contratos de
organismos distintos (Renfe Viajeros y Aeropuerto de Teruel) muestran el mismo
**`LOTE A41050113`** — un valor idéntico entre organismos no es un número de lote; parece un
ID (¿de resultado/award?) colándose en el mapeo. Verifica contra el XML CODICE de origen. Si
el fallo está en Signal (serialización), NO lo arregles aquí: documenta el caso exacto en
`docs/implementation/OPEN_QUESTIONS.md` con los dos folder ids afectados para un prompt de
Signal.

## Alcance C — Pulido de la superficie auditada (menor, no bloquea el gate)

- La tarjeta fijada muestra la evidencia como UUID crudo (`6f208b22-…`); usa el formato de
  cita legible ya existente en los informes, o al menos etiqueta y acorta.
- Microcopy en inglés en «Siguientes acciones» del Resumen: `medium`/`high` → español
  (AGENTS.md §13).
- `background_jobs.error_message` genérico («El job no pudo completarse») en fallos
  permanentes: conserva la causa raíz truncada y sin secretos, para que un fallo sea
  diagnosticable sin bucear en logs de Celery.
- Dropdown de sugerencias de adjudicatario: las opciones se pintan como columnas apretadas
  con texto partido; conviértelo en lista vertical legible.
- Grafo de entidad: la leyenda distingue Empresa (azul) / Persona (morado), pero en
  «ITURRI SA» los 295 nodos se ven del mismo color. Comprueba si el estilo por tipo se aplica;
  si resulta que todos los nodos eran empresas, verifica con una entidad que tenga personas
  (cualquier administrador de la pestaña «Órganos y cargos»).

---

## Criterios de aceptación

- [ ] «Informe documental» sobre «Concurso bomberos» ya no devuelve el error de
      Idempotency-Key: encola el job (202) y un segundo POST con la misma clave hace replay.
- [ ] Tabla del barrido idempotencia (endpoint ↔ cliente) en el resumen; mutaciones que la
      requieren, todas cubiertas y con test.
- [ ] El snapshot fijado conserva fecha e importe; regla multi-lote documentada.
- [ ] Hallazgo LOTE: arreglado si es de Oracle; documentado en OPEN_QUESTIONS si es de Signal.
- [ ] Ruff, mypy, pytest, lint/typecheck/test del frontend y build verdes.
- [ ] `STATUS.md` actualizado.

## Despliegue y verificación (obligatorio)

Runbook estándar (backup + restore-test, release inmutable, `oracle-control update`, smoke,
health). Sin migraciones salvo que el Alcance B lo exija — si añade columnas al snapshot,
migración con expand/contract y downgrade documentado.

La verificación que importa, en producción y desde la UI autenticada:

1. Expediente «Concurso bomberos» → Licitaciones → **Informe documental** → el job se encola
   y termina: descarga real de pliegos (máx. 10 / 15 MiB), antivirus, extracción y análisis.
   El informe aparece en la pestaña Informes con sus citas.
2. La tarjeta fijada muestra fecha e importe reales.
3. Si el informe se genera con éxito, **desfija la adjudicación y elimina el informe de
   prueba** (limpieza acordada del test end-to-end); deja constancia en el resumen.

## No hacer

- No toques el backend de idempotencia (`service.py`, `exports.py`): el contrato es correcto.
- No generes la clave por render/componente (rompería el replay por doble clic); por intento.
- No arregles serialización de Signal desde este repo: OPEN_QUESTIONS + prompt aparte.
- No desfijes el fixture antes de que el informe se genere con éxito.
- No mezcles este trabajo con el prompt 35; si ambos están listos, un release conjunto vale,
  pero commits separados y atribuibles.
