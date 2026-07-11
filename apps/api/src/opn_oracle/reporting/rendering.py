"""Safe report rendering without network or arbitrary HTML input."""

from __future__ import annotations

import html
import json
from dataclasses import dataclass
from datetime import date
from typing import Any, Protocol

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


@dataclass(frozen=True, slots=True)
class RenderContext:
    report_id: str
    version: int
    generated_on: date
    confidentiality_label: str
    template_label: str


PRINT_CSS = """
@page { size: A4; margin: 22mm 18mm 20mm; }
* { box-sizing: border-box; }
body { color: #15263b; font-family: Arial, Helvetica, sans-serif; font-size: 10.5pt;
  line-height: 1.55; }
header { border-bottom: 2px solid #145b8c; margin-bottom: 20px; padding-bottom: 10px; }
h1 { font-size: 23pt; line-height: 1.15; margin: 8px 0; }
h2 { border-bottom: 1px solid #cbd7e4; font-size: 15pt; margin-top: 24px; padding-bottom: 5px; }
.meta, .claim-meta { color: #52657a; font-size: 9pt; }
.claim { border-left: 3px solid #7a8da3; margin: 10px 0; padding: 6px 10px; }
.claim.fact { border-color: #145b8c; }
.claim.inference { border-color: #9a6900; }
.claim.recommendation { border-color: #26734d; }
.claim.decision { border-color: #70478a; }
.sources { border-top: 1px solid #cbd7e4; margin-top: 28px; padding-top: 12px; }
a { color: #145b8c; text-decoration: underline; }
footer { color: #52657a; font-size: 8pt; margin-top: 32px; }
@media print { a { color: #15263b; } }
""".strip()


def _text(value: Any, *, limit: int = 8000) -> str:
    return html.escape(str(value)[:limit], quote=True)


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
            parts.extend(
                (
                    f'<div class="claim {_text(paragraph.kind, limit=30)}">',
                    f"<p>{_text(paragraph.text)}</p>",
                    f'<div class="claim-meta">{_text(paragraph.kind.title())} · '
                    f"confianza {paragraph.confidence}/100 {citations}</div></div>",
                )
            )
        parts.append("</section>")
    parts.append('<section class="sources"><h2>Fuentes y evidencias</h2><ol>')
    for source in output.source_index:
        parts.append(
            f'<li id="evidence-{source.evidence_id}"><strong>'
            f"{_text(source.label, limit=1000)}</strong>"
            f" — {_text(source.locator, limit=2000)}</li>"
        )
    parts.extend(
        (
            "</ol></section>",
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
