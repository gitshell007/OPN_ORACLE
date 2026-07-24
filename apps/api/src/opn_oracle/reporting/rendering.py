"""Safe report rendering without network or arbitrary HTML input."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol, cast

from opn_oracle.ai.schemas import ReportOutput


class ReportRenderError(RuntimeError):
    pass


class PDFRenderer(Protocol):
    enabled: bool

    def render(self, html_document: bytes, *, max_bytes: int) -> bytes: ...


class DisabledPDFRenderer:
    """Explicit fail-closed adapter; it never returns fake PDF bytes."""

    enabled = False

    def render(self, html_document: bytes, *, max_bytes: int) -> bytes:
        del html_document, max_bytes
        raise ReportRenderError("La generación PDF no está habilitada.")


def _forbid_external_fetch(url: str, *args: Any, **kwargs: Any) -> Any:
    """WeasyPrint url_fetcher that rejects every request.

    render_report_html already forbids external references, so any fetch here
    means the sanitization was bypassed; failing loudly beats fetching.
    """

    del args, kwargs
    raise ReportRenderError(f"Referencia externa bloqueada durante el render PDF: {url}")


class WeasyPrintPDFRenderer:
    """Isolated renderer: pure-Python layout engine, no browser, no network.

    It only ever receives the strict HTML produced by render_report_html
    (model text is escaped, external references rejected), and the fetcher
    above turns any residual remote reference into a hard error.
    """

    enabled = True

    def render(self, html_document: bytes, *, max_bytes: int) -> bytes:
        # Import lazily: weasyprint drags native libs (pango/cairo) that only
        # the API/worker images install; tooling contexts must not need them.
        from weasyprint import HTML  # type: ignore[import-untyped]

        pdf = cast(
            "bytes | None",
            HTML(
                string=html_document.decode("utf-8"),
                url_fetcher=_forbid_external_fetch,
            ).write_pdf(),
        )
        if pdf is None or not pdf.startswith(b"%PDF-"):
            raise ReportRenderError("El renderer PDF no produjo un documento válido.")
        if len(pdf) > max_bytes:
            raise ReportRenderError("El PDF del informe supera el límite permitido.")
        return pdf


@dataclass(frozen=True, slots=True)
class RenderContext:
    report_id: str
    version: int
    generated_on: date
    confidentiality_label: str
    template_label: str


PRINT_CSS = """
@page {
  size: A4; margin: 24mm 18mm 22mm;
  @bottom-left { content: string(doc-confidentiality); color: #52657a; font-size: 7.5pt;
    font-family: Arial, Helvetica, 'DejaVu Sans', sans-serif; }
  @bottom-right { content: "Página " counter(page) " de " counter(pages); color: #52657a;
    font-size: 7.5pt; font-family: Arial, Helvetica, 'DejaVu Sans', sans-serif; }
  @top-right { content: string(doc-title); color: #8296ab; font-size: 7.5pt;
    font-family: Arial, Helvetica, 'DejaVu Sans', sans-serif; }
}
@page :first { @top-right { content: none; } }
* { box-sizing: border-box; }
body { color: #15263b; font-family: Arial, Helvetica, 'DejaVu Sans', sans-serif;
  font-size: 10pt; line-height: 1.55; }
header { border-bottom: 2.5pt solid #145b8c; margin-bottom: 22px; padding-bottom: 12px; }
header .meta:first-child { text-transform: uppercase; letter-spacing: 0.09em; font-size: 8pt;
  color: #145b8c; font-weight: bold; }
h1 { font-size: 22pt; line-height: 1.18; margin: 8px 0 10px; color: #0d1c30;
  string-set: doc-title content(); }
header > p { font-size: 10.5pt; color: #33475e; margin: 0 0 10px; }
header .meta:last-child { display: inline-block; border: 0.75pt solid #b9c7d7;
  border-radius: 3pt; padding: 2pt 7pt; string-set: doc-confidentiality content(); }
nav { margin: 0 0 26px; padding: 12px 16px; background: #f4f8fc; border-radius: 4pt;
  page-break-inside: avoid; }
nav strong { display: block; text-transform: uppercase; letter-spacing: 0.09em;
  font-size: 8pt; color: #145b8c; margin-bottom: 6px; }
nav ol { margin: 0; padding-left: 18px; }
nav li { margin: 2pt 0; font-size: 9.5pt; }
nav a { color: #15263b; text-decoration: none; }
nav a::after { content: leader('.') " " target-counter(attr(href), page); color: #52657a; }
h2 { border-bottom: 1pt solid #cbd7e4; font-size: 14pt; margin: 26px 0 10px;
  padding-bottom: 5px; color: #10395c; page-break-after: avoid; }
.meta, .claim-meta { color: #52657a; font-size: 8.5pt; }
.claim { border-left: 2.5pt solid #7a8da3; background: #fafbfd; border-radius: 0 3pt 3pt 0;
  margin: 9px 0; padding: 7px 11px; page-break-inside: avoid; }
.claim p { margin: 0 0 4pt; }
.claim.fact { border-color: #145b8c; }
.claim.inference { border-color: #9a6900; background: #fdfbf6; }
.claim.recommendation { border-color: #26734d; background: #f7fbf9; }
.claim.decision { border-color: #70478a; background: #fbf9fd; }
.claim-meta { text-transform: uppercase; letter-spacing: 0.05em; font-size: 7.5pt; }
.claim-meta a { color: #145b8c; text-decoration: none; }
.sources { border-top: 1pt solid #cbd7e4; margin-top: 30px; padding-top: 14px; }
.sources ol { padding-left: 18px; }
.sources li { margin: 4pt 0; font-size: 9pt; }
.sources li strong { color: #10395c; }
a { color: #145b8c; text-decoration: underline; }
footer { color: #52657a; font-size: 7.5pt; margin-top: 34px; border-top: 0.75pt solid #e0e7ef;
  padding-top: 8px; }
@media print { a { color: #15263b; } }
""".strip()


def _text(value: Any, *, limit: int = 8000) -> str:
    return html.escape(str(value)[:limit], quote=True)


# Las clases CSS conservan el kind original; solo se traduce el texto visible.
CLAIM_KIND_LABELS = {
    "fact": "Hecho",
    "inference": "Inferencia",
    "recommendation": "Recomendación",
    "decision": "Decisión",
}


def render_report_html(
    output_payload: dict[str, Any], context: RenderContext, *, max_bytes: int
) -> bytes:
    """Render a strict schema; model content never becomes markup or a remote URL."""

    output = ReportOutput.model_validate_json(
        json.dumps(output_payload, ensure_ascii=False, default=str)
    )
    parts = [
        '<!doctype html><html lang="es"><head><meta charset="utf-8">',
        f"<title>{_text(output.title, limit=500)}</title><style>{PRINT_CSS}</style></head><body>",
        "<header>",
        f'<div class="meta">{_text(context.template_label)} · '
        f"versión {context.version} · {context.generated_on.isoformat()}</div>",
        f"<h1>{_text(output.title, limit=500)}</h1>",
        f"<p>{_text(output.executive_summary)}</p>",
        f'<div class="meta">Clasificación: {_text(context.confidentiality_label)}</div>',
        '</header><nav aria-label="Tabla de contenidos"><strong>Contenido</strong><ol>',
    ]
    for index, section in enumerate(output.sections, start=1):
        parts.append(f'<li><a href="#section-{index}">{_text(section.heading, limit=500)}</a></li>')
    parts.append("</ol></nav>")
    for index, section in enumerate(output.sections, start=1):
        parts.append(f'<section id="section-{index}"><h2>{_text(section.heading, limit=500)}</h2>')
        for paragraph in section.paragraphs:
            citations = " ".join(
                f'<a href="#evidence-{evidence_id}">[{_text(evidence_id)}]</a>'
                for evidence_id in paragraph.evidence_ids
            )
            kind_label = CLAIM_KIND_LABELS.get(paragraph.kind, paragraph.kind.title())
            parts.extend(
                (
                    f'<div class="claim {_text(paragraph.kind, limit=30)}">',
                    f"<p>{_text(paragraph.text)}</p>",
                    f'<div class="claim-meta">{_text(kind_label)} · '
                    f"confianza {paragraph.confidence}/100 {citations}</div></div>",
                )
            )
        parts.append("</section>")
    parts.append('<section class="sources"><h2>Fuentes y evidencias</h2>')
    if output.source_index:
        parts.append("<ol>")
        for source in output.source_index:
            parts.append(
                f'<li id="evidence-{source.evidence_id}"><strong>'
                f"{_text(source.label, limit=1000)}</strong>"
                f" — {_text(source.locator, limit=2000)}</li>"
            )
        parts.append("</ol>")
    else:
        parts.append('<p class="meta">Esta versión no cita fuentes externas.</p>')
    parts.extend(
        (
            "</section>",
            f"<footer>OPN Oracle · report {context.report_id} · versión {context.version} · "
            f"{_text(context.confidentiality_label)}</footer></body></html>",
        )
    )
    rendered = "".join(parts).encode("utf-8")
    if len(rendered) > max_bytes:
        raise ReportRenderError("El HTML del informe supera el límite permitido.")
    lowered = rendered.lower()
    if any(marker in lowered for marker in (b"<img", b"<iframe", b" src=", b"@import", b"url(")):
        raise ReportRenderError("El informe contiene una referencia externa no permitida.")
    return rendered
