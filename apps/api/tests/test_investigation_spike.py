from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SPIKE_DIR = Path(__file__).resolve().parents[3] / "scripts" / "spikes"
if str(SPIKE_DIR) not in sys.path:
    sys.path.insert(0, str(SPIKE_DIR))

from investigation_harness import (  # noqa: E402
    CallBudget,
    CheckpointRunner,
    IdentityTriageOutput,
    SpikeStep,
    _run_cached_case,
    audit_award_contract,
    deduplicate_received_tender_quantity,
    identity_gate,
    normalize_ollama_base_url,
    ollama_structured_call,
    parse_placsp_atom,
    read_json,
    sanitize_artifact,
    score_participation,
    score_reviewer,
)
from oracle_exp_inv_01 import _decision_step  # noqa: E402

FIXTURE = Path(__file__).parent / "fixtures" / "investigation" / "oracle_exp_inv_01.v1.json"


def test_identity_gate_only_accepts_same_official_identifier() -> None:
    same_name = {"name": "PERSONA SINTÉTICA", "official_identifier": None}
    identifier = {
        "scheme": "synthetic_registry_id",
        "authority": "registro-sintetico",
        "jurisdiction": "ES",
        "normalized_value": "ID-1",
    }
    assert identity_gate(same_name, same_name) == "candidate_human_review"
    assert (
        identity_gate(
            {"name": "A", "official_identifier": identifier},
            {"name": "B", "official_identifier": identifier},
        )
        == "verified_same_identifier"
    )
    assert (
        identity_gate(
            {"name": "A", "official_identifier": identifier},
            {
                "name": "A",
                "official_identifier": identifier | {"normalized_value": "ID-2"},
            },
        )
        == "rejected_identifier_conflict"
    )
    assert (
        identity_gate(
            {"name": "A", "official_identifier": identifier},
            {
                "name": "A",
                "official_identifier": identifier
                | {
                    "scheme": "synthetic_tax_id",
                    "authority": "agencia-sintetica",
                },
            },
        )
        == "candidate_human_review"
    )
    assert (
        identity_gate(
            {"name": "A", "official_identifier": identifier},
            {
                "name": "A",
                "official_identifier": identifier | {"normalized_value": "id-1"},
            },
        )
        == "rejected_identifier_conflict"
    )
    assert (
        identity_gate(
            {"name": "A", "official_identifier": identifier},
            {
                "name": "A",
                "official_identifier": {
                    "scheme": "synthetic_registry_id",
                    "normalized_value": "ID-1",
                },
            },
        )
        == "candidate_human_review"
    )


def test_received_tender_quantity_is_deduplicated_per_lot_and_revision() -> None:
    fixture = read_json(FIXTURE)
    awards = fixture["award_contract"]["items"]

    result = deduplicate_received_tender_quantity(awards)

    assert result == {
        "rows": 4,
        "rows_with_count": 3,
        "scopes_total": 3,
        "scopes_with_count": 2,
        "scopes_with_conflict": 0,
        "repeated_count_rows": 1,
        "naive_sum": 10,
        "deduplicated_sum": 6,
        "double_count_avoided": 4,
    }


def test_award_contract_reports_fields_that_snapshot_would_drop() -> None:
    fixture = read_json(FIXTURE)

    result = audit_award_contract(
        fixture["award_contract"],
        oracle_preserved_keys=(
            "folder_id",
            "lot_id",
            "winner",
            "documents",
        ),
    )

    assert result["participant_count"]["numerator"] == 3
    assert result["winner_identifier"]["numerator"] == 3
    assert result["participant_identities"]["numerator"] == 0
    assert result["oracle_snapshot_preserves"] == {
        "received_tender_quantity": False,
        "winner_identifier": False,
        "participant_identities": False,
    }


def test_placsp_parser_does_not_double_count_repeated_lot_quantity() -> None:
    payload = b"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom"
 xmlns:cbc="urn:dgpe:names:draft:codice:schema:xsd:CommonBasicComponents-2"
 xmlns:cac="urn:dgpe:names:draft:codice:schema:xsd:CommonAggregateComponents-2">
  <id>https://example.invalid/feed</id>
  <updated>2026-07-23T10:00:00+02:00</updated>
  <entry>
    <updated>2026-07-22T09:00:00+02:00</updated>
    <link href="https://example.invalid/folder"/>
    <cac:ContractFolderStatus>
      <cbc:ContractFolderID>EXP-SYN</cbc:ContractFolderID>
      <cac:TenderResult>
        <cbc:ReceivedTenderQuantity>3</cbc:ReceivedTenderQuantity>
        <cac:WinningParty>
          <cac:PartyIdentification>
            <cbc:ID schemeName="NIF">B00000001</cbc:ID>
          </cac:PartyIdentification>
          <cac:PartyName><cbc:Name>UNO SINTETICO SL</cbc:Name></cac:PartyName>
        </cac:WinningParty>
        <cac:AwardedTenderedProject><cbc:ProcurementProjectLotID>1</cbc:ProcurementProjectLotID></cac:AwardedTenderedProject>
      </cac:TenderResult>
      <cac:TenderResult>
        <cbc:ReceivedTenderQuantity>3</cbc:ReceivedTenderQuantity>
        <cac:WinningParty>
          <cac:PartyIdentification>
            <cbc:ID schemeName="NIF">B00000002</cbc:ID>
          </cac:PartyIdentification>
          <cac:PartyName><cbc:Name>DOS SINTETICO SL</cbc:Name></cac:PartyName>
        </cac:WinningParty>
        <cac:AwardedTenderedProject><cbc:ProcurementProjectLotID>1</cbc:ProcurementProjectLotID></cac:AwardedTenderedProject>
      </cac:TenderResult>
    </cac:ContractFolderStatus>
  </entry>
</feed>"""

    result = parse_placsp_atom(payload, source_url="https://example.invalid/feed")
    deduplication = result["received_tender_quantity"]["deduplication"]

    assert result["entries"] == 1
    assert result["tender_results"] == 2
    assert result["entries_with_non_winner_identity_nodes"] == 0
    assert deduplication["naive_sum"] == 6
    assert deduplication["deduplicated_sum"] == 3
    assert deduplication["double_count_avoided"] == 3


def test_checkpoint_runner_resumes_and_invalidates_on_input_change(tmp_path: Path) -> None:
    calls = {"first": 0, "second": 0}

    def first(_: object) -> dict[str, int]:
        calls["first"] += 1
        return {"value": 1}

    def second(context: object) -> dict[str, int]:
        calls["second"] += 1
        assert isinstance(context, dict)
        return {"value": int(context["first"]["value"]) + 1}

    steps = (
        SpikeStep("first", (), first),
        SpikeStep("second", ("first",), second),
    )
    runner = CheckpointRunner(work_dir=tmp_path, protocol_hash="protocol-v1")

    first_run = runner.run(steps, run_input={"fixture_hash": "one"})
    resumed = runner.run(steps, run_input={"fixture_hash": "one"})
    first_checkpoint_path = tmp_path / "checkpoints" / "first.json"
    first_checkpoint = read_json(first_checkpoint_path)
    first_checkpoint["result"] = {"value": 999}
    first_checkpoint_path.write_text(json.dumps(first_checkpoint), encoding="utf-8")
    tampered = runner.run(steps, run_input={"fixture_hash": "one"})
    changed = runner.run(steps, run_input={"fixture_hash": "two"})

    assert calls == {"first": 3, "second": 2}
    assert [row["reused"] for row in first_run["steps"]] == [False, False]
    assert [row["reused"] for row in resumed["steps"]] == [True, True]
    assert [row["reused"] for row in tampered["steps"]] == [False, True]
    assert [row["reused"] for row in changed["steps"]] == [False, False]
    assert changed["results"]["second"] == {"value": 2}


def test_checkpoint_artifacts_redact_secrets_and_raw_corpus() -> None:
    value = {
        "api_key": "do-not-persist",
        "input_tokens": 40,
        "nested": {"raw_payload": {"person": "synthetic"}, "safe": True},
    }

    assert sanitize_artifact(value) == {
        "api_key": "[redacted]",
        "input_tokens": 40,
        "nested": {"raw_payload": "[redacted]", "safe": True},
    }


def test_call_budget_stops_before_exceeding_limit() -> None:
    budget = CallBudget(maximum=1)
    budget.consume()

    with pytest.raises(RuntimeError, match="budget exhausted"):
        budget.consume()

    assert budget.used == 1


def test_ollama_endpoint_is_loopback_and_never_contains_credentials() -> None:
    assert normalize_ollama_base_url("http://localhost:11434/") == "http://localhost:11434"
    assert normalize_ollama_base_url("http://[::1]:11434") == "http://[::1]:11434"

    with pytest.raises(ValueError, match="credential-free loopback"):
        normalize_ollama_base_url("http://user:password@localhost:11434")
    with pytest.raises(ValueError, match="credential-free loopback"):
        normalize_ollama_base_url("https://ollama.example.test")


def test_reviewer_false_pass_is_a_blocking_metric() -> None:
    score = score_reviewer(
        expected={"verdict": "fail", "issue_categories": ["unsupported"]},
        output={
            "source_pack_hash": "a" * 64,
            "verdict": "pass",
            "issues": [],
        },
        source_pack_hash="a" * 64,
    )
    invalid_output = score_reviewer(
        expected={"verdict": "fail", "issue_categories": ["unsupported"]},
        output=None,
        source_pack_hash="a" * 64,
    )

    assert score["false_pass"] is True
    assert score["category_false_negatives"] == 1
    assert score["category_exact_match"] is False
    assert score["source_pack_hash_match"] is True
    assert invalid_output["false_pass"] is False


def test_participation_score_rejects_cross_document_attribution() -> None:
    case_input = {
        "document_id": "DOC-EXPECTED",
        "pages": [{"page": 1, "text": "EMPRESA SINTÉTICA fue admitida."}],
    }
    output = {
        "document_id": "DOC-OTHER",
        "extractions": [
            {
                "literal_name": "EMPRESA SINTÉTICA",
                "identifier": None,
                "lot_id": None,
                "role": "bidder_confirmed",
                "page": 1,
                "quote": "EMPRESA SINTÉTICA fue admitida.",
                "is_ute": False,
                "explicit_members": [],
                "ambiguous": False,
            }
        ],
    }

    score = score_participation(
        case_input=case_input,
        expected=output["extractions"],
        output=output,
    )

    assert score["matched"] == 1
    assert score["valid_localizers"] == 1
    assert score["document_id_match"] is False


def test_structured_ollama_call_disables_hidden_reasoning() -> None:
    class FakeClient:
        def __init__(self) -> None:
            self.payload: dict[str, object] | None = None

        def post(
            self,
            path: str,
            payload: dict[str, object],
            *,
            counted: bool,
        ) -> dict[str, object]:
            assert path == "api/chat"
            assert counted is True
            self.payload = payload
            return {
                "message": {
                    "content": (
                        '{"pair_id":"PAIR-1","signals_for":[],"signals_against":[],'
                        '"priority":50,"uncertain":true,'
                        '"recommended_action":"human_review","rationale":"Falta identidad."}'
                    )
                },
                "eval_count": 20,
                "eval_duration": 1_000_000_000,
            }

    client = FakeClient()
    result = ollama_structured_call(
        client=client,  # type: ignore[arg-type]
        model="synthetic-model",
        schema=IdentityTriageOutput,
        system_prompt="System",
        task_prompt="Task",
        context={"pair_id": "PAIR-1"},
        max_output_tokens=100,
        num_ctx=2048,
    )

    assert client.payload is not None
    assert client.payload["think"] is False
    assert result["initial_schema_pass"] is True
    assert result["repair_used"] is False


def test_case_cache_reuses_only_the_same_fingerprint(tmp_path: Path) -> None:
    calls = 0

    def execute() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"calls": calls}

    first, first_reused = _run_cached_case(
        cache_dir=tmp_path,
        task="reviewer",
        case_id="case:1",
        fingerprint="fingerprint-1",
        execute=execute,
    )
    second, second_reused = _run_cached_case(
        cache_dir=tmp_path,
        task="reviewer",
        case_id="case:1",
        fingerprint="fingerprint-1",
        execute=execute,
    )
    changed, changed_reused = _run_cached_case(
        cache_dir=tmp_path,
        task="reviewer",
        case_id="case:1",
        fingerprint="fingerprint-2",
        execute=execute,
    )

    assert first == second == {"calls": 1}
    assert changed == {"calls": 2}
    assert first_reused is False
    assert second_reused is True
    assert changed_reused is False


def test_case_cache_reexecutes_if_persisted_result_hash_is_tampered(tmp_path: Path) -> None:
    calls = 0

    def execute() -> dict[str, int]:
        nonlocal calls
        calls += 1
        return {"calls": calls}

    _run_cached_case(
        cache_dir=tmp_path,
        task="identity",
        case_id="case-1",
        fingerprint="fingerprint-1",
        execute=execute,
    )
    cache_path = tmp_path / "identity" / "case-1.json"
    checkpoint = read_json(cache_path)
    checkpoint["result"] = {"calls": 999}
    cache_path.write_text(json.dumps(checkpoint), encoding="utf-8")

    result, reused = _run_cached_case(
        cache_dir=tmp_path,
        task="identity",
        case_id="case-1",
        fingerprint="fingerprint-1",
        execute=execute,
    )

    assert result == {"calls": 2}
    assert reused is False


def test_participation_gate_requires_recall_localizers_and_schema() -> None:
    contracts = {
        "awards": {"oracle_snapshot_preserves": {"received_tender_quantity": False}},
        "identity_gate": {
            "cases": 4,
            "passed": 4,
            "unsafe_identity_promotions": 0,
        },
    }
    placsp = {
        "metrics": {"received_tender_quantity": {"coverage": {"numerator": 96, "denominator": 96}}}
    }
    ollama = {
        "metrics": {
            "aggregate": {
                "logical_calls": 160,
                "final_schema_pass": 160,
            },
            "participation": {
                "cases": 4,
                "expected": 150,
                "matched": 2,
                "critical_errors": 148,
                "document_id_matches": 4,
                "precision": 1.0,
                "recall": 0.01,
                "localizer_rate": 1.0,
            },
            "reviewer": {
                "cases": 10,
                "false_passes": 0,
                "final_schema_pass": 10,
                "verdict_accuracy": 1.0,
                "category_precision": 1.0,
                "category_recall": 1.0,
                "category_exact_matches": 9,
                "source_pack_hash_matches": 10,
            },
        }
    }

    decision = _decision_step(contracts, placsp, ollama)

    assert (
        decision["decisions"]["ollama_participation_extraction"]["status"] == "continue_gold_corpus"
    )
    assert decision["decisions"]["ollama_reviewer_reject_output"]["status"] == "no_go"

    ollama["metrics"]["participation"].update(
        matched=150,
        critical_errors=1,
        recall=1.0,
    )
    critical_error = _decision_step(contracts, placsp, ollama)
    assert (
        critical_error["decisions"]["ollama_participation_extraction"]["status"]
        == "continue_gold_corpus"
    )

    ollama["metrics"]["participation"]["critical_errors"] = 0
    ollama["metrics"]["participation"]["matched"] = 149
    insufficient_positive_corpus = _decision_step(contracts, placsp, ollama)
    assert (
        insufficient_positive_corpus["decisions"]["ollama_participation_extraction"]["status"]
        == "continue_gold_corpus"
    )

    ollama["metrics"]["participation"]["matched"] = 150
    ollama["metrics"]["reviewer"].update(
        category_exact_matches=10,
    )

    release_candidate = _decision_step(contracts, placsp, ollama)

    assert (
        release_candidate["decisions"]["ollama_participation_extraction"]["status"]
        == "release_ready"
    )
    assert (
        release_candidate["decisions"]["ollama_reviewer_reject_output"]["status"]
        == "provisional_go"
    )
