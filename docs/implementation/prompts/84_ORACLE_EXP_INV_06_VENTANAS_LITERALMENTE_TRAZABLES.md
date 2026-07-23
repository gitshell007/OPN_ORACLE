# Prompt 84 · ORACLE-EXP-INV-06 · ventanas literalmente trazables

## Objetivo

Medir una alternativa determinista a los chunks de 3.000 caracteres de INV-04 sin
cambiar el schema `placsp-participation-chunk/v1`: ventanas más pequeñas, tomadas
literalmente de la misma página alrededor de vocabulario de participación.

## Invariantes

- Cada ventana es un substring exacto de una página física, con SHA-256 y página
  propios; no se reconstruyen tablas ni se normaliza contenido para el modelo.
- El contrato, la validación de citas, el merge determinista y la revisión humana
  obligatoria no cambian.
- Las pasadas posteriores reutilizan exclusivamente objetos de cuarentena cuyo
  sidecar, tamaño y SHA-256 se revalidan antes de parsear. No descargan de nuevo.
- La comparación no usa gold, no estima precisión/recall y no promueve candidatos.
- No hay cambios de runtime productivo ni de Signal Avanza.

## Gate

La variante solo sustituye a `chunk/v1` como entrada por defecto si, con presupuesto
comparable, no empeora schema o merge final y reduce de forma observable los rechazos
`quote_missing` y `name_not_in_quote`. Si no supera ese umbral, queda como herramienta
de diagnóstico y `chunks` continúa siendo la estrategia activa.
