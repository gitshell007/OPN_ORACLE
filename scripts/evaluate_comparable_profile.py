#!/usr/bin/env python3
"""Evaluate a comparable-company plan against known awards over time."""

from __future__ import annotations

import argparse
import json
import re
import time
from collections.abc import Iterable, Mapping
from datetime import UTC, date, datetime
from decimal import Decimal
from functools import partial
from pathlib import Path
from typing import Any

from opn_oracle.app import create_app
from opn_oracle.integrations.procurement import procurement_client_from_config
from opn_oracle.oracle.comparable_procurement import (
    COMPARABLE_PROFILE_MAX_ROWS,
    evaluate_comparable_history,
    title_terms,
)
from opn_oracle.oracle.competitive_procurement import (
    AWARD_PAGE_SIZE,
    AwardHistory,
    _call_waiting_out_rate_limit,
    _cpv_codes,
    _group_contracts,
    fetch_award_history,
)
from opn_oracle.oracle.cpv_taxonomy import load_cpv_taxonomy, normalize_cpv_code


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
        raise ValueError(
            "El JSON de adjudicaciones debe ser una lista o un payload de Signal."
        )
    if not isinstance(rows, list) or not all(isinstance(item, dict) for item in rows):
        raise ValueError("El JSON no contiene una lista válida de adjudicaciones.")
    selected = tuple(dict(item) for item in rows[:max_rows])
    return AwardHistory(
        rows=selected,
        provider_total=provider_total,
        truncated=provider_total > len(selected),
        provider_company_norm=company_norm,
    )


def _read_plan_json(value: str) -> dict[str, Any]:
    """Read a direct plan or unwrap the common wizard artifact envelopes."""

    stripped = value.strip()
    if stripped.startswith("{"):
        payload = json.loads(stripped)
    else:
        payload = json.loads(Path(value).read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("El plan debe ser un objeto JSON.")

    for key in ("plan", "output", "result", "validated_output"):
        nested = payload.get(key)
        if isinstance(nested, dict) and (
            "candidate_cpv" in nested or "include_terms" in nested
        ):
            return dict(nested)
    return dict(payload)


def _strings(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, Mapping):
        result: list[str] = []
        for nested in value.values():
            result.extend(_strings(nested))
        return result
    if isinstance(value, Iterable):
        result = []
        for nested in value:
            if isinstance(nested, Mapping):
                candidate = (
                    nested.get("term") or nested.get("value") or nested.get("label")
                )
                if isinstance(candidate, str):
                    result.append(candidate)
                else:
                    result.extend(_strings(nested))
            else:
                result.extend(_strings(nested))
        return result
    return []


def _cpv_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value]
    if not isinstance(value, Iterable) or isinstance(value, Mapping):
        return []
    result: list[str] = []
    for item in value:
        if isinstance(item, str):
            result.append(item)
        elif isinstance(item, Mapping):
            candidate = item.get("code") or item.get("cpv") or item.get("value")
            if isinstance(candidate, str):
                result.append(candidate)
    return result


def _plan_terms(values: Iterable[str]) -> list[str]:
    """Flatten chips with the same tokenization used by wizard post-validation."""

    seen: set[str] = set()
    result: list[str] = []
    for raw in values:
        for token in sorted(title_terms(raw)):
            if token in seen:
                continue
            seen.add(token)
            result.append(token)
    return result


def _percent(hits: int, denominator: int) -> str | None:
    if not denominator:
        return None
    value = Decimal(hits) * 100 / Decimal(denominator)
    return str(value.quantize(Decimal("0.1")))


def _evaluate_arbitrary_plan(
    history: AwardHistory,
    *,
    plan: Mapping[str, Any],
) -> dict[str, Any]:
    """Measure one accepted/generated plan on the same newest-20% holdout."""

    contracts, _ignored_rows = _group_contracts(history.rows)
    dated = [
        contract
        for contract in contracts
        if isinstance(contract.get("award_date"), date)
    ]
    dated.sort(key=lambda item: (item["award_date"], str(item["folder_id"])))
    if len(dated) < 2:
        train_size = len(dated)
    else:
        train_size = min(len(dated) - 1, max(1, int(len(dated) * 0.8)))
    holdout = dated[train_size:]

    taxonomy = load_cpv_taxonomy()
    raw_cpvs = _cpv_values(plan.get("candidate_cpv", []))
    accepted_cpvs: list[str] = []
    discarded_cpvs: list[dict[str, str]] = []
    for raw in raw_cpvs:
        normalized = normalize_cpv_code(raw)
        if normalized is None:
            discarded_cpvs.append({"raw": raw, "reason": "invalid_format"})
        elif normalized not in taxonomy.codes:
            discarded_cpvs.append({"raw": raw, "reason": "not_in_cpv_taxonomy"})
        elif normalized not in accepted_cpvs:
            accepted_cpvs.append(normalized)

    include_raw = _strings(plan.get("include_terms", []))
    synonym_raw = _strings(plan.get("synonyms", []))
    exclude_raw = _strings(plan.get("exclude_terms", []))
    include_chips = _plan_terms([*include_raw, *synonym_raw])
    exclude_chips = _plan_terms(exclude_raw)
    accepted_cpv_set = set(accepted_cpvs)
    include_term_set = set(include_chips)

    cpv_hits = 0
    term_hits = 0
    combined_hits = 0
    for contract in holdout:
        observed_cpv = next(iter(_cpv_codes(contract.get("primary_cpv"))), None)
        cpv = normalize_cpv_code(observed_cpv)
        contract_terms = title_terms(contract.get("title"))
        cpv_hit = cpv in accepted_cpv_set if cpv is not None else False
        term_hit = bool(contract_terms & include_term_set)
        cpv_hits += int(cpv_hit)
        term_hits += int(term_hit)
        combined_hits += int(cpv_hit or term_hit)

    denominator = len(holdout)

    def metric(hits: int) -> dict[str, Any]:
        return {
            "hits": hits,
            "denominator_holdout_contracts": denominator,
            "recall_percent": _percent(hits, denominator),
        }

    return {
        "schema": "procurement-wizard-plan-evaluation-v1",
        "match_semantics": {
            "cpv": "coincidencia exacta del CPV normalizado",
            "terms": "OR entre tokens plegados por spanish-procurement-stopwords-v1",
            "synonyms": "tokens adicionales unidos por OR",
            "exclude_terms": (
                "no puntuados: Signal v1 no ofrece NOT demostrado y el holdout carece "
                "de etiquetas negativas"
            ),
        },
        "normalized_plan": {
            "candidate_cpv": accepted_cpvs,
            "include_and_synonym_terms": include_chips,
            "exclude_terms": exclude_chips,
        },
        "discarded_candidate_cpv": discarded_cpvs,
        "holdout_contracts": denominator,
        "recall": {
            "cpv": metric(cpv_hits),
            "terms": metric(term_hits),
            "combined": metric(combined_hits),
        },
    }


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
        results.append(
            {"kind": kind, "value": value, "total": int(payload.get("total") or 0)}
        )
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

    wizard = report.get("wizard_plan_evaluation")
    if wizard is not None:
        baseline_combined = recall["combined"]
        wizard_combined = wizard["recall"]["combined"]
        comparison = report["wizard_plan_comparison"]
        lines.extend(
            [
                "",
                "## Plan arbitrario del wizard sobre el mismo holdout",
                "",
                "| Plan | Aciertos | Denominador | Recall combinado |",
                "|---|---:|---:|---:|",
                f"| Línea base determinista | {baseline_combined['hits']} | "
                f"{baseline_combined['denominator_holdout_contracts']} | "
                f"{baseline_combined['recall_percent'] or 'n/d'} % |",
                f"| Wizard · {report['wizard_plan_label']} | {wizard_combined['hits']} | "
                f"{wizard_combined['denominator_holdout_contracts']} | "
                f"{wizard_combined['recall_percent'] or 'n/d'} % |",
                "",
                f"- Criterio ≥ línea base: **{comparison['result']}**; brecha: "
                f"**{comparison['delta_percentage_points']} puntos porcentuales**.",
                "- Los términos y sinónimos se pliegan en tokens y se unen por OR, igual que "
                "la post-validación del wizard. Las exclusiones no se puntúan.",
                f"- CPV descartados al evaluar: **{len(wizard['discarded_candidate_cpv'])}**.",
            ]
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
    parser.add_argument(
        "--plan-json",
        help="Ruta a un plan JSON arbitrario o un objeto JSON inline.",
    )
    parser.add_argument("--plan-label", default="plan-v1")
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
            wizard_evaluation = (
                _evaluate_arbitrary_plan(history, plan=_read_plan_json(args.plan_json))
                if args.plan_json
                else None
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
        "wizard_plan_label": args.plan_label if wizard_evaluation is not None else None,
        "wizard_plan_evaluation": wizard_evaluation,
        "current_tender_smoke": smoke,
    }
    if wizard_evaluation is not None:
        baseline_value = Decimal(
            evaluation["recall"]["combined"]["recall_percent"] or "0"
        )
        wizard_value = Decimal(
            wizard_evaluation["recall"]["combined"]["recall_percent"] or "0"
        )
        delta = wizard_value - baseline_value
        report["wizard_plan_comparison"] = {
            "acceptance_criterion": "wizard combined recall >= deterministic baseline",
            "baseline_recall_percent": str(baseline_value),
            "wizard_recall_percent": str(wizard_value),
            "delta_percentage_points": str(delta),
            "result": "PASS" if delta >= 0 else "FAIL",
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
