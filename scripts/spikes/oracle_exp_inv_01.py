#!/usr/bin/env python3
"""Execute the read-only ORACLE-EXP-INV-01 coverage and identity spike."""

from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from investigation_harness import (
    CheckpointRunner,
    SpikeStep,
    audit_award_contract,
    audit_graph_contract,
    audit_identity_gate,
    audit_registry_contract,
    download_official_placsp,
    inspect_ollama_model,
    load_literal_tuple,
    normalize_ollama_base_url,
    parse_placsp_atom,
    read_json,
    run_ollama_benchmark,
    sha256_bytes,
    sha256_json,
    write_json_atomic,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_FIXTURE = REPO_ROOT / "apps/api/tests/fixtures/investigation/oracle_exp_inv_01.v1.json"
DEFAULT_WORK_DIR = REPO_ROOT / "docs/implementation/spikes/.work/75/default"
DEFAULT_PROTOCOL = REPO_ROOT / "docs/implementation/spikes/75_investigation_protocol_v1.md"
PROCUREMENT_SOURCE = REPO_ROOT / "apps/api/src/opn_oracle/oracle/procurement_items.py"
OFFICIAL_PLACSP_ATOM = (
    "https://contrataciondelsectorpublico.gob.es/sindicacion/sindicacion_643/"
    "licitacionesPerfilesContratanteCompleto3.atom"
)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, dict) else {}


def _contract_step(
    fixture: Mapping[str, Any],
    *,
    award_snapshot_keys: tuple[str, ...],
) -> dict[str, Any]:
    return {
        "fixture": {
            "synthetic": fixture.get("synthetic") is True,
            "protocol_version": fixture.get("protocol_version"),
            "hash": sha256_json(fixture),
        },
        "registry": audit_registry_contract(_mapping(fixture.get("registry_contract"))),
        "graph": audit_graph_contract(_mapping(fixture.get("graph_contract"))),
        "awards": audit_award_contract(
            _mapping(fixture.get("award_contract")),
            oracle_preserved_keys=award_snapshot_keys,
        ),
        "identity_gate": audit_identity_gate(
            case for case in fixture.get("identity_gate_cases", []) if isinstance(case, dict)
        ),
        "runtime_boundary": {
            "signal_live_measurement": "not_run_no_local_consumer_credentials",
            "signal_role": "authoritative_runtime_producer",
            "direct_placsp_role": "read_only_spike_diagnostic_only",
            "oracle_persistence": "aggregate_metrics_and_promoted_extracts_only",
            "runtime_mutations": False,
        },
    }


def _decision_step(
    contracts: Mapping[str, Any],
    placsp: Mapping[str, Any],
    ollama: Mapping[str, Any],
) -> dict[str, Any]:
    award_contract = _mapping(contracts.get("awards"))
    snapshot_flags = _mapping(award_contract.get("oracle_snapshot_preserves"))
    official_metrics = _mapping(placsp.get("metrics"))
    count_metrics = _mapping(official_metrics.get("received_tender_quantity"))
    count_coverage = _mapping(count_metrics.get("coverage"))
    identity_gate = _mapping(contracts.get("identity_gate"))
    ai_metrics = _mapping(ollama.get("metrics"))
    ai_aggregate = _mapping(ai_metrics.get("aggregate"))
    reviewer = _mapping(ai_metrics.get("reviewer"))
    participation = _mapping(ai_metrics.get("participation"))

    placsp_count_observed = (
        isinstance(count_coverage.get("numerator"), int) and int(count_coverage["numerator"]) > 0
    )
    identity_safe = (
        identity_gate.get("unsafe_identity_promotions") == 0
        and identity_gate.get("passed") == identity_gate.get("cases")
        and int(identity_gate.get("cases") or 0) > 0
    )
    reviewer_measured = bool(ai_metrics)
    reviewer_false_passes = reviewer.get("false_passes")
    all_schemas_valid = ai_aggregate.get("logical_calls", 0) > 0 and ai_aggregate.get(
        "final_schema_pass"
    ) == ai_aggregate.get("logical_calls")
    reviewer_release_ready = (
        reviewer_measured
        and reviewer_false_passes == 0
        and reviewer.get("cases", 0) >= 10
        and reviewer.get("final_schema_pass") == reviewer.get("cases")
        and reviewer.get("verdict_accuracy") == 1.0
        and reviewer.get("category_precision") == 1.0
        and reviewer.get("category_recall") == 1.0
        and reviewer.get("category_exact_matches") == reviewer.get("cases")
        and reviewer.get("source_pack_hash_matches") == reviewer.get("cases")
    )
    participant_precision = participation.get("precision")
    participant_recall = participation.get("recall")
    participant_localizer_rate = participation.get("localizer_rate")
    participant_release_ready = (
        isinstance(participant_precision, (int, float))
        and not isinstance(participant_precision, bool)
        and participant_precision >= 0.98
        and isinstance(participant_recall, (int, float))
        and not isinstance(participant_recall, bool)
        and participant_recall >= 0.95
        and participant_localizer_rate == 1.0
        and all_schemas_valid
        and participation.get("matched", 0) >= 150
        and participation.get("critical_errors") == 0
        and participation.get("document_id_matches") == participation.get("cases")
    )
    decisions = {
        "mvp_awards": {
            "status": "conditional_go",
            "scope": "adjudications_only_signal_643",
            "reason": (
                "La base actual sirve para un MVP factual, pero falta medir con consumer aislado "
                "la concordancia de 96 unidades y la familia agregada queda fuera."
            ),
        },
        "received_tender_quantity": {
            "status": "contract_no_go",
            "source_field_observed": placsp_count_observed,
            "oracle_snapshot_preserves_field": (
                snapshot_flags.get("received_tender_quantity") is True
            ),
            "reason": (
                "La fuente oficial comunica el recuento, pero el contrato/snapshot Oracle actual "
                "no lo conserva y no aporta identidades."
            ),
        },
        "nominal_non_winners": {
            "status": "no_go",
            "reason": (
                "No existe contrato Signal de participantes por lote con documento y localizador; "
                "la sindicación estructurada no basta para identificar perdedores."
            ),
        },
        "identity": {
            "status": "candidate_human_review_only" if identity_safe else "no_go",
            "auto_merge": False,
            "reason": (
                "El gate determinista evita merge por nombre, pero counterpart_kind e "
                "identificadores siguen incompletos."
            ),
        },
        "ollama_participation_extraction": {
            "status": "release_ready" if participant_release_ready else "continue_gold_corpus",
            "observed_precision": participant_precision,
            "observed_recall": participant_recall,
            "observed_localizer_rate": participant_localizer_rate,
            "observed_critical_errors": participation.get("critical_errors"),
            "observed_document_id_matches": participation.get("document_id_matches"),
            "required_positive_assertions": 150,
        },
        "ollama_reviewer_reject_output": {
            "status": "provisional_go" if reviewer_release_ready else "no_go",
            "false_passes": reviewer_false_passes,
            "reason": (
                "Schema, hash simétrico, veredicto y categoría deben ser exactos y no puede haber "
                "falsos pass; incluso cumpliéndolo el microcorpus solo autoriza ampliar el "
                "benchmark."
            ),
        },
        "all_participants_product_claim": {
            "status": "no_go",
            "reason": (
                "Exige listas completas/reconciliadas >=95 % por estrato y cobertura 643 más "
                "agregada; ninguna de esas condiciones está demostrada."
            ),
        },
    }
    blockers = [
        "Consumer Signal aislado y contrato vivo no disponibles localmente.",
        "Signal/Oracle no exponen ReceivedTenderQuantity ni participantes nominales.",
        "counterpart_kind no está garantizado para contrapartes BORME.",
        "La familia PLACSP agregada autonómica no está cubierta por el corpus Signal observado.",
        "Las muestras estratificadas 96 PLACSP y 72 BORME siguen pendientes de etiquetar.",
        "qwen3.6:27b no está instalado en el host de benchmark.",
    ]
    return {
        "decisions": decisions,
        "blockers": blockers,
        "next_measurement": {
            "placsp_units": 96,
            "borme_assertions": 72,
            "double_label_fraction": 0.25,
            "signal_consumer": "isolated_read_only",
            "model": ai_metrics.get("model", {}).get("model") if ai_metrics else None,
        },
        "no_runtime_changes_authorized": True,
    }


def build_steps(
    *,
    fixture: Mapping[str, Any],
    award_snapshot_keys: tuple[str, ...],
    placsp_url: str | None,
    placsp_timeout: float,
    placsp_max_bytes: int,
    run_ollama: bool,
    ollama_url: str,
    model: str,
    ollama_timeout: float,
    max_calls: int,
    num_ctx: int,
    reviewer_repeat: int,
    cold_start: bool,
    case_cache_dir: Path,
) -> tuple[SpikeStep, ...]:
    def contracts(_: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
        return _contract_step(fixture, award_snapshot_keys=award_snapshot_keys)

    def placsp(_: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
        if placsp_url is None:
            return {"status": "skipped", "reason": "No official Atom URL was requested."}
        payload = download_official_placsp(
            placsp_url,
            timeout_seconds=placsp_timeout,
            max_bytes=placsp_max_bytes,
        )
        return {
            "status": "measured",
            "metrics": parse_placsp_atom(payload, source_url=placsp_url),
        }

    def ollama(_: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
        if not run_ollama:
            return {"status": "skipped", "reason": "Local Ollama benchmark was not requested."}
        return {
            "status": "measured",
            "metrics": run_ollama_benchmark(
                fixture,
                base_url=ollama_url,
                model=model,
                timeout_seconds=ollama_timeout,
                max_calls=max_calls,
                num_ctx=num_ctx,
                reviewer_repeat=reviewer_repeat,
                cold_start=cold_start,
                case_cache_dir=case_cache_dir,
            ),
        }

    def decision(context: Mapping[str, dict[str, Any]]) -> dict[str, Any]:
        return _decision_step(
            context["contracts"],
            context["placsp"],
            context["ollama"],
        )

    return (
        SpikeStep("contracts", (), contracts),
        SpikeStep("placsp", ("contracts",), placsp),
        SpikeStep("ollama", ("contracts", "placsp"), ollama),
        SpikeStep("decision", ("contracts", "placsp", "ollama"), decision),
    )


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--protocol", type=Path, default=DEFAULT_PROTOCOL)
    parser.add_argument("--work-dir", type=Path, default=DEFAULT_WORK_DIR)
    parser.add_argument(
        "--official-placsp",
        action="store_true",
        help="Read one current official PLACSP Atom page and persist aggregate metrics only.",
    )
    parser.add_argument("--placsp-url", default=OFFICIAL_PLACSP_ATOM)
    parser.add_argument("--placsp-timeout", type=float, default=60.0)
    parser.add_argument("--placsp-max-bytes", type=int, default=12_000_000)
    parser.add_argument("--ollama", action="store_true")
    parser.add_argument("--ollama-url", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="qwen3.5:9b")
    parser.add_argument("--ollama-timeout", type=float, default=180.0)
    parser.add_argument("--max-calls", type=int, default=40)
    parser.add_argument("--num-ctx", type=int, default=8192)
    parser.add_argument("--reviewer-repeat", type=int, default=1)
    parser.add_argument("--warm-only", action="store_true")
    parser.add_argument(
        "--stop-after",
        choices=("contracts", "placsp", "ollama", "decision"),
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    fixture = read_json(args.fixture)
    if fixture.get("synthetic") is not True:
        raise ValueError("The versioned benchmark fixture must be explicitly synthetic")
    protocol_bytes = args.protocol.read_bytes()
    award_snapshot_keys = load_literal_tuple(
        PROCUREMENT_SOURCE,
        "AWARD_SNAPSHOT_KEYS",
    )
    normalized_ollama_url = normalize_ollama_base_url(args.ollama_url) if args.ollama else None
    ollama_step_reachable = args.ollama and args.stop_after not in {"contracts", "placsp"}
    ollama_model_manifest = (
        inspect_ollama_model(
            base_url=normalized_ollama_url,
            model=args.model,
            timeout_seconds=args.ollama_timeout,
        )
        if ollama_step_reachable and normalized_ollama_url is not None
        else None
    )
    run_input = {
        "fixture_hash": sha256_json(fixture),
        "protocol_hash": sha256_bytes(protocol_bytes),
        "implementation_hash": sha256_bytes(
            Path(__file__).read_bytes()
            + Path(__file__).with_name("investigation_harness.py").read_bytes()
        ),
        "official_placsp": args.official_placsp,
        "placsp_url": args.placsp_url if args.official_placsp else None,
        "placsp_timeout": args.placsp_timeout if args.official_placsp else None,
        "placsp_max_bytes": args.placsp_max_bytes if args.official_placsp else None,
        "ollama": args.ollama,
        "ollama_url": normalized_ollama_url,
        "model": args.model if args.ollama else None,
        "model_manifest": ollama_model_manifest,
        "ollama_timeout": args.ollama_timeout if args.ollama else None,
        "max_calls": args.max_calls if args.ollama else None,
        "num_ctx": args.num_ctx if args.ollama else None,
        "reviewer_repeat": args.reviewer_repeat if args.ollama else None,
        "cold_start": args.ollama and not args.warm_only,
    }
    steps = build_steps(
        fixture=fixture,
        award_snapshot_keys=award_snapshot_keys,
        placsp_url=args.placsp_url if args.official_placsp else None,
        placsp_timeout=args.placsp_timeout,
        placsp_max_bytes=args.placsp_max_bytes,
        run_ollama=args.ollama,
        ollama_url=normalized_ollama_url or args.ollama_url,
        model=args.model,
        ollama_timeout=args.ollama_timeout,
        max_calls=args.max_calls,
        num_ctx=args.num_ctx,
        reviewer_repeat=args.reviewer_repeat,
        cold_start=not args.warm_only,
        case_cache_dir=args.work_dir / "ollama_cases",
    )
    runner = CheckpointRunner(
        work_dir=args.work_dir,
        protocol_hash=run_input["protocol_hash"],
    )
    manifest = runner.run(steps, run_input=run_input, stop_after=args.stop_after)
    result_path = args.work_dir / "result.json"
    write_json_atomic(result_path, manifest)
    summary = {
        "result": str(result_path),
        "completed_steps": manifest["completed_steps"],
        "reused": [row["step"] for row in manifest["steps"] if row["reused"]],
        "decisions": (
            manifest.get("results", {}).get("decision", {}).get("decisions")
            if "decision" in manifest.get("results", {})
            else None
        ),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
