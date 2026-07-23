# Prompt 77 · ORACLE-EXP-INV-02 — Marcos, muestras y concordancia

## Objetivo

Convertir el siguiente gate de ORACLE-EXP-INV-01 en marcos reproducibles antes de crear producto:

- challenge set PLACSP de 96 unidades, separado por familia alojada/agregada;
- challenge set BORME de 72 aserciones difíciles;
- muestra de artículos BORME independiente del extractor para medir recall;
- comparador Signal efímero, GET-only y sin reutilizar credenciales productivas.

## Corrección metodológica previa

El protocolo v1 queda conservado como resultado de INV-01, pero no se ejecuta literalmente. INV-02
publica v1.1 porque:

- una revisión o un lote no son observaciones independientes;
- alojada y agregada tienen contratos de publicación distintos;
- los casos raros seleccionados por el parser no estiman prevalencia ni recall;
- el sumario BORME contiene documentos y artículos, no relaciones tipadas;
- Signal v1 no transporta revisión y solo indexa la familia alojada.

## Alcance

1. Congelar bytes, hashes, fecha de adquisición y versión del algoritmo.
2. Deduplicar PLACSP por colección+`entry/id`, conservando la última revisión al corte.
3. Seleccionar como máximo un lote por expediente en el core y mantener challenge sets separados.
4. Seleccionar artículos BORME al azar antes de ejecutar detectores de actos.
5. Generar ledgers locales de anotación, sin versionar nombres ni textos reales.
6. Comparar Signal después del sorteo y con denominadores separados por familia.
7. Emitir resultado honesto: completitud del marco, celdas factibles, datos pendientes de gold y
   bloqueos contractuales.

## Límites vinculantes

- No investigar una empresa o persona semilla.
- No crear filas de dominio, endpoints, migraciones, jobs o task keys.
- Todo corpus real, texto, nombre y respuesta Signal queda bajo `.work/77`.
- Los artefactos versionados contienen solo hashes, conteos, fechas, flags no personales y
  decisiones.
- `counterpart_kind` no se promueve desde mayúsculas, forma del nombre o juicio de Ollama.
- Un detector puede proponer candidatos BORME, pero no producir el gold con el que se evalúa.
- Ningún error HTTP, falta de credencial o ausencia de contrato se convierte en cero observado.
- No se reutilizan `SIGNAL_AI_API_KEY` ni `SIGNAL_AVANZA_API_KEY`.

## Definición de terminado

- Protocolo v1.1 y codebook ejecutable.
- Fixtures sintéticos y pruebas de deduplicación, sorteo, secreto, allowlist y denominadores.
- Manifest redacted reproducible de los marcos adquiridos.
- Ledger real local listo para doble etiquetado.
- Medición de lo observable sin afirmar que el etiquetado humano pendiente ya ocurrió.
- Mutaciones de invariantes demostradas y suites ejecutadas.
