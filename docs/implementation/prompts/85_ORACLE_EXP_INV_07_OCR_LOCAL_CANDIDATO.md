# Prompt 85 · ORACLE-EXP-INV-07 · OCR local candidato

## Objetivo

Recuperar de forma local y reproducible el texto de los cinco PDF de INV-03 que el
parser nativo clasificó como `ocr_required`, y medirlos con el mismo contrato de
chunks sin confundir transcripción OCR con evidencia nativa.

## Invariantes

- Solo se leen objetos ya revalidados de la cuarentena privada: sidecar, nombre,
  tamaño y SHA-256 deben coincidir antes de renderizar.
- PDF se renderiza con `pdftoppm`; Apple Vision reconoce la imagen localmente con
  `accurate`, `es-ES` y `en-US`. No hay red, Signal ni proveedor externo.
- Cada bloque conserva página, DPI, hash de texto y limitaciones explícitas
  `ocr_text_may_misrecognize` y `candidate_only_human_review_required`.
- Las páginas visualmente vacías no invalidan el PDF, pero no generan texto ni
  afirmaciones. Ninguna salida OCR se promueve automáticamente.
- Cache OCR y resultados reales permanecen bajo `.work` ignorado por Git.

## Gate

El éxito significa únicamente recuperar texto candidato verificable por página. La
calidad OCR no sustituye el gold humano: citas, participantes, roles, precisión y
recall continúan bloqueados hasta la anotación/adjudicación A/B.
