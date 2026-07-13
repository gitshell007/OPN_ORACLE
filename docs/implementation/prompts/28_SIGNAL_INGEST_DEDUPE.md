# 28 — Deduplicación de señales por URL/contenido en la ingesta (P2)

> Lee `18_UX_REMEDIATION_OVERVIEW.md` (reglas comunes). **Ejecutar después del prompt 27** (o en el
> mismo ciclo); al terminar, **despliega a producción** con el modo rápido UAT (D-022) y verifica.

## Problema (auditoría en vivo 2026-07-12/13)

La bandeja global y los expedientes muestran **el mismo artículo varias veces**: «CATL defiende su
fábrica de baterías en España» apareció 2 veces en el mismo expediente (puntuaciones 65 y 67) y una
tercera en otro. Cada duplicado genera triaje IA propio (coste), puntuaciones divergentes para el
mismo hecho y ruido que erosiona la confianza en el radar. El prompt 25 consolidó **presentación**
en la bandeja del expediente, pero la **ingesta sigue creando señales duplicadas**.

## Causa (punteros verificados)

`_ingest_item` (`apps/api/src/opn_oracle/integrations/service.py:298`) deduplica solo por:
1. `SignalIngestionRecord` con el mismo `provider_signal_id` por monitor, y
2. `Signal` con el mismo `external_id` por conexión.

Si el proveedor entrega la **misma historia como items distintos** (IDs distintos — p. ej.
encontrada por dos consultas o dos fuentes del monitor), se crean `Signal` y `DossierSignal`
duplicados. No hay dedupe por URL ni por contenido.

## Objetivo

Que una misma historia (misma URL canónica, o mismo título+fuente cuando no hay URL) **no cree una
segunda señal** dentro del mismo tenant+conexión: debe reutilizar la existente conservando
procedencia y contadores, sin fusionar historias realmente distintas.

## Alcance

1. **Clave de dedupe secundaria en ingesta** (en `_ingest_item`, antes de crear una señal nueva):
   - **URL canónica**: normalizar `source_url` (minúsculas en host, sin fragmento, sin parámetros de
     tracking — `utm_*`, `gclid`, `fbclid`, etc., sin barra final). Si existe una `Signal` del mismo
     tenant+conexión con la misma URL canónica → **reutilizarla** (actualizar campos si el contenido
     cambió, como hace hoy la rama `changed`).
   - **Sin URL**: usar título normalizado (casefold, espacios colapsados) + `source_name` como clave
     de respaldo. Solo coincidencia **exacta** normalizada; nada difuso.
2. **Procedencia intacta:** el `SignalIngestionRecord` del item nuevo debe registrarse apuntando a
   la señal reutilizada (occurrence_count/last_seen), de forma que se conserve qué monitor y qué
   sync la trajeron. El enlace `DossierSignal` no debe duplicarse si ya existe para ese expediente.
3. **Almacenar la URL canónica** (columna nueva indexada o índice funcional — decidir; si se añade
   columna, **migración Alembic** con backfill de las señales existentes y sin downtime) para que la
   búsqueda de duplicados sea O(índice), no un scan.
4. **No retro-fusionar**: los duplicados ya existentes en datos UAT pueden quedarse (o limpiarse a
   mano); este prompt solo evita crear nuevos. Documentarlo en STATUS.
5. **Triaje**: al reutilizar una señal existente no debe re-encolarse un triaje IA completo salvo
   cambio real de contenido (mantener el comportamiento actual de la rama `changed`).

## Criterios de aceptación

- [ ] Dos items del proveedor con IDs distintos y la misma URL (con y sin `utm_*`) producen **una**
      señal, dos registros de ingesta y un solo `DossierSignal` por expediente.
- [ ] Dos items sin URL con mismo título normalizado y misma fuente → una señal.
- [ ] Historias distintas con URLs distintas jamás se fusionan; títulos iguales de **fuentes
      distintas** tampoco (la clave de respaldo incluye `source_name`).
- [ ] Cambio real de contenido en la misma URL actualiza la señal y re-encola triaje (rama
      `changed` intacta).
- [ ] Si hay migración: upgrade desde base, `flask db check` sin drift, downgrade documentado.
- [ ] Tests backend de los cuatro casos anteriores + test de integración PG si `TEST_*` disponible.

## Despliegue y verificación en producción (obligatorio)

1. CI verde. Modo rápido UAT (D-022): backup local + restore aislado, release inmutable,
   `sudo oracle-control update`, smoke + health. **Si hay migración**, verificar que el head sube
   exactamente una revisión y registrar el nuevo head en STATUS.
2. Verificación funcional: forzar «Sincronizar» en el monitor del expediente CATL
   (`292d85e5-…/settings`) dos veces; confirmar que la bandeja global no acumula nuevas entradas
   duplicadas de la misma URL y que los contadores de ingesta crecen en la señal existente.
3. Actualizar `docs/implementation/STATUS.md` (release-id, migración si la hay, comandos,
   resultados) y `DECISIONS.md` con la política de canonicalización de URL elegida.

## No hacer

- Nada de matching difuso/semántico (eso sería otra fase, con IA y evidencia).
- No borrar ni fusionar señales existentes en producción.
- No debilitar la idempotencia actual por `provider_signal_id`/`external_id`: la nueva clave es
  **adicional**, no sustituta.
