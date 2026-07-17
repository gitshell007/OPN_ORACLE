# 41 — El grafo se dibuja como una línea diagonal: `randomize: false` sin posiciones iniciales (P1)

> Prompt de corrección para Codex. Regresión detectada en producción (`479f416`) el 2026-07-17 al
> verificar el prompt 39 con `ITURRI SA` (295 nodos, 300 enlaces) desde una sesión autenticada real
> —lo que tú no pudiste hacer—. **El origen está en una sugerencia mal calibrada de mi prompt 39:**
> te pedí replantearte `randomize`, y hacerlo sin más rompe el layout. La responsabilidad del
> diagnóstico es mía; lo que necesito de ti es la solución correcta.

## Lo que sí quedó bien (no lo toques)

- Controles `+`, `−`, `Reencuadrar` e indicador de zoom: funcionan (105% → 58% verificado).
- Cronograma de doble manejador: «300 de 300 vínculos visibles», rango 3/1/2020–17/7/2026, con
  «300 vínculos fechados · 0 sin fecha» y explicación en la interfaz.
- Distinción por color Empresa/Persona: ahora sí se aprecia (antes todo se veía azul).
- Ficha cronológica: **excelente**. Agrupa por año, muestra persona, cargo, acción, fecha,
  provincia y cita BOE, y declara el límite de la fuente sin fingir completitud.

## El fallo

Con `ITURRI SA`, los 295 nodos se dibujan formando **una línea diagonal perfecta** de esquina a
esquina, con las etiquetas superpuestas y sin ninguna estructura visible. No aparece la entidad
central. Se ve igual a cualquier zoom: no es un problema de encuadre, es el layout.

Causa, en `src/components/entity-intel/entity-intel.tsx` (~línea 652):

```js
layout: { name: "fcose", animate: false, fit: false, padding: 42, randomize: false }
```

`randomize: false` le dice a fcose que **parta de las posiciones actuales de los nodos** en vez de
sembrar posiciones aleatorias. Los elementos se añaden sin `position`, así que Cytoscape les asigna
posiciones por defecto degeneradas y el algoritmo de fuerzas no tiene de dónde separarlas: colapsan
en una recta. Es el fallo clásico de fcose con `randomize: false`.

Antes (`randomize: true`) el grafo era una maraña ilegible, pero **bidimensional**. Ahora es
unidimensional: hemos cambiado un problema por otro peor.

## Lo que se pide

El objetivo de fondo sigue siendo válido y no lo retiro: **el mismo grafo debe dibujarse igual
entre visitas**, porque si cada carga da una forma distinta el usuario no puede reconocer nada.
Lo que estaba mal era el medio, no el fin.

`randomize: false` no es la forma de conseguir determinismo: es la forma de conseguir un layout
degenerado. Necesitas darle a fcose un punto de partida **determinista y no degenerado**. Elige y
razona:

- Sembrar posiciones iniciales deterministas antes del layout (por ejemplo, distribuyendo los nodos
  en círculo según un orden estable por identificador) y ejecutar fcose con `randomize: false`
  desde ahí.
- O mantener `randomize: true` y aceptar la variabilidad, documentando por qué el determinismo no
  compensa.
- O cualquier alternativa que consiga las dos cosas; lo que no vale es el estado actual.

**Innegociable:**

- [ ] Con `ITURRI SA` el grafo muestra una estructura bidimensional reconocible, no una recta.
- [ ] La entidad central es identificable en el encuadre inicial.
- [ ] Dos cargas seguidas de la misma entidad producen el mismo dibujo (o se documenta por qué no).
- [ ] Verificado **en el navegador, con datos reales**, no con un harness sintético. Si no tienes
      sesión, dilo y páralo ahí: el harness local del prompt 39 no detectó esto precisamente porque
      no era el entorno real.

## Método: por qué esto se coló

Tu harness local con 295 nodos sintéticos no reprodujo el fallo. Probablemente tus nodos sintéticos
llevaban posiciones, o la distribución de aristas era distinta. **Un fixture con el volumen correcto
no es lo mismo que los datos reales**, y esta es la tercera vez en el proyecto que un fallo solo
aparece con datos de producción (las barras en `folder_id`, el 422 del smoke, y ahora esto).

No te pido que consigas acceso: te pido que, cuando no puedas verificar en real, **lo declares como
no verificado** en vez de aportar capturas de un harness como si fueran equivalentes. Eso fue lo que
me hizo desplegar esta regresión.

## Criterios de aceptación

- [ ] Layout corregido y verificado visualmente con `ITURRI SA` y con una entidad pequeña.
- [ ] Capturas del antes y el después, indicando de dónde salen.
- [ ] Decisión sobre determinismo registrada en `DECISIONS.md`.
- [ ] `npm run lint`, `npm run typecheck`, `npx vitest run` y `npm run build` verdes.
- [ ] Si añades un test, que cubra que el layout no colapsa (p. ej. verificando dispersión de
      posiciones en ambos ejes tras el layout, con Cytoscape mockeado o real en jsdom).

## No hacer

- No toques los controles de zoom, el cronograma ni la ficha: funcionan y están verificados.
- No vuelvas a `fit: true`: eso era el bug original del prompt 39.
- No des el layout por bueno por que «los tests pasan»: este fallo no lo detecta ningún test actual,
  solo mirarlo.
