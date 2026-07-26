# 95 — PDF por defecto y writer de actores con allowlist intacta (P0 · reporting + IA)

## Medido

- Prod: `REPORT_PDF_MODE=weasyprint`, WeasyPrint en contenedor genera `%PDF-`.
- Informes ready solo tenían html+json porque el default/UI no pedía pdf.
- Informe de actores con 104 evidencias: el modelo hablaba de IDs vacíos porque
  `_fit_budget` truncaba `allowed_evidence_ids`.

## Alcance

1. Incluir PDF cuando el renderer y la plantilla lo permiten.
2. Proteger allowlist de evidencia en el fit de presupuesto; priorizar evidencia de actores;
   `report_writer` v7 + guidance de plantilla actors.

## Criterio

- Nuevo reintento de actores → ready con artefacto `pdf` y prosa que cite actores/evidencia.
