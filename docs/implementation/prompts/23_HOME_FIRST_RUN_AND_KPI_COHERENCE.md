# 23 — Inicio: primer arranque y coherencia de KPIs (P2/P3)

> Lee `18_UX_REMEDIATION_OVERVIEW.md` y las reglas comunes. Severidad **P2/P3**.

## Problema observado (evidencia de auditoría)

En `/app` (Inicio):

1. **Muro de ceros:** un tenant/expediente nuevo ve 5 de 7 KPIs a 0 (Expedientes 0,
   Oportunidades 0, Riesgos 0, Reuniones 0, Tareas 0) y bloques «No hay elementos accesibles».
   La primera impresión es de herramienta vacía y defensiva, no del "radar de oportunidades"
   que promete el producto (OPN_Oracle_Codex_Memory.md §7, enfoque ofensivo).
2. **Incoherencia KPI vs. cartera:** «Expedientes activos: 0», pero el bloque
   «Cartera activa · Requieren atención» listaba dos entradas que enlazan a expedientes
   (`/app/dossiers/{uuid}/signals`). El rótulo del bloque es «Ver expedientes» pero las entradas
   se leen como señales (con «Puntuación 67 · Nueva»). El usuario no entiende qué está viendo ni
   por qué el contador dice 0.

## Contexto de código

- `src/components/navigation/product-home.tsx` (líneas ~123–139: «Cartera activa / Requieren
   atención», enlace «Ver expedientes», estados vacíos y `home?.dossier_total`).
- Read model de inicio servido por Flask (`oracle` home/read model). Verifica qué cuenta
  «Expedientes activos» y qué alimenta «Requieren atención».

## Objetivo

Que Inicio comunique valor y guíe la acción desde el primer minuto, y que los contadores y
bloques sean **coherentes** entre sí y con lo que enlazan.

## Alcance e implementación sugerida

1. **Primer arranque (onboarding):** cuando no hay expedientes/datos, sustituir el muro de ceros
   por un estado inicial que invite a la acción (crear el primer expediente, activar vigilancia),
   explicando en una frase qué hará Oracle. Reutiliza el copy honesto ya presente
   (`product-home.tsx:139`) y amplíalo a un onboarding claro.
2. **Coherencia de contadores:** alinear «Expedientes activos» con lo que realmente se muestra.
   Decide y aplica: si «Requieren atención» lista expedientes, el contador y el rótulo deben
   concordar; si lista señales prioritarias, renómbralo y sepáralo del enlace «Ver expedientes».
   Elimina la ambigüedad señal/expediente en ese bloque.
3. **Sesgo ofensivo:** ordenar la jerarquía visual para que «oportunidades/señales que requieren
   atención» pesen más que los contadores en cero (sin ocultar los riesgos).

## Criterios de aceptación

- [ ] Un tenant sin datos ve un onboarding accionable, no un muro de ceros.
- [ ] «Expedientes activos» coincide con lo que el usuario ve; el bloque «Requieren atención» y su
      enlace son coherentes (expedientes o señales, sin mezclar rótulos).
- [ ] Ningún elemento de Inicio enlaza a un destino que contradiga su etiqueta.
- [ ] Tests frontend del estado vacío y del poblado; smoke visual en 1440×900 y 390×844.

## Verificación

Raíz: `npm run lint typecheck test build`; `npm run test:e2e` del recorrido de Inicio. Si el read
model backend cambia, `apps/api` checks + `api:client:check`. Actualiza `STATUS.md`.

## No hacer

- No toques los prototipos `/concept-a`, `/concept-b`.
- No inventes métricas; si un dato no está disponible, dilo con copy honesto.
