# Prompt 86 · ORACLE-EXP-INV-08 · pack de revisión doble ciego

## Objetivo

Convertir las hojas vacías A/B de INV-03 en un paquete operativo para revisión humana,
sin contaminar el gold con identificadores de muestra, URLs, ganadores estructurados ni
salidas de Ollama.

## Invariantes

- A recibe sus 96 hojas y B las 24 del core. Cada índice usa solo `annotation_id` y
  `source_ref_id` opacos.
- Los objetos disponibles permanecen en cuarentena; el pack no copia, descarga ni altera
  PDF/DOCX. Cada índice declara `available` o `not_acquired` sin inventar un reemplazo.
- La coordinación `sample_id ↔ annotation_id` continúa separada y privada.
- Anotar disponibilidad o ausencia de material no equivale a ausencia de participante.
- Ninguna persona recibe candidato Ollama, etiquetas del otro anotador o ganador estructurado.

## Gate

El resultado es una preparación de revisión, no gold. Gold sigue en cero hasta que A/B
completen sus hojas y un adjudicador humano resuelva desacuerdos y casos ambiguos.
