# El informe de actores no recibe actores

**Fecha:** 2026-07-24
**Estado:** diagnosticado, sin corregir
**Evidencia:** expediente «Coches de Bomberos», plantilla `actors` v1

## Síntoma

Dos generaciones consecutivas del «Informe de actores · Coches de Bomberos»
fallaron con causas distintas:

| Intento | Hora | Modelo | Resultado |
|---|---|---|---|
| g1-r3 (`4a593606`) | 08:14 | `ollama/qwen3.5:9b` | `sections: []` → rechazado por «no contiene las secciones requeridas» |
| g2-r1 (`86d37f0f`) | 15:13 | `ollama/qwen3.5:9b` | contenido generado → rechazado por el revisor de evidencia |

En el primer intento el modelo acompañó el informe vacío de advertencias
propias: «la confianza en cualquier conclusión derivada de este análisis es
nula hasta que se aporte trazabilidad». Estaba describiendo su propio problema.

## Causa raíz

**El snapshot de contexto que congela `_frozen_report_snapshot`
(`apps/api/src/opn_oracle/reporting/service.py:402`) no incluye actores.**

Las claves que se congelan son: `schema`, `captured_at`, `dossier`, `template`,
`closure_fields_required`, `options`, `objectives`, `hypotheses`,
`living_summary`, `procurement_items`, `evidence`. Verificado en producción
sobre el snapshot real del informe `86d37f0f`: no existe la clave `actors`, ni
`relationships`, ni `opportunities`, ni `risks`.

La plantilla `actors` v1 exige siete secciones que son, todas, sobre actores:

    Mapa de actores · Roles · Influencia · Relaciones confirmadas ·
    Afinidades inferidas · Movimientos recientes · Siguientes acciones

El modelo recibe 103 evidencias sueltas y ningún actor, ningún rol y ninguna
relación. Se le pide un mapa de actores sin darle el mapa.

El agravante: el expediente **sí tiene** los datos que faltan. En base de datos
hay 5 actores vinculados (Iturri, ITURRI SA, Iberdrola SA, TRILLO MARTINEZ
PATRICIA, ITURRI FRANCO JUAN FRANCISCO). Ninguno llega al snapshot.

## Por qué el fallo cambia de forma entre intentos

Ninguno de los dos rechazos es un falso positivo: los dos controles hicieron
exactamente su trabajo sobre un output que no podía ser bueno.

- Sin actores en contexto, el modelo o bien devuelve secciones vacías (intento
  1) o bien redacta afirmaciones que no puede anclar a la evidencia entregada
  (intento 2), y entonces el revisor de evidencia las rechaza con
  `reject_output`.
- La variación entre intentos es ruido de muestreo del modelo sobre el mismo
  contexto insuficiente. No aporta información: el contexto es el mismo.

## Qué NO es el problema

- **No es la validación de headings.** Se relajó hoy (`c418d70`) para aceptar
  paráfrasis de mayúsculas/acentos. Es una mejora legítima, pero no toca este
  caso: el intento 1 no falló por cómo se escribían los títulos, falló porque
  no había secciones.
- **No es (solo) la capacidad del modelo.** Mi hipótesis inicial —mover
  `report_writer` a `gemini-2.5-flash`— habría maquillado el síntoma: un modelo
  más capaz redactaría inferencias mejor formuladas sobre el mismo vacío. La
  consulta a Signal sigue teniendo valor por calidad general, pero no arregla
  esto y no debe presentarse como si lo hiciera.
- **No es falta de evidencia en el expediente.** Hay 103 evidencias congeladas
  en el snapshot. Lo que falta es la capa de actores que las organiza.

## Alcance

Afecta a toda plantilla cuyas secciones dependan de entidades del expediente
que el snapshot no congela. Confirmado en `actors`. A revisar con el mismo
criterio, porque sus contratos declaran entradas que el snapshot tampoco
transporta:

- `opportunity` v1 → `opportunity_id`
- `risk` v1 → `risk_id`
- `meeting_briefing` v1 → `meeting_id`
- `tender` v1 → `opportunity_id`

El contrato de entrada valida los IDs (`service.py:310` comprueba que
`actor_ids` pertenece al expediente) pero **no los resuelve a datos** dentro
del snapshot. Se valida la referencia y se descarta el contenido.

## Dirección de arreglo

Congelar en el snapshot las entidades que las plantillas necesitan, con el
mismo criterio de inmutabilidad y trazabilidad que ya se aplica a la
evidencia:

1. Añadir `actors` al snapshot: identidad canónica, tipo, roles en el
   expediente, relaciones confirmadas y evidencias vinculadas a cada uno.
2. Respetar `actor_ids` / `relationship_scope` del contrato cuando vengan
   informados; sin ellos, incluir los actores del expediente con un tope
   declarado (como ya se hace con las fuentes de evidencia).
3. Declarar el recorte al modelo, igual que `balance_evidence_sources`: si se
   truncan actores o relaciones, decirlo en el contexto en lugar de dejar que
   el modelo infiera ausencia.
4. Resolver el mismo hueco para `opportunity_id`, `risk_id` y `meeting_id`
   antes de dar esas plantillas por operativas.

## Nota sobre el dato de negocio

Los 5 actores del expediente tienen **0 evidencias vinculadas** entre ellos.
Aunque se arregle el snapshot, un informe de actores sobre este expediente
concreto seguirá siendo pobre hasta que se vincule evidencia a los actores
—trabajo de usuario, no de código—. El arreglo del snapshot es condición
necesaria; la vinculación de evidencia es la que da calidad.
