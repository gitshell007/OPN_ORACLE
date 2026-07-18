# 55 — Área de espera del informe de entidad: no se puede leer antes de incorporar (P1)

> Contexto: el informe IA de entidad ya funciona end-to-end en producción. Genera con
> evidencia citable, se incorpora y materializa 33 evidencias reales ligadas al expediente.
> Lo que falla ahora es el camino que lleva al usuario hasta él: la ficha te pide decidir
> sobre un informe que todavía no puedes leer, y te enseña un mensaje que apunta a otro
> informe distinto. Todo esto es de la ficha de entidad (`/app/actors/entity/...`), no del
> renderizado del informe, que ya está bien.

## 1 — No hay forma de leer el informe antes de incorporarlo

Medido en producción el 2026-07-18 sobre `ITURRI SA`. La tarjeta «Informe IA» de la ficha
tiene exactamente estos controles: `Informe de la entidad` (generar), `Actualizar estado`,
un selector de expediente destino y `Incorporar a expediente`. **No hay ningún «Ver
informe».**

Por diseño (D-035) el informe vive en un área de espera con `dossier_id` NULL y solo se
materializa como `Report` real al incorporarlo. Eso está bien como modelo de datos, pero la
consecuencia en pantalla es que **la única manera de leer el informe es archivarlo antes en
un expediente**. Se le pide al usuario que decida dónde guardar algo cuyo contenido no ha
visto, y esa decisión no es trivial: elegir mal el expediente ensucia la trazabilidad del
expediente equivocado.

Qué hacer: añadir una **previsualización del informe en espera** desde la propia ficha, sin
incorporarlo. Sirve un panel o diálogo que muestre el contenido tal cual ya lo devuelve el
job (`result_ref.output`): resumen ejecutivo, secciones con sus párrafos, y las fuentes
citables de `result_ref.pending_evidence_sources`. No hace falta plantilla nueva: el
renderizado del informe incorporado ya existe y se ve bien; la vista previa puede reutilizar
la misma presentación en modo solo lectura.

Debe quedar claro en la vista previa que es un informe **en espera y aún no incorporado**, y
que las evidencias que cita **todavía no existen** como registros: son IDs reservados que
solo se materializan al incorporar. Es la diferencia entre «esto ya está en el expediente» y
«esto es lo que entraría si lo incorporas», y el usuario tiene que poder distinguirlas.

## 2 — El mensaje «Informe ya incorporado» apunta a un informe viejo

En la misma tarjeta aparecía en verde:

```
Informe ya incorporado a un expediente. Puedes consultarlo en la biblioteca de informes.
```

Estado real de la base de datos en ese momento:

| Generado | Fuentes citables | Incorporado |
|---|---|---|
| 09:07 hoy | 33 | No |
| 08:47 hoy | 33 | No |
| 08:43 hoy | 13 | No |
| 19:26 ayer | **0** | Sí |

Es decir: el mensaje era literalmente cierto —existe *un* informe incorporado— pero
señalaba el de ayer, que es el peor de todos (cero evidencia citable, anterior a todo el
trabajo de citas). Los tres buenos estaban sin incorporar y sin forma de verse. Un usuario
que siga ese mensaje va a la biblioteca, abre el informe malo y concluye que la
funcionalidad no sirve.

Qué hacer: el mensaje debe referirse **al informe actualmente en espera**, no a cualquier
informe histórico de la entidad. Si el informe en espera no está incorporado, el estado debe
decir eso y ofrecer verlo (punto 1). Si el usuario ya lo incorporó, entonces sí enlazar
**a ese informe concreto**, no a la biblioteca en general.

## 3 — Regenerar no funciona: la clave idempotente se reutiliza

Pulsar `Informe de la entidad` dos veces en la misma página devuelve **202 con el job
anterior** en lugar de lanzar uno nuevo, porque la clave `Idempotency-Key` se reutiliza
entre pulsaciones de la misma vista. Visualmente no pasa nada y no hay forma de saber por
qué. Durante la verificación en producción hubo que lanzar los informes por API con una
clave nueva para poder repetir la prueba.

La idempotencia está bien y no hay que quitarla: protege de dobles envíos accidentales. Lo
que falla es que **no se puede regenerar a propósito**. Hay que decidir y dejar explícito el
comportamiento: o la clave se renueva cuando el usuario pide explícitamente un informe nuevo
(y entonces regenerar funciona), o la interfaz dice claramente «ya existe un informe reciente
para esta entidad» y ofrece verlo o forzar uno nuevo. Lo que no vale es un botón que
responde 202 y aparentemente no hace nada.

## 4 — El clic silencioso sigue vivo (relacionado con el 46 y el 53)

Durante toda la verificación en producción, **el primer clic tras navegar se perdía** de
forma sistemática, tanto en `Informe de la entidad` como en `Incorporar a expediente`: hubo
que pulsar dos veces cada vez. Los prompts 46 y 53 no lo han cerrado en estas páginas.

No lo arregles a ciegas aquí si ya hay trabajo en curso en el 53; pero déjalo anotado con
esta evidencia nueva: **se reproduce de forma fiable en la ficha de entidad**, que es una
página pesada (ficha 360º con grafo), así que es un buen sitio para reproducirlo y por fin
cerrarlo. Confirma si es el mismo problema de hidratación que ya se atacó o uno distinto.

## Criterios de aceptación

- Desde la ficha de una entidad con un informe en espera se puede **leer el informe completo
  sin incorporarlo**, y la vista deja claro que está en espera y que sus evidencias aún no
  existen como registros.
- El estado que muestra la tarjeta se refiere al informe en espera actual; si enlaza a un
  informe incorporado, enlaza a **ese** informe, no a la biblioteca genérica.
- Regenerar un informe a propósito funciona, o la interfaz explica por qué no y qué hacer.
  Ningún botón responde 202 sin efecto visible.
- Tests que cubran: informe en espera sin incorporar (se puede previsualizar), informe ya
  incorporado (enlaza al correcto), y entidad sin ningún informe (estado vacío).

## No hacer

- No cambies el modelo del área de espera (D-035): que el informe no sea un `Report` hasta
  incorporarlo es deliberado. El arreglo es de presentación, no de datos.
- No materialices evidencia al previsualizar. La previsualización no debe tener efectos: las
  evidencias solo se crean al incorporar.
- No toques el renderizado del informe ya incorporado ni la plantilla `entity_intelligence`:
  funcionan bien, con procedencia y el panel de fuentes numeradas.
- No quites la idempotencia para arreglar el punto 3.
