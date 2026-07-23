# Prompt 83 · ORACLE-EXP-INV-05 · no complicar schema sin medir

## Objetivo

Continuar INV-04 con una comparación mínima antes de escalar a todo el corpus. La fase debe:

1. probar si un contrato de chunk con varias citas mejora los fallos de `quote_missing` y
   `name_not_in_quote`;
2. revertirlo si empeora schema, validación o latencia;
3. ampliar `chunk/v1` de forma acotada para comprobar estabilidad;
4. publicar solo métricas agregadas, nunca contenido documental ni precision/recall;
5. mantener el bloqueo de promoción automática hasta gold A/B.

## Invariantes

- Más estructura en el schema no se acepta por intuición: se mide contra salidas reales.
- `chunk/v1` sigue siendo el extractor candidato activo mientras supere a alternativas locales.
- Ninguna comparación usa gold ni etiquetas humanas pendientes.
- El resultado solo puede mover decisiones metodológicas, no hechos del dominio.

## Gate

Si una variante empeora schema o validación estructural, se descarta aunque parezca más expresiva.
