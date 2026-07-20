#!/usr/bin/env python3
"""Disposable spike for Prompt 61: local model report generation by sections.

This script is intentionally outside the product runtime. It reads a local JSON export
created from production with read-only SELECTs, calls a local Ollama model, and writes
measurement artifacts under docs/implementation/spikes/.work/61.
"""

from __future__ import annotations

import argparse
import json
import re
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

WORK_DIR = Path("docs/implementation/spikes/.work/61")
RAW_REPORTS = WORK_DIR / "prod_reports_raw.json"
OUTPUT_JSON = WORK_DIR / "sectional_spike_result.json"
MODEL = "qwen3.5:9b"

COMPETITIVE_REPORT_ID = "3e56d28d-321d-46f0-a228-fe92995ae32b"
ENTITY_REPORT_ID = "4338f53d-501f-4e75-981d-1649a2c52610"

WORD_RE = re.compile(r"[A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]+(?:[-'][A-Za-zÁÉÍÓÚÜÑáéíóúüñ0-9]+)?")
UUID_RE = re.compile(
    r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"
)
ALIAS_RE = re.compile(r"\[(E[0-9]+)\]")
THINK_RE = re.compile(r"<think>.*?</think>", re.DOTALL | re.IGNORECASE)
STOPWORDS = {
    "a",
    "al",
    "ante",
    "bajo",
    "como",
    "con",
    "contra",
    "de",
    "del",
    "desde",
    "el",
    "en",
    "entre",
    "es",
    "esa",
    "ese",
    "esta",
    "este",
    "la",
    "las",
    "lo",
    "los",
    "mas",
    "no",
    "o",
    "para",
    "por",
    "que",
    "se",
    "sin",
    "su",
    "sus",
    "un",
    "una",
    "y",
}


@dataclass(frozen=True)
class EvidenceAlias:
    alias: str
    evidence_id: str
    label: str


@dataclass(frozen=True)
class SectionSpec:
    key: str
    heading: str
    target_words: str
    evidence_aliases: tuple[str, ...]
    data_keys: tuple[str, ...]
    instruction: str


SECTIONS: tuple[SectionSpec, ...] = (
    SectionSpec(
        "executive_summary",
        "Resumen ejecutivo",
        "180-240",
        ("E1", "E2"),
        ("corpus", "amount_distribution", "buyer_concentration", "awards_by_year"),
        "Sintetiza posicion, volumen, concentracion, limites y decision operativa. No abras lista.",
    ),
    SectionSpec(
        "market_position",
        "Posicion en el mercado",
        "200-300",
        ("E1", "E2"),
        ("corpus", "amount_distribution", "awards_by_year", "primary_cpv_distribution"),
        "Explica escala, recurrencia temporal, familias CPV y lectura competitiva.",
    ),
    SectionSpec(
        "buyer_dependency",
        "Dependencia de organismos",
        "200-300",
        ("E1",),
        ("corpus", "buyer_concentration"),
        "Evalua concentracion por organismos, dependencia real y dispersion de demanda.",
    ),
    SectionSpec(
        "price_behavior",
        "Comportamiento en precio",
        "200-300",
        ("E1",),
        ("amount_distribution", "discount_coverage"),
        "Interpreta distribucion de importes y explica por que no se debe publicar baja media.",
    ),
    SectionSpec(
        "alliances",
        "Alianzas y UTEs",
        "200-300",
        ("E1",),
        ("ute_partners", "winner_variants", "identity_warning"),
        "Analiza la ausencia de socios UTE verificados sin convertir la heuristica en hecho.",
    ),
    SectionSpec(
        "strategic_reading",
        "Lectura estrategica",
        "220-320",
        ("E1", "E2"),
        (
            "corpus",
            "amount_distribution",
            "buyer_concentration",
            "discount_coverage",
            "scope_warning",
        ),
        (
            "Conecta los hallazgos con decisiones comerciales para un expediente "
            "de concurso de bomberos."
        ),
    ),
    SectionSpec(
        "coverage_limits",
        "Cobertura y limites",
        "200-280",
        ("E1", "E2"),
        ("scope_warning", "identity_warning", "corpus", "discount_coverage"),
        "Declara limites de corpus, truncamiento, identidad por nombre y baja no computable.",
    ),
)


def words(text: str) -> list[str]:
    return WORD_RE.findall(text)


def word_count(text: str) -> int:
    return len(words(text))


def paragraphs(text: str) -> list[str]:
    return [part.strip() for part in re.split(r"\n\s*\n", text.strip()) if part.strip()]


def clean_response(text: str) -> str:
    text = THINK_RE.sub("", text)
    text = text.replace("/no_think", "")
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("```") or stripped.lower().startswith("titulo:"):
            continue
        stripped = re.sub(r"^#{1,6}\s*", "", stripped)
        stripped = re.sub(r"^\s*[-*]\s+", "", stripped)
        if stripped:
            lines.append(stripped)
        elif lines and lines[-1]:
            lines.append("")
    return "\n".join(lines).strip()


def compact(value: Any, *, limit: int = 12_000) -> str:
    encoded = json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True, default=str)
    if len(encoded) <= limit:
        return encoded
    return encoded[: limit - 200] + "\n... TRUNCATED IN SPIKE PROMPT ..."


def ollama_generate(prompt: str, *, model: str, timeout: int) -> tuple[str, float]:
    payload = {
        "model": model,
        "prompt": prompt,
        "stream": False,
        "think": False,
        "options": {
            "temperature": 0.25,
            "top_p": 0.9,
            "num_ctx": 8192,
            "num_predict": 900,
        },
    }
    started = time.perf_counter()
    request = urllib.request.Request(
        "http://127.0.0.1:11434/api/generate",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            body = json.loads(response.read().decode("utf-8"))
    except urllib.error.URLError as error:
        raise RuntimeError(f"Ollama call failed: {error}") from error
    return clean_response(str(body.get("response", ""))), time.perf_counter() - started


def find_report(data: dict[str, Any], report_id: str) -> dict[str, Any]:
    return next(report for report in data["reports"] if str(report["id"]) == report_id)


def evidence_aliases(report: dict[str, Any]) -> dict[str, EvidenceAlias]:
    evidence = report["source_snapshot"]["evidence"]
    aliases: dict[str, EvidenceAlias] = {}
    for index, row in enumerate(evidence, start=1):
        aliases[f"E{index}"] = EvidenceAlias(
            alias=f"E{index}",
            evidence_id=str(row["id"]),
            label=str(row.get("source_label") or row.get("locator") or row["id"])[:220],
        )
    return aliases


def section_prompt(
    *,
    report: dict[str, Any],
    section: SectionSpec,
    prior_summary: str,
) -> str:
    analysis = report["source_snapshot"]["competitive_procurement_analysis"]
    aliases = evidence_aliases(report)
    allowed = [aliases[alias] for alias in section.evidence_aliases if alias in aliases]
    data = {key: analysis.get(key) for key in section.data_keys}
    evidence_lines = "\n".join(f"- {item.alias}: {item.label}" for item in allowed)
    prior = (
        f"\nResumen de secciones ya escritas para evitar repeticion:\n{prior_summary}\n"
        if prior_summary
        else ""
    )
    return f"""Eres analista senior de inteligencia competitiva de contratacion publica.

Escribe SOLO la prosa de la seccion "{section.heading}" para un informe ejecutivo
sobre ITURRI S.A en el expediente "Concurso bomberos".

Contrato editorial:
- Extension objetivo: {section.target_words} palabras.
- 2 o 3 parrafos, cada parrafo de 60 a 150 palabras.
- Tono ejecutivo, analitico y claro. No uses bullets, tablas ni JSON.
- No calcules importes, porcentajes ni conteos: usa solo los agregados de Python.
- No escribas UUIDs. Para citar, usa solo alias como [E1] o [E2]; Python los mapeara a evidence_id.
- No cites alias que no esten en la lista permitida de esta seccion.
- Si un dato no esta cubierto por los agregados, declara el limite.
- No incluyas razonamiento oculto, etiquetas think ni preambulos.

Instruccion especifica:
{section.instruction}

Evidencias permitidas para esta seccion:
{evidence_lines}
{prior}
Agregados de Python:
{compact(data)}

/no_think
"""


def extract_section(
    section: SectionSpec, text: str, aliases: dict[str, EvidenceAlias]
) -> dict[str, Any]:
    section_paragraphs = []
    for paragraph in paragraphs(text):
        cited_aliases = sorted(set(ALIAS_RE.findall(paragraph)))
        cleaned = ALIAS_RE.sub("", paragraph)
        cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
        section_paragraphs.append(
            {
                "text": cleaned,
                "kind": "inference",
                "confidence": 70,
                "evidence_ids": [
                    aliases[alias].evidence_id for alias in cited_aliases if alias in aliases
                ],
                "cited_aliases": cited_aliases,
            }
        )
    return {"heading": section.heading, "paragraphs": section_paragraphs, "raw": text}


def build_report(
    report: dict[str, Any],
    generated_sections: list[dict[str, Any]],
    aliases: dict[str, EvidenceAlias],
) -> dict[str, Any]:
    first_paragraphs = generated_sections[0]["paragraphs"] if generated_sections else []
    summary = "\n\n".join(paragraph["text"] for paragraph in first_paragraphs)
    sections = [
        {"heading": item["heading"], "paragraphs": item["paragraphs"]}
        for item in generated_sections
        if item["heading"] != "Resumen ejecutivo"
    ]
    return {
        "title": "Informe seccional de inteligencia competitiva: ITURRI S.A.",
        "executive_summary": summary,
        "sections": sections,
        "facts": [],
        "inferences": [],
        "recommendations": [],
        "confidence": 70,
        "top_opportunities": [],
        "top_risks": [],
        "recommended_actions": [],
        "decisions_required": [],
        "open_questions": [],
        "warnings": [
            "Spike instrumental: el output no procede del flujo productivo de Oracle.",
        ],
        "source_index": [
            {"evidence_id": item.evidence_id, "label": item.label} for item in aliases.values()
        ],
        "source_report_id": report["id"],
    }


def report_text(output: dict[str, Any]) -> str:
    parts = [str(output.get("executive_summary") or "")]
    for section in output.get("sections") or []:
        for paragraph in section.get("paragraphs") or []:
            parts.append(str(paragraph.get("text") or ""))
    return "\n\n".join(part for part in parts if part.strip())


def cited_evidence_ids(output: dict[str, Any]) -> list[str]:
    ids: list[str] = []
    for section in output.get("sections") or []:
        for paragraph in section.get("paragraphs") or []:
            ids.extend(str(item) for item in paragraph.get("evidence_ids") or [])
    return ids


def lexical_overlap(output: dict[str, Any]) -> dict[str, Any]:
    section_tokens: list[tuple[str, set[str]]] = []
    for section in output.get("sections") or []:
        text = " ".join(
            str(paragraph.get("text") or "") for paragraph in section.get("paragraphs") or []
        )
        tokens = {
            token.casefold()
            for token in words(text)
            if len(token) > 3 and token.casefold() not in STOPWORDS
        }
        section_tokens.append((str(section.get("heading")), tokens))
    pairs = []
    for index, (left_name, left_tokens) in enumerate(section_tokens):
        for right_name, right_tokens in section_tokens[index + 1 :]:
            union = left_tokens | right_tokens
            score = len(left_tokens & right_tokens) / len(union) if union else 0.0
            pairs.append({"left": left_name, "right": right_name, "jaccard": round(score, 3)})
    pairs.sort(key=lambda item: item["jaccard"], reverse=True)
    average = sum(item["jaccard"] for item in pairs) / len(pairs) if pairs else 0.0
    return {"average_jaccard": round(average, 3), "top_pairs": pairs[:5]}


def metrics(output: dict[str, Any], *, allowed_evidence_ids: set[str]) -> dict[str, Any]:
    text = report_text(output)
    paragraph_word_counts = [word_count(paragraph) for paragraph in paragraphs(text)]
    section_counts = [
        {
            "heading": section.get("heading"),
            "words": sum(
                word_count(paragraph.get("text") or "")
                for paragraph in section.get("paragraphs") or []
            ),
            "paragraphs": len(section.get("paragraphs") or []),
        }
        for section in output.get("sections") or []
    ]
    citations = cited_evidence_ids(output)
    invalid = sorted(set(citations) - allowed_evidence_ids)
    prose_uuid_count = len(UUID_RE.findall(text))
    return {
        "total_words": word_count(text),
        "executive_summary_words": word_count(str(output.get("executive_summary") or "")),
        "section_words": section_counts,
        "paragraphs": len(paragraph_word_counts),
        "paragraph_word_counts": paragraph_word_counts,
        "telegraphic_paragraphs": sum(1 for count in paragraph_word_counts if count < 45),
        "citations": len(citations),
        "invalid_citations": invalid,
        "prose_uuid_count": prose_uuid_count,
        "lexical_overlap": lexical_overlap(output),
    }


def generate_sections(
    *,
    report: dict[str, Any],
    model: str,
    timeout: int,
    with_prior_summary: bool,
    only_key: str | None = None,
) -> dict[str, Any]:
    aliases = evidence_aliases(report)
    generated = []
    timings = []
    prior_summary = ""
    selected_sections = [
        section for section in SECTIONS if only_key is None or section.key == only_key
    ]
    for section in selected_sections:
        prompt = section_prompt(report=report, section=section, prior_summary=prior_summary)
        text, seconds = ollama_generate(prompt, model=model, timeout=timeout)
        generated_section = extract_section(section, text, aliases)
        generated.append(generated_section)
        timings.append(
            {"section": section.heading, "seconds": round(seconds, 1), "words": word_count(text)}
        )
        if with_prior_summary and only_key is None:
            compact_text = " ".join(
                paragraph["text"] for paragraph in generated_section["paragraphs"]
            )
            prior_summary = (
                prior_summary + "\n" + f"{section.heading}: {compact_text[:500]}"
            ).strip()
    output = build_report(report, generated, aliases)
    if only_key is not None:
        output["sections"] = [
            {"heading": item["heading"], "paragraphs": item["paragraphs"]} for item in generated
        ]
        output["executive_summary"] = ""
    allowed_ids = {item.evidence_id for item in aliases.values()}
    return {
        "output": output,
        "raw_sections": generated,
        "timings": timings,
        "total_seconds": round(sum(item["seconds"] for item in timings), 1),
        "metrics": metrics(output, allowed_evidence_ids=allowed_ids),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--input", type=Path, default=RAW_REPORTS)
    parser.add_argument("--output", type=Path, default=OUTPUT_JSON)
    args = parser.parse_args()

    data = json.loads(args.input.read_text())
    competitive = find_report(data, COMPETITIVE_REPORT_ID)
    entity = find_report(data, ENTITY_REPORT_ID)
    aliases = evidence_aliases(competitive)
    allowed_ids = {item.evidence_id for item in aliases.values()}

    print("1/3 Generating single section: Dependencia de organismos", flush=True)
    single = generate_sections(
        report=competitive,
        model=args.model,
        timeout=args.timeout,
        with_prior_summary=False,
        only_key="buyer_dependency",
    )
    print(json.dumps(single["metrics"], ensure_ascii=False, indent=2), flush=True)

    print("2/3 Generating full report by sections, no prior summary", flush=True)
    full = generate_sections(
        report=competitive,
        model=args.model,
        timeout=args.timeout,
        with_prior_summary=False,
    )
    print(json.dumps(full["metrics"], ensure_ascii=False, indent=2), flush=True)

    print("3/3 Generating full report by sections, with prior summary", flush=True)
    mitigated = generate_sections(
        report=competitive,
        model=args.model,
        timeout=args.timeout,
        with_prior_summary=True,
    )
    print(json.dumps(mitigated["metrics"], ensure_ascii=False, indent=2), flush=True)

    result = {
        "model": args.model,
        "source": {
            "competitive_report_id": COMPETITIVE_REPORT_ID,
            "entity_report_id": ENTITY_REPORT_ID,
        },
        "baseline_qwen_monolithic": metrics(
            competitive["content"], allowed_evidence_ids=allowed_ids
        ),
        "reference_gemini_entity": metrics(
            entity["content"],
            allowed_evidence_ids={str(row["id"]) for row in entity["source_snapshot"]["evidence"]},
        ),
        "single_section": single,
        "sectional_qwen": full,
        "sectional_qwen_with_prior_summary": mitigated,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"Wrote {args.output}", flush=True)


if __name__ == "__main__":
    main()
