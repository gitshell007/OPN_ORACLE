# 38 — La lista blanca del snapshot descarta `documents` e `is_ute` (P1)

> Prompt de corrección para Codex. Hallazgo de la prueba end-to-end del informe documental
> ejecutada en producción el 2026-07-17, ya con los prompts 35 y 36 desplegados (`ed8c4f3`).
> El informe **se genera**, pero **sin descargar un solo pliego**: la funcionalidad completa de
> adquisición documental (descarga → antivirus → extracción → análisis) nunca ha llegado a
> ejecutarse ni una vez en la vida del proyecto.

## Contexto: la tercera capa de la cebolla

Tres bugs independientes apilados, cada uno tapando al siguiente:

1. **Barras en `folder_id`** (`0b5ee58`/`2ed3edb`): era imposible fijar el 69% de las
   adjudicaciones. Nadie llegaba al botón.
2. **Idempotency-Key ausente** (`0087c49`): el botón devolvía 422 siempre. Nadie llegaba al job.
3. **Este:** el job corre, termina `succeeded`, el informe queda `ready`… y descarga cero PDF.

Verificado en producción el 2026-07-17 con la adjudicación `EMERGENCIACR2026/671` (ITURRI S.A,
SCIS Ciudad Real) fijada al expediente «Concurso bomberos»:

- `background_jobs`: `oracle.procurement_document_report.generate` → **succeeded**.
- `reports`: informe `812bf0d8-…` → **ready**, con contenido real y evidencia citada.
- `documents`: **0 filas**. Volumen `/var/lib/oracle-storage`: **48K**.
- El propio informe lo dice: «La documentación detallada de la licitación no está disponible en el
  contexto actual.»

**Causa raíz, confirmada consultando a Signal en vivo desde el contenedor de la API:**

```
# Lo que Signal DEVUELVE para EMERGENCIACR2026/671:
claves item: [award_amount, award_date, buyer, cpv, documents, folder_id,
              is_ute, lot_id, region, source_url, status, title, winner]
documents: [{'uri': 'https://contrataciondelestado.es/FileSystem/servlet/GetDocumentByIdServlet?...',
             'file_name': '', 'doc_type': 'l...

# Lo que Oracle GUARDA en el snapshot:
claves entry: [cpv, kind, buyer, title, lot_id, region, status, winner,
               folder_id, award_date, source_url, award_amount]
```

`_snapshot()` (`apps/api/src/opn_oracle/oracle/procurement_items.py:97`) copia campos mediante una
**lista blanca explícita** de claves. `documents` **no está en ella**, así que los enlaces se
descartan al fijar. Y `procurement_report.py:109` lee exactamente eso:

```python
for document in entry.get("documents", []) if isinstance(entry, dict) else []:
```

`_referenced_documents()` devuelve siempre `[]`, `_ingest_documents()` sale de inmediato, y no se
descarga nada. Nunca. El informe se genera solo con los metadatos de la adjudicación.

**Y hay un segundo campo caído en la misma trampa:** `is_ute` aparece **cero veces** en
`procurement_items.py`, tampoco está en la lista blanca. Pero la UI lo lee
(`snapshotIsUte` en `src/components/dossiers/dossier-procurement-section.tsx:55` comprueba
`item.snapshot.is_ute` y `entries[].is_ute`) y `STATUS.md:25` afirma que Vector muestra el
distintivo «UTE · En consorcio» «tanto en Actores como en las adjudicaciones fijadas al
expediente». En Actores funciona, porque lee de Signal en vivo. **En las adjudicaciones fijadas no
puede funcionar jamás**, porque el campo no llega al snapshot. La documentación declara terminado
algo que el código no puede hacer.

## Fuentes de verdad

`AGENTS.md` (§9 evidencia, §12 IA, §16 testing, §20 definición de terminado),
`docs/integrations/signal-avanza/CONTRACT_V1.md` (contrato del snapshot),
`docs/implementation/STATUS.md`. Repo en `master` = `ed8c4f3`, desplegado y verde.

---

## Alcance A — Que los campos que Signal da lleguen al snapshot

Añade `documents` e `is_ute` a la lista blanca de adjudicaciones en `_snapshot()`. Ojo con
`documents`: es una lista de objetos, no un escalar, así que decide y documenta:

- **Qué se conserva de cada documento** (`uri`, `doc_type`, `file_name`…). El `file_name` puede
  venir vacío, como en el caso real citado: no asumas que existe.
- **Un límite duro de tamaño**: el snapshot es JSONB y se guarda por cada adjudicación fijada. Una
  adjudicación con decenas de lotes y decenas de documentos cada uno puede inflarlo. Acota y di
  cuánto.
- **Normalización**: si el mismo documento aparece en varios lotes, decide si se deduplica.

**No cambies el contrato de Signal ni el orden de los campos existentes.** Actualiza
`CONTRACT_V1.md` para reflejar que el snapshot conserva ahora estos dos campos.

## Alcance B — Que la lista blanca no vuelva a comerse un campo en silencio

Este bug y el de `is_ute` son el mismo fallo dos veces: un campo que el proveedor da, que el
consumidor espera, y que una lista blanca intermedia descarta **sin que nada avise**. Volverá a
pasar en cuanto Signal añada un campo nuevo.

No impongo la solución; quiero tu criterio razonado sobre cómo cerrar la clase entera de fallo.
Opciones que veo:

- Un test de contrato que compare las claves que devuelve el fixture de Signal con las que
  conserva el snapshot, y falle si aparece una clave nueva no clasificada explícitamente como
  «conservada» o «descartada a propósito».
- Invertir la lista: guardar todo salvo una lista negra de campos ruidosos o sensibles.
- Registrar (log, no error) las claves descartadas al fijar, para que se vean en producción.

Exijo, sea cual sea la solución:

- [ ] Un test que **falle hoy** si se quita `documents` o `is_ute` de la lista blanca.
- [ ] Un mecanismo que detecte una clave nueva del proveedor que nadie ha clasificado.
- [ ] La decisión registrada en `DECISIONS.md`.

## Alcance C — Corregir la documentación que miente

`STATUS.md:25` afirma que el distintivo UTE funciona en las adjudicaciones fijadas. Es falso desde
que se escribió. Corrígelo con el estado real y, si tras el Alcance A pasa a ser cierto, dilo
entonces — no antes.

---

## Criterios de aceptación

- [ ] Una adjudicación recién fijada conserva `documents` e `is_ute` en el snapshot.
- [ ] El informe documental de `EMERGENCIACR2026/671` **descarga pliegos reales**: filas en
      `documents`, antivirus ejecutado, texto extraído y citado en el informe con evidencia.
- [ ] El distintivo «UTE · En consorcio» aparece en una adjudicación fijada que sea UTE.
- [ ] Existe protección contra la pérdida silenciosa de campos futuros (Alcance B).
- [ ] Ruff, mypy, pytest, lint/typecheck/test del frontend y build verdes. **Ejecútalos**: si tu
      entorno no tiene `uv`, dilo y no afirmes que pasan (ver prompt 37, Alcance C).
- [ ] `STATUS.md` y `CONTRACT_V1.md` dicen la verdad.

## Verificación end-to-end (obligatoria, en producción)

El fixture está preparado: expediente «Concurso bomberos»
(`e3519e18-f7f7-4486-9359-8d2ce2f23110`) con `EMERGENCIACR2026/671` fijada. **Hay que desfijarla y
volver a fijarla** para que el snapshot se regenere con los campos nuevos: los snapshots viejos no
se migran solos, y por eso esa tarjeta sigue mostrando «Sin fecha» e «Importe no publicado» pese al
arreglo del prompt 36 — dato que el informe sí encontró («290.372,77 EUR», «6 de julio de 2026»)
porque lo leyó de `entries`.

Después: generar informe y comprobar que **esta vez sí** baja los PDF (máx. 10 / 15 MiB), pasa el
antivirus, extrae texto y lo cita. Al terminar, desfijar y borrar el informe de prueba.

## No hacer

- No amplíes los límites de descarga (10 documentos / 15 MiB): son deliberados.
- No metas los binarios de los documentos en el snapshot: solo enlaces y metadatos.
- No des por bueno un informe `ready` sin comprobar que `documents` tiene filas: es exactamente el
  falso positivo que dejó este bug oculto tras otros dos durante semanas.
- No migres snapshots antiguos en este prompt; si crees que hace falta, anótalo en
  `OPEN_QUESTIONS.md` con el coste estimado.
