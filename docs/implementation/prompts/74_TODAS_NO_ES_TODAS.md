# 74 — «Todas» no es todas: verdad temporal en licitaciones (P0 · contrato)

> Prompt de producto para Codex, **backend + frontend + propuesta de contrato a Signal**.
> Es la fase P0 del plan de búsqueda de licitaciones: antes de construir ningún wizard, la
> plataforma tiene que decir la verdad sobre qué ámbito temporal muestra y qué cobertura tiene.
> Todo lo citado abajo está leído hoy en el código con archivo y línea. Lo que exija producción
> o la API real de Signal, verifícalo con sesión/credenciales reales; si no puedes, decláralo
> como no verificado en vez de asumirlo.

## 1 — El filtro «Todas» devuelve solo activas, y está medido de punta a punta

La cadena completa del bug:

1. El frontend define `type ActiveFilter = "" | "true" | "false"` y ofrece
   `<option value="">Todas</option>` (`src/components/procurement/procurement-workspace.tsx`,
   líneas 47 y 738). Con `""` envía `active: undefined`, es decir, **omite el parámetro**
   (líneas 227-230).
2. Flask declara `active = Boolean(load_default=True)` en `TendersQuerySchema`
   (`integrations/procurement_routes.py:85`). La omisión se convierte en `true`.
3. El handler siempre reenvía un booleano: `active=bool(query_data["active"])`
   (`procurement_routes.py:294`), y el cliente lo incluye siempre hacia Signal
   (`integrations/procurement.py:269`).

Resultado: el usuario elige «Todas» y recibe solo licitaciones activas, sin ningún aviso.
Es peor que no tener el filtro, porque afirma un ámbito que no sirve.

Dato que te facilita el arreglo: `_clean_params` (`procurement.py:45-60`) **ya descarta los
valores `None`** antes de llamar a Signal. Si el schema pasa a
`Boolean(load_default=None, allow_none=True)` y el handler propaga `None`, el parámetro
simplemente no viaja. La fontanería existe; lo que falta es el contrato.

**Antes de dar el arreglo por bueno, mide qué hace Signal** (`GET api/v1/registry/tenders`)
cuando `active` no llega. Hay tres desenlaces y cada uno tiene su salida honesta:

- Devuelve el corpus completo → el arreglo del schema basta; añade test y cierra.
- Devuelve solo activas (omisión = activas implícitas) → «Todas» es hoy **imposible** desde
  Oracle. Retira la opción de la interfaz o desactívala con explicación visible, y registra la
  capacidad como dependencia del contrato v2 (sección 4). No la simules.
- Error → igual que el caso anterior, más el detalle del error en la propuesta de contrato.

Lo que no vale, bajo ningún desenlace: lanzar dos peticiones (activas + no activas) y
fusionarlas en Oracle presentando el resultado como un conjunto ordenado. Es exactamente el
orden global fingido que prohíbe D-043.

## 2 — `active: bool` se queda corto: propone `scope` y estado canónico

Un booleano no puede expresar «activas | históricas | todas», y el plan de búsqueda aprobado
necesita las tres. En la API de Oracle:

- Añade `scope = active | historical | all` a `TendersQuerySchema`, manteniendo `active` como
  alias deprecado durante la transición (decide y documenta el plazo). `scope` se traduce hoy
  a lo que Signal entienda (`active=true`, `active=false`, omisión si la sección 1 lo
  demuestra viable); lo que Signal no soporte se declara como no disponible, no se aproxima.
- Cada item de resultado debe exponer un **estado canónico**: `open | closed | awarded |
  cancelled | unknown`. Primero mide qué campos trae hoy un item real de Signal (captura uno
  en producción y documéntalo en el prompt de cierre): si el estado no viene o no es mapeable,
  el valor es `unknown`, y `unknown` se muestra en la interfaz como «Estado no confirmado por
  la fuente» en gris — nunca se rellena por inferencia. El patrón es el de D-044: la ausencia
  de dato es un estado visible, no un hueco a tapar.
- Rangos de fechas: hoy solo existe `deadline_before` (`procurement_routes.py:78-82`) y
  `AwardsQuerySchema` no tiene **ningún** filtro temporal (líneas 48-61). Define en el schema
  de Oracle `published_from/to`, `deadline_from/to` y `awarded_from/to`, propágalos solo si
  Signal los acepta, y los que no, decláralos en la propuesta de contrato v2. La interfaz solo
  ofrece los rangos que funcionan de verdad.

Si tocas la API: regenera OpenAPI y el cliente TypeScript, como siempre.

## 3 — Mide la cobertura histórica real antes de prometerla

Una comprobación previa documentada sobre ITURRI encontró **1.251 adjudicaciones** pero **0 de
30** referencias probadas resolvían la licitación original. Adjudicaciones históricas no
equivalen a archivo de pliegos. Este prompt debe dejar la cobertura medida, no supuesta:

- Explota `GET /api/v1/procurement/stats`: el schema ya declara `placsp_awards` y
  `placsp_open_tenders` como dicts opacos (`procurement_routes.py:167-168`). Captura su
  contenido real y documenta qué dicen de volumen, antigüedad (`oldest`/`newest`) y fuentes.
- Reproduce la auditoría de resolución: toma una muestra de adjudicaciones (sirve la propia
  ITURRI u otra empresa con volumen), distribuida por años, e intenta resolver cada referencia
  con `tender_by_folder` (`procurement.py:278`). Registra el porcentaje de resolución por año.
- Escribe el resultado en `docs/integrations/signal-avanza/` como informe de cobertura con
  fecha: por año, fuente y estado. Ese documento es el que decidirá si la vista histórica del
  futuro buscador se construye alrededor de **adjudicaciones** (existen) o de pliegos (no
  demostrados).

## 4 — Propuesta de contrato v2 a Signal, por escrito

Todo lo que Signal no soporte hoy no se pierde: se convierte en una propuesta de contrato
formal en `docs/integrations/signal-avanza/` (junto a `CONTRACT_V1.md`), con la misma regla
que ya usa el contrato vigente: **Signal declara sus capacidades; Oracle no las presume**.
Contenido mínimo de la propuesta:

- Semántica de la omisión de `active` o parámetro `scope` explícito.
- Campo de estado canónico por item, con vocabulario cerrado.
- Rangos temporales de publicación, cierre y adjudicación en tenders y awards.
- Ordenación server-side (heredada de D-043, sigue pendiente).
- Declaración de cobertura histórica en `stats` (años, fuentes, resolución de pliegos).

Registra además la decisión en `docs/implementation/DECISIONS.md` (siguiente número libre):
qué puede afirmar Oracle hoy sobre el ámbito temporal, qué queda delegado al contrato v2 y la
postura award-céntrica para el histórico mientras los pliegos no estén demostrados.

## Verificación exigida

- Test de ruta que reproduzca el bug: petición sin `active` → el mock de Signal (transport
  httpx de test, patrón ya usado en la suite) **no** debe recibir el parámetro tras el
  arreglo, y sí recibía `active=true` antes. Di qué mutaste para validar el test y qué cayó.
- Tests del mapeo `scope` → parámetros hacia Signal, incluidos el alias deprecado `active` y
  el rechazo de valores inválidos.
- Test del estado canónico: item con estado mapeable, item sin estado → `unknown`.
- **Cada test nuevo verificado por mutación**: di qué mutaste y qué test cayó.
- `ruff check`, `ruff format --check`, `mypy src`, suite completa con integración, y
  regeneración de OpenAPI + cliente TypeScript, nombrados por separado.
- Si tocas el frontend: `npm run typecheck`, `npm run lint`, `npx vitest run`,
  `npm run build`, y verificación visual en `/app/procurement` con sesión real describiendo
  el antes y el después del filtro de ámbito.
- La medición de Signal en producción (sección 1 y 3) con fecha y valores crudos capturados;
  si no hay credenciales, cada punto queda declarado como no verificado, nunca asumido.

## Qué NO hacer

- No fusiones dos llamadas para fabricar «Todas» ni presentes una página ordenada como orden
  global: D-043.
- No construyas un índice o copia local del corpus PLACSP en Oracle: D-028, Signal es el
  productor autoritativo.
- No inventes estados canónicos por heurística cuando la fuente no los da: `unknown` es un
  resultado correcto y visible.
- No presentes cobertura histórica no medida como completa, ni escondas la parcial: el patrón
  es D-044 (aviso con valores exactos, no ocultación ni exageración).
- No empieces el wizard de búsqueda, el perfil de empresa ni la taxonomía CPV: este prompt es
  solo contrato y verdad temporal. El wizard llega en el siguiente y depende de que esto esté
  cerrado.
