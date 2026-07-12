# 25 — Lote de coherencia y fricciones de UX (P3)

> Lee `18_UX_REMEDIATION_OVERVIEW.md` y las reglas comunes. Severidad **P3**. Son arreglos
> pequeños e independientes; pueden hacerse en un commit lógico o repartirse. Trata cada punto
> como una casilla de aceptación.

## Puntos observados en la auditoría

1. **Scroll reset en Configuración.** Tras crear un monitor, guardar cambios o sincronizar, la
   página salta al inicio de Configuración y el usuario pierde la posición (lista de monitores).
   → Mantener el scroll / hacer scroll al bloque afectado, no al top.
   Código: pestaña Configuración del expediente (settings) y su manejo post-mutación.

2. **Etiqueta del monitor = nombre de conexión.** En la lista de monitores, un monitor creado con
   nombre «Gigafactoría CATL-Stellantis y cadena de baterías» se muestra como **«signal-avanza»**
   (el nombre de la conexión), no por su nombre. → Mostrar el nombre del monitor; usar la conexión
   como dato secundario.

3. **Breadcrumb del expediente sin título.** Al entrar en subpestañas (p. ej. Actores) el
   breadcrumb muestra «Expediente» en vez del título del expediente (deuda ya anotada en STATUS).
   → Resolver el título real en breadcrumbs. Código: shell/navegación de expediente
   (`src/components/navigation/*`).

4. **Fecha de fuente «no disponible».** En el detalle de señal, la evidencia muestra
   «news · Fecha no disponible». → Si Signal Avanza entrega fecha, mapearla; si no, valorar copy
   menos crudo. Verifica el mapeo de ingesta (`integrations/`), sin acoplar a la API concreta.

5. **Señales duplicadas.** En la bandeja global aparecía «CATL defiende su fábrica de baterías en
   España» varias veces (puntuaciones 65, 67, 0) sobre el mismo expediente. → Revisar la
   deduplicación por conexión/ID/hash en la ingesta (`integrations/`, outbox/inbox) y/o la
   presentación; evitar mostrar cuasi-duplicados como entradas separadas dentro de un expediente.

6. **Señales en otro idioma pese al filtro.** Con idiomas `es, en` aparecían señales en chino
   («CATL推出首款现场验证钠离子BESS»). → Verificar que el filtro de idioma del monitor se aplica en
   la ingesta/consulta de Signal Avanza; si el idioma no es fiable, degradar de forma honesta
   (marcar idioma detectado) en vez de colar ruido.

## Reglas

Cada punto necesita, según toque: verificación de causa, fix mínimo, test (frontend y/o backend),
y `api:client:check` si cambia contrato. Los puntos 4–6 tocan la ingesta de Signal Avanza:
respeta `SignalAvanzaAdapter` y no acoples dominio/UI a la API concreta del proveedor; si el
arreglo requiere cambios del lado productor (`opn_signal`), regístralo en `OPEN_QUESTIONS.md` y
acótalo aquí a lo que Oracle controla (mapeo, dedupe de presentación, filtro efectivo).

## Criterios de aceptación

- [ ] Configuración conserva la posición de scroll tras crear/guardar/sincronizar.
- [ ] La lista de monitores muestra el nombre del monitor.
- [ ] El breadcrumb del expediente muestra su título en todas las subpestañas.
- [ ] La fecha de fuente se muestra cuando existe; el copy es honesto cuando no.
- [ ] No se muestran cuasi-duplicados de una misma señal dentro de un expediente.
- [ ] El filtro de idioma del monitor se respeta (o se marca el idioma detectado con honestidad).
- [ ] Tests proporcionales a cada arreglo.

## Verificación

`apps/api`: checks + integración si tocas ingesta. Raíz: `lint typecheck test build`;
`api:client:check` si aplica. Smoke visual de Configuración, detalle de señal y breadcrumbs.
Actualiza `STATUS.md` y, si algo depende del productor Signal, `OPEN_QUESTIONS.md`.

## No hacer

- No acoples la UI/dominio a la API concreta de Signal Avanza.
- No conviertas un cuasi-duplicado real en pérdida de trazabilidad: dedupe de presentación, no de
  datos, salvo que la ingesta esté realmente duplicando registros.
