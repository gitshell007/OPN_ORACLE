# 69 — Patentes: un tope invisible y un fallo que parece «no tiene» (P1)

> Prompt para Codex. **No hay que integrar nada nuevo**: las patentes ya llegan a Oracle y se
> muestran. Lo que hay que arreglar es que, tal como se presentan hoy, pueden inducir a error a un
> analista.
>
> Todo lo que sigue está medido hoy contra producción. No hay que investigar la causa.

## Lo que se ve hoy, medido

Consultando el dossier de entidad de cuatro empresas reales:

| Empresa | `ok` | Patentes que llegan | Total real en EPO | Error |
|---|---|---:|---:|---|
| TELEFONICA SA | true | **25** | **569** | — |
| INDRA SISTEMAS SA | true | 3 | 3 | — |
| ITURRI SA | false | 0 | — | `epo_search_404` |
| ACCIONA SA | false | 0 | — | `epo_search_404` |

De ahí salen los dos problemas.

### Problema 1 — El recorte real no se declara en ninguna parte

Signal devuelve **como máximo 25 patentes por entidad** (límite suyo, confirmado por su equipo).
Para Telefónica eso significa que Oracle ve **25 de 569: un 4 %**.

- **La ficha web no lo dice.** La pestaña «Patentes» pinta la tabla sin nota alguna, mientras que
  la pestaña de CNMV sí lleva una (`note="CNMV: solo hechos recientes disponibles en Signal."`).
  El analista ve 25 filas y no tiene forma de saber que hay 569.
- **El informe de IA lo dice mal.** `source_limits` declara «Oracle solo ha pasado N patentes de M»,
  pero ese M es el total **que le ha llegado** (25), no el real (569). Es decir, puede afirmar
  «20 patentes de 25» cuando la empresa tiene 569, lo que refuerza una falsa sensación de
  exhaustividad en lugar de corregirla.

El dato existe y llega: el payload trae `total` (569 para Telefónica). Solo hay que usarlo.

Esto es exactamente la misma familia de fallo que ya corregimos con el BORME hace unos días: un
corte de la fuente presentado como si fuera un dato de la empresa.

### Problema 2 — «Falló la búsqueda» es indistinguible de «no tiene patentes»

Para ITURRI y ACCIONA, Signal devuelve `ok=false` con `error=epo_search_404`. La ficha, al no haber
elementos, **simplemente no muestra la pestaña**. Para el usuario es idéntico a que la empresa no
tenga ninguna patente.

Y son cosas muy distintas: el 404 de EPO viene de no encontrar ese nombre exacto de solicitante.
ITURRI y ACCIONA son industriales grandes; lo más probable es que sí tengan patentes registradas
con otra grafía («ITURRI, S.A.», el nombre de una filial, etc.), no que no tengan ninguna.

Un analista que consulte ITURRI hoy concluirá «no tiene patentes», y es una conclusión que Oracle
no puede sostener.

## Qué hay que conseguir

1. **Que el recorte se declare donde el usuario lo lee.** Si llegan 25 de 569, tanto la ficha como
   el informe deben decirlo. Usa el `total` que ya viene en el payload; no lo estimes.
2. **Que un fallo de la fuente se distinga de una ausencia real.** Cuando `ok=false`, la ficha debe
   decir que la consulta no se pudo completar —y, si es un `epo_search_404`, que puede deberse a que
   el nombre no coincide con el del solicitante en EPO—. Lo que no puede es callarse y parecer un
   cero.
3. **Que el informe de IA no afirme exhaustividad que no tiene.** Revisa `source_limits` para el
   bloque de patentes: debe reflejar el total real de la fuente, y decir explícitamente que no puede
   inferirse ausencia de patentes a partir de una búsqueda fallida.

No te doy la redacción exacta de los avisos: escríbelos pensando en quién los lee. Una nota que diga
«limit=25» no sirve; una que diga «se muestran 25 de 569 publicaciones» sí.

## Contexto útil que no hace falta que investigues

- La consulta a EPO es **por solicitante exacto**, no por materia. No existe búsqueda de patentes
  por tema desde Oracle, y Signal ha confirmado que tampoco puede ofrecerla hoy por esta vía.
- El tope de 25 es de Signal y **no es configurable desde Oracle**. No intentes subirlo.
- La sección `patents` ya viaja en el dossier y ya la consumen tanto la ficha (pestaña «Patentes»,
  visible solo si hay elementos) como el informe de entidad desde el prompt 59.
- La ficha ya tiene el patrón de nota por pestaña: mira cómo lo hace CNMV y sé coherente.

## Verificación exigida

- Test de que, con un payload de 25 elementos y `total=569`, la ficha muestra el recorte y el
  informe lo declara con el total real.
- Test de que un `ok=false` con `epo_search_404` produce un aviso distinguible de la ausencia de
  patentes, y **no** un estado vacío silencioso.
- Test de que una entidad con 3 de 3 patentes **no** muestra aviso de recorte: un aviso que salta
  siempre deja de leerse.
- **Cada test nuevo verificado por mutación**: di qué mutaste y qué test cayó.
- Frontend: `npm run typecheck`, `npm run lint`, `npx vitest run`, `npm run build`.
- Backend, si tocas `source_limits`: `ruff check`, `ruff format --check`, `mypy src` y la suite con
  integración.
- Verificación en el navegador con sesión real sobre **TELEFONICA SA** (caso de recorte) y sobre
  **ITURRI SA** (caso de fallo), describiendo qué se ve en cada uno.

## Qué NO hacer

- No intentes subir el tope de 25 ni pedir a Signal que lo suba: no es el problema, el problema es
  que no se declara.
- No inventes una búsqueda de patentes por materia: no existe hoy.
- No hagas que la pestaña aparezca siempre. Si una entidad realmente no tiene patentes y la consulta
  fue bien, el comportamiento actual es correcto.
- No toques la integración con EPO ni el cliente de Signal: el dato llega bien, se presenta mal.
