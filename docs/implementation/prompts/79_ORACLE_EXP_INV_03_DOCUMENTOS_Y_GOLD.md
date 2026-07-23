# Prompt 79 · ORACLE-EXP-INV-03 · documentos, gold y contrato candidato

## Objetivo

Continuar INV-02 sin convertir la salida de Ollama en verdad. La fase debe:

1. sortear antes de observar documentos un core de 24/96 expedientes, tres por cada celda;
2. intentar todas sus referencias documentales bajo límites explícitos;
3. separar cuarentena, antivirus, parsing, inferencia, gold y scoring;
4. producir hojas vacías A/B para doble etiquetado;
5. validar un schema candidato v2 con citas literales por página;
6. conservar todo dato real exclusivamente en `.work`;
7. publicar cobertura técnica y bloqueos, nunca precisión o recall sin gold adjudicado.

## Invariantes

- Un fallo de referencia, descarga, formato, antivirus, parser u OCR permanece en el denominador.
- No se repone un expediente fallido con otro más fácil.
- `document_id` remoto no identifica un objeto: se usa `SHA-256(sample_id + URL exacta)`.
- Solo HTTPS, host+ruta+query allowlisted, DNS público, peer fijado, proxy desactivado y cero
  redirects.
- HTML con estado 200, WAF, MIME, extensión o nombre remoto nunca bastan para admitir bytes.
- Todo fichero queda en cuarentena; el modo interno autorizado registra
  `internal_unscanned_authorized` y revalida tamaño+SHA-256 antes de abrirlo.
- ClamAV no bloquea este benchmark interno por decisión explícita del propietario. La excepción no
  declara el documento limpio ni cambia la política productiva.
- OCR ausente se declara `ocr_unavailable`; Ollama Vision no sustituye gold de OCR.
- Inferencia no puede leer `gold`, `expected` ni la salida del segundo anotador.
- Toda aserción del modelo conserva `needs_human_review=true`.
- `non_awarded_bidder` exige oferta confirmada en el lote y otro adjudicatario.
- Nombre, identificador, lote, rol y miembros UTE requieren citas literales verificables.
- La cita usa página física PDF 1-based y texto normalizado; no fuzzy matching.
- Ninguna salida candidata promueve actores, relaciones, participaciones, evidencias o informes.

## Entregables

- protocolo INV-03;
- adquiridor reanudable y fail-closed;
- packs privados `annotator_a`, `annotator_b` y mapa coordinador separado;
- schema `placsp-participation-candidate/v2`;
- validación determinista de hash, página, literal y soporte de cita;
- smoke sintético adversarial con `qwen3.5:9b`, `think=false`;
- resultado agregado redactado;
- pruebas y mutaciones de los invariantes críticos.

## Gates

El extractor real permanece `NO-GO` hasta disponer de:

- documentos íntegros y autorizados para el contexto de ejecución;
- doble etiquetado y adjudicación;
- cero citas/hash/páginas inválidas;
- cero invenciones críticas;
- corpus suficiente por celda;
- precisión y recall calculados únicamente después de congelar candidatos y gold.
