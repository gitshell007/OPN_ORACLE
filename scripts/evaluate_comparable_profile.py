#!/usr/bin/env python3
"""Evaluate a comparable-company plan against known awards over time."""

from __future__ import annotations

import argparse
import json
import re
import time
from datetime import UTC, datetime
from functools import partial
from pathlib import Path
from typing import Any

from opn_oracle.app import create_app
from opn_oracle.integrations.procurement import procurement_client_from_config
from opn_oracle.oracle.comparable_procurement import (
    COMPARABLE_PROFILE_MAX_ROWS,
    evaluate_comparable_history,
)
from opn_oracle.oracle.competitive_procurement import (
    AWARD_PAGE_SIZE,
    AwardHistory,
    _call_waiting_out_rate_limit,
    fetch_award_history,
)


def _history_from_json(path: Path, *, max_rows: int) -> AwardHistory:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        rows = payload
        provider_total = len(rows)
        company_norm = ""
    elif isinstance(payload, dict):
        rows = payload.get("items")
        provider_total = int(payload.get("total") or len(rows or []))
        company_norm = str(payload.get("company_norm") or "")
    else:
        raise ValueError("El JSON de adjudicaciones debe ser una lista o un payload de Signal.")
    if not isinstance(rows, list) or not all(isinstance(item, dict) for item in rows):
        raise ValueError("El JSON no contiene una lista válida de adjudicaciones.")
    selected = tuple(dict(item) for item in rows[:max_rows])
    return AwardHistory(
        rows=selected,
        provider_total=provider_total,
        truncated=provider_total > len(selected),
        provider_company_norm=company_norm,
    )


def _tender_smoke(
    client: Any,
    evaluation: dict[str, Any],
    *,
    per_kind: int,
) -> dict[str, Any]:
    plan = evaluation["plan"]
    probes = [
        *[("cpv", value) for value in plan["cpvs"][:per_kind]],
        *[("term", value) for value in plan["terms"][:per_kind]],
    ]
    results: list[dict[str, Any]] = []
    for index, (kind, value) in enumerate(probes):
        if index:
            time.sleep(0.35)

        call = partial(
            client.tenders,
            keywords=value if kind == "term" else None,
            cpv=value if kind == "cpv" else None,
            min_amount=None,
            max_amount=None,
            deadline_before=None,
            buyer=None,
            region=None,
            active=False,
            limit=1,
            offset=0,
        )

        payload = _call_waiting_out_rate_limit(call, time.sleep)
        results.append({"kind": kind, "value": value, "total": int(payload.get("total") or 0)})
    return {
        "purpose": "informational-current-scope-all-not-recall",
        "provider_contract": "active=false omite el predicado de actividad en Signal v1",
        "measured_at": datetime.now(UTC).isoformat(),
        "probes": results,
        "warning": (
            "Los recuentos se solapan y no se suman. Describen el índice actual de licitaciones, "
            "no la recuperación del holdout histórico de adjudicaciones."
        ),
    }


def _markdown(report: dict[str, Any]) -> str:
    evaluation = report["evaluation"]
    corpus = evaluation["corpus"]
    split = evaluation["temporal_split"]
    recall = evaluation["recall"]
    smoke = report.get("current_tender_smoke")
    lines = [
        f"# Evaluación del perfil comparable · {report['company']}",
        "",
        f"- Ejecutada: `{report['generated_at']}`.",
        f"- Filas Signal: **{corpus['provider_total_rows']}**; analizadas: "
        f"**{corpus['analyzed_rows']}**; truncado: **{str(corpus['truncated']).lower()}**.",
        f"- Expedientes agregados: **{corpus['aggregated_contracts']}**; con fecha para el split: "
        f"**{corpus['dated_contracts']}**.",
        f"- Entrenamiento: **{split['training_contracts']}** "
        f"(`{split['training_start']}` → `{split['training_end']}`).",
        f"- Holdout: **{split['holdout_contracts']}** "
        f"(`{split['holdout_start']}` → `{split['holdout_end']}`).",
        f"- Sin fecha excluidos del split: **{corpus['undated_contracts_excluded_from_split']}**; "
        f"filas con fecha inválida: **{corpus['rows_with_invalid_date']}**.",
        f"- Filas fuente sin fecha: **{corpus['rows_without_date']}**; se conservan en el corpus "
        "agregado cuando su expediente tiene otra fila fechada.",
        "",
        "## Recall sobre adjudicaciones conocidas del holdout",
        "",
        "| Plan | Aciertos | Denominador | Recall |",
        "|---|---:|---:|---:|",
    ]
    for key, label in (
        ("cpv", "Top-K CPV"),
        ("terms", "Top-K términos"),
        ("combined", "Combinado"),
    ):
        metric = recall[key]
        lines.append(
            f"| {label} | {metric['hits']} | {metric['denominator_holdout_contracts']} | "
            f"{metric['recall_percent'] or 'n/d'} % |"
        )

    lines.extend(
        [
            "",
            "## Plan aprendido solo del 80 % antiguo",
            "",
            f"- CPV (K={evaluation['plan']['cpv_top_k']}): "
            + ", ".join(f"`{value}`" for value in evaluation["plan"]["cpvs"]),
            f"- Términos (K={evaluation['plan']['term_top_k']}): "
            + ", ".join(f"`{value}`" for value in evaluation["plan"]["terms"]),
            f"- Stopwords/tokenización: `{evaluation['plan']['title_term_method_version']}`.",
        ]
    )
    if smoke is not None:
        lines.extend(
            [
                "",
                "## Licitaciones actuales: comprobación informativa",
                "",
                "Estos recuentos son consultas independientes con `scope=all`; se solapan, no se "
                "suman y no forman parte del recall histórico.",
                "",
                "| Tipo | Consulta | Total actual |",
                "|---|---|---:|",
            ]
        )
        for probe in smoke["probes"]:
            lines.append(f"| {probe['kind']} | `{probe['value']}` | {probe['total']} |")

    lines.extend(
        [
            "",
            "## Resultado reproducible",
            "",
            "```json",
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True),
            "```",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--company", required=True)
    parser.add_argument("--max-rows", type=int, default=COMPARABLE_PROFILE_MAX_ROWS)
    parser.add_argument("--page-size", type=int, default=AWARD_PAGE_SIZE)
    parser.add_argument("--cpv-top-k", type=int, default=20)
    parser.add_argument("--term-top-k", type=int, default=20)
    parser.add_argument("--tender-smoke-per-kind", type=int, default=5)
    parser.add_argument("--skip-tender-smoke", action="store_true")
    parser.add_argument("--awards-json", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if min(args.max_rows, args.page_size, args.cpv_top_k, args.term_top_k) < 1:
        parser.error("Los límites y K deben ser enteros positivos.")

    app = create_app()
    client = None
    with app.app_context():
        try:
            if args.awards_json is not None:
                history = _history_from_json(args.awards_json, max_rows=args.max_rows)
            else:
                client = procurement_client_from_config()
                history = fetch_award_history(
                    client,
                    company_name=args.company,
                    max_rows=args.max_rows,
                    page_size=args.page_size,
                )
            evaluation = evaluate_comparable_history(
                history,
                company_name=args.company,
                cpv_top_k=args.cpv_top_k,
                term_top_k=args.term_top_k,
            )
            smoke = None
            if not args.skip_tender_smoke:
                if client is None:
                    client = procurement_client_from_config()
                smoke = _tender_smoke(
                    client,
                    evaluation,
                    per_kind=max(0, args.tender_smoke_per_kind),
                )
        finally:
            if client is not None:
                client.close()

    report = {
        "schema": "procurement-comparable-evaluation-report-v1",
        "company": args.company,
        "generated_at": datetime.now(UTC).isoformat(),
        "parameters": {
            "max_rows": args.max_rows,
            "page_size": args.page_size,
            "cpv_top_k": args.cpv_top_k,
            "term_top_k": args.term_top_k,
        },
        "evaluation": evaluation,
        "current_tender_smoke": smoke,
    }
    rendered = _markdown(report)
    if args.output is None:
        print(rendered)
    else:
        safe_company = re.sub(r"[^A-Za-z0-9._-]+", "_", args.company).strip("_")
        output = Path(str(args.output).replace("{company}", safe_company))
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
