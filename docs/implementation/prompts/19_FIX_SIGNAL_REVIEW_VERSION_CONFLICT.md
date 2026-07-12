# 19 — Corregir el choque de versión al revisar señales (P1)

> Lee primero `18_UX_REMEDIATION_OVERVIEW.md` y las reglas comunes. Severidad **P1**: bloquea
> la acción central del inbox de señales.

## Problema observado (evidencia de auditoría)

En una señal recién ingerida, pulsar **«Marcar revisada»** → **Confirmar** devuelve siempre el
error rojo **«La revisión de señal cambió.»** y no completa nunca; la señal permanece en estado
`Nueva`. Reproducido dos veces seguidas sobre la señal «Puesta de la primera piedra en la
gigafactoría de baterías de Stellantis en Figueruelas». Como la promoción a oportunidad/riesgo
exige estado `reviewed`, **este bug bloquea todo el arco señal → acción** (ver prompt 20).

## Causa raíz confirmada

Es un choque de **optimistic concurrency** sobre `DossierSignal.triage_version`:

- Backend `apps/api/src/opn_oracle/oracle/service.py:443` `review_signal_link()`:
  exige `payload["version"]` y en línea ~461 hace `if link.triage_version != expected:
  raise VersionConflict("La revisión de señal cambió.")`. En éxito hace `triage_version += 1`.
- Frontend `src/components/dossiers/dossier-intelligence-section.tsx:306` envía
  `version: Number(link.triage_version) || 0` tomado del objeto **cacheado** en la lista.
- El **triaje asíncrono** (ingesta/`signal_triage`) incrementa `triage_version` por debajo
  después de que la vista cargó la señal. El usuario envía una versión obsoleta → 409 perpetuo,
  porque la UI nunca recarga la versión vigente antes de reintentar.

## Objetivo

Que revisar/descartar una señal funcione de forma fiable aunque el triaje haya avanzado, sin
romper la garantía de concurrencia (no queremos pisar una revisión concurrente real de otra
persona). El backend es correcto; el fallo es de **recuperación en el frontend**.

## Alcance e implementación sugerida

**Frontend (principal)** — `dossier-intelligence-section.tsx` y el cliente
`packages/api-client/src/transport.ts` (`dossierSignals.review`):

1. Al recibir 409/`VersionConflict` en `review`, **refrescar la señal** (re-fetch del link o de
   la lista) para obtener el `triage_version` vigente y su estado, y **reintentar una vez** de
   forma transparente si el estado sigue siendo accionable (`new`/`reviewed`).
2. Si tras el refresco el estado ya cambió de forma incompatible (p. ej. otra persona la
   descartó), mostrar un aviso claro y accionable en español («La señal se actualizó; hemos
   recargado los datos, revisa y confirma de nuevo») en vez del error crudo, y dejar el drawer
   con los datos frescos para reintentar. No dejar al usuario en un callejón.
3. Asegurar que el drawer/lista mantienen `triage_version` sincronizado tras cualquier mutación
   o refresco (evitar volver a servir el objeto cacheado obsoleto).

**Backend (verificar, cambiar solo si procede):**
- Confirmar que `signal_review` (`routes.py:1177`) devuelve un `problem+json` con `code`
  estable y distinguible (p. ej. `version_conflict`) para que el frontend lo trate de forma
  fiable, y que la respuesta incluya el `triage_version` actual para permitir el reintento sin
  una segunda llamada de lectura. Si no lo incluye, añádelo (y regenera OpenAPI/cliente).

## Criterios de aceptación

- [ ] Marcar revisada una señal recién ingerida funciona al primer o segundo intento sin
      intervención manual, y la señal pasa a `Revisada`.
- [ ] Descartar funciona igual.
- [ ] Un conflicto real (dos revisiones concurrentes con cambios distintos) sigue protegido:
      no se pierde silenciosamente la revisión de nadie; se informa y se recargan datos.
- [ ] El mensaje de error crudo «La revisión de señal cambió.» ya no se muestra al usuario como
      estado final sin salida.
- [ ] Test frontend que simula 409 → refetch → reintento con éxito. Test backend/contrato del
      `code` y del `triage_version` en la respuesta de conflicto (si se añadió).

## Verificación

`apps/api`: `make lint && make typecheck && make test` (+ integración si hay `TEST_*`).
Raíz: `npm run lint && npm run typecheck && npm run test && npm run build`; `api:client:check`
si cambió contrato. Smoke Playwright del recorrido señal→revisar. Actualiza `STATUS.md`.

## No hacer

- No elimines la comprobación de versión ni la conviertas en "última escritura gana".
- No muevas la lógica de revisión al frontend.
