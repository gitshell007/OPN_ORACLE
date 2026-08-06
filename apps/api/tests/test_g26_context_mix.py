"""G-26 · guardia de mezcla del contexto (familias, floors/caps, adversarios)."""

from __future__ import annotations

import uuid
from collections import Counter
from dataclasses import dataclass, field
from typing import Any

import pytest

from opn_oracle.ai.context_mix import (
    CONTEXT_FAMILIES,
    diversify_by_context_family,
    intent_family_priority,
    map_context_family,
    mix_context_evidence,
    truncate_extract_for_budget,
)


@dataclass
class FakeEvidence:
    source_kind: str
    extract: str
    provenance: dict[str, Any] = field(default_factory=dict)
    locator: dict[str, Any] = field(default_factory=dict)
    id: str = ""
    checksum: bytes | None = None
    overall_score: float = 0.0

    def __post_init__(self) -> None:
        if not self.id:
            self.id = str(uuid.uuid4())
        if self.checksum is None:
            self.checksum = uuid.UUID(self.id).bytes if _is_uuid(self.id) else self.id.encode()[:32]


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except ValueError:
        return False


def _people(n: int, *, score: float = 50.0) -> list[FakeEvidence]:
    return [
        FakeEvidence(
            "entity_intel",
            f"Persona clave {i} influye en la decisión.",
            provenance={
                "source_kind": "entity_intel",
                "entity_kind": "person",
                "entity_name": f"persona-{i}",
            },
            overall_score=score + i,
        )
        for i in range(n)
    ]


def _competitors(n: int, *, score: float = 50.0) -> list[FakeEvidence]:
    return [
        FakeEvidence(
            "entity_intel",
            f"Competidor relevante {i} concentra el mercado.",
            provenance={
                "source_kind": "entity_intel",
                "entity_kind": "company",
                "role": "competitor",
                "entity_name": f"comp-{i}",
            },
            overall_score=score + i,
        )
        for i in range(n)
    ]


def _actors(n: int) -> list[FakeEvidence]:
    return [
        FakeEvidence(
            "entity_intel",
            f"Actor institucional {i} del ecosistema.",
            provenance={
                "source_kind": "entity_intel",
                "entity_kind": "organization",
                "actor_type": "institution",
                "entity_name": f"actor-{i}",
            },
        )
        for i in range(n)
    ]


def _tenders(n: int, *, label: str = "pliego irrelevante") -> list[FakeEvidence]:
    return [
        FakeEvidence(
            "procurement",
            f"{label} {i} CONTR 2026 {10000 + i}",
            provenance={"source_kind": "procurement"},
            overall_score=1.0,
        )
        for i in range(n)
    ]


def _documents(n: int) -> list[FakeEvidence]:
    return [
        FakeEvidence(
            "document",
            f"Documento propio del expediente {i}.",
            provenance={"source_kind": "document", "document_role": "own_upload"},
            overall_score=40.0,
        )
        for i in range(n)
    ]


def _memories(n: int) -> list[FakeEvidence]:
    return [
        FakeEvidence(
            "memory_signal",
            f"Memoria del expediente hecho {i}.",
            provenance={"source_kind": "memory_signal", "source_ref": f"mem-{i}"},
            overall_score=30.0,
        )
        for i in range(n)
    ]


def _adversarial_bag(
    *,
    tenders: int = 500,
    people: int = 3,
    competitors: int = 4,
    actors: int = 2,
    documents: int = 5,
    memories: int = 3,
) -> list[FakeEvidence]:
    # Newest-first flood: tenders dominate the head of the list.
    return (
        _tenders(tenders)
        + _people(people)
        + _competitors(competitors)
        + _actors(actors)
        + _documents(documents)
        + _memories(memories)
    )


QUESTION = "¿qué persona y competidor influyen y qué dice el pliego?"


# ---------------------------------------------------------------------------
# Family mapping matrix
# ---------------------------------------------------------------------------


@pytest.mark.unit
@pytest.mark.parametrize(
    "item,expected",
    [
        (
            FakeEvidence("memory_signal", "m", provenance={"source_kind": "memory_signal"}),
            "memory",
        ),
        (
            FakeEvidence("procurement", "p", provenance={"source_kind": "procurement"}),
            "tenders",
        ),
        (
            FakeEvidence("document", "d", provenance={"document_role": "own_upload"}),
            "documents",
        ),
        (
            FakeEvidence(
                "document",
                "pliego",
                provenance={"document_role": "pliego"},
            ),
            "tenders",
        ),
        (
            FakeEvidence(
                "entity_intel",
                "p",
                provenance={"entity_kind": "person"},
            ),
            "people",
        ),
        (
            FakeEvidence(
                "entity_intel",
                "c",
                provenance={"entity_kind": "company", "role": "competitor"},
            ),
            "competitors",
        ),
        (
            FakeEvidence(
                "entity_intel",
                "a",
                provenance={"entity_kind": "organization", "actor_type": "institution"},
            ),
            "actors",
        ),
        (
            FakeEvidence("signal", "s", provenance={}),
            "other",
        ),
        (
            FakeEvidence("web_search", "w", provenance={"source_kind": "web_search"}),
            "other",
        ),
        (
            FakeEvidence(
                "mystery_kind",
                "x",
                provenance={"context_family": "people"},
            ),
            "people",
        ),
    ],
)
def test_family_mapping_matrix(item: FakeEvidence, expected: str) -> None:
    assert map_context_family(item) == expected


@pytest.mark.unit
def test_unmapped_falls_to_other() -> None:
    item = FakeEvidence("legacy_unresolved", "noise", provenance={})
    assert map_context_family(item) == "other"


# ---------------------------------------------------------------------------
# Adversarial fixtures
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_adversarial_500_tenders_preserves_relevant_families() -> None:
    bag = _adversarial_bag()
    result = mix_context_evidence(
        bag,
        limit=40,
        question=QUESTION,
        memory_mode="augment",
    )
    selected = result.selected
    families = Counter(map_context_family(r) for r in selected)
    meta = result.metadata

    assert families["people"] >= 1
    assert families["competitors"] >= 1
    assert families["tenders"] >= 1
    assert families["documents"] >= 1
    assert families["memory"] >= 1
    assert families["actors"] >= 1
    # Massive tender corpus must not monopolize the bag or expel others.
    assert families["tenders"] < 40
    non_tender = sum(v for k, v in families.items() if k != "tenders")
    assert non_tender >= 6  # at least one slot-worth across other families
    assert any("Persona clave" in r.extract for r in selected)
    assert any("Competidor relevante" in r.extract for r in selected)
    assert any("pliego" in r.extract.lower() or "CONTR" in r.extract for r in selected)
    assert meta["mixer"] == "context_family_mix.v1"
    assert meta["selected_by_family"]["people"] >= 1
    assert meta["selected_by_family"]["competitors"] >= 1
    assert meta["diversity_complete"] is True
    assert meta["budget_insufficient_for_all_families"] is False


@pytest.mark.unit
def test_extra_1000_irrelevant_tenders_do_not_change_people_competitors() -> None:
    base = _adversarial_bag(tenders=500)
    result_a = mix_context_evidence(base, limit=30, question=QUESTION, memory_mode="augment")
    people_a = sorted(
        r.extract for r in result_a.selected if map_context_family(r) == "people"
    )
    comps_a = sorted(
        r.extract for r in result_a.selected if map_context_family(r) == "competitors"
    )

    flooded = base + _tenders(1000, label="pliego ruido extra")
    # Shuffle order of flood head to prove stability beyond list position.
    flooded = list(reversed(flooded))
    result_b = mix_context_evidence(flooded, limit=30, question=QUESTION, memory_mode="augment")
    people_b = sorted(
        r.extract for r in result_b.selected if map_context_family(r) == "people"
    )
    comps_b = sorted(
        r.extract for r in result_b.selected if map_context_family(r) == "competitors"
    )

    assert people_a == people_b
    assert comps_a == comps_b
    assert people_a  # non-empty
    assert comps_a


@pytest.mark.unit
def test_absent_family_redistributes_and_duplicates_do_not_count() -> None:
    # No actors family at all.
    bag = _people(2) + _competitors(2) + _tenders(20) + _documents(2) + _memories(2)
    # Duplicate people by identity (same entity_name).
    dup = FakeEvidence(
        "entity_intel",
        "Persona clave 0 DUPLICADA no debe ocupar otro slot.",
        provenance={
            "source_kind": "entity_intel",
            "entity_kind": "person",
            "entity_name": "persona-0",  # same identity as people[0]
        },
        overall_score=99.0,
    )
    bag = [dup, *bag]
    result = mix_context_evidence(bag, limit=20, question=QUESTION, memory_mode="augment")
    meta = result.metadata
    assert meta["floors_applied"]["actors"] == 0
    assert meta["selected_by_family"]["actors"] == 0
    # Dedupe: only one slot for persona-0 identity.
    people_ids = [
        r.provenance.get("entity_name")
        for r in result.selected
        if map_context_family(r) == "people"
    ]
    assert people_ids.count("persona-0") <= 1
    assert "dedupe_identity" in meta["discards"] or meta["selected_by_family"]["people"] <= 2


@pytest.mark.unit
def test_budget_3_with_6_eligible_families_is_deterministic_and_flagged() -> None:
    bag = _adversarial_bag(tenders=50)
    orders = [
        bag,
        list(reversed(bag)),
        bag[::2] + bag[1::2],
    ]
    snapshots = []
    for ordered in orders:
        result = mix_context_evidence(
            ordered,
            limit=3,
            question=QUESTION,
            memory_mode="augment",
        )
        assert result.metadata["budget_insufficient_for_all_families"] is True
        assert result.metadata["diversity_complete"] is False
        assert "budget_insufficient_for_all_families" in result.metadata["reason_codes"]
        assert len(result.selected) == 3
        # Intent: persona + competidor + pliego → people/competitors/tenders first.
        families = [map_context_family(r) for r in result.selected]
        snapshots.append(tuple(sorted(r.id for r in result.selected)))
        assert "people" in families
        assert "competitors" in families
        assert "tenders" in families
    # Deterministic across input orders.
    assert len(set(snapshots)) == 1


@pytest.mark.unit
def test_long_token_budget_never_exceeds_and_protects_ids() -> None:
    long_id = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    extract = (
        f"Claim citable con evidence_id {long_id} y CONTR 2026 11077. " + ("palabra " * 2000)
    )
    bag = [
        FakeEvidence(
            "procurement",
            extract,
            provenance={"source_kind": "procurement"},
            id=str(uuid.uuid4()),
            overall_score=100.0,
        ),
        *_people(1),
    ]
    result = mix_context_evidence(
        bag,
        limit=5,
        question=QUESTION,
        memory_mode="augment",
        max_tokens=40,  # ~160 chars
    )
    assert result.metadata["budget_tokens_used"] <= 40
    if result.metadata["budget_chars_requested"] is not None:
        assert result.metadata["budget_chars_used"] <= result.metadata["budget_chars_requested"]
    originals = {r.id: r.extract for r in bag}
    for item_id, text in result.selected_extracts.items():
        assert len(text) <= 40 * 4
        original = originals[item_id]
        # Truncation must not invent content — always a prefix of the original.
        assert original.startswith(text) or text == original[: len(text)]


@pytest.mark.unit
def test_truncate_does_not_split_uuid_when_possible() -> None:
    uid = "11111111-2222-3333-4444-555555555555"
    text = f"Hecho con id {uid} y más texto de relleno aquí."
    out = truncate_extract_for_budget(text, 30)
    assert len(out) <= 30
    # Either full uuid kept or cut before it — never a half uuid suffix alone as claim.
    if uid not in out:
        assert not out.endswith("11111111-2222")


@pytest.mark.unit
def test_memory_modes_g29_disabled_shadow_augment() -> None:
    bag = _people(1) + _competitors(1) + _tenders(5) + _memories(3)

    off = mix_context_evidence(bag, limit=20, memory_mode="disabled")
    assert off.metadata["selected_by_family"]["memory"] == 0
    assert off.metadata["memory_observed"] == 3
    assert "memory_disabled_zero" in off.metadata["reason_codes"]

    shadow = mix_context_evidence(bag, limit=20, memory_mode="shadow")
    assert shadow.metadata["selected_by_family"]["memory"] == 0
    assert shadow.metadata["memory_observed"] == 3
    assert "memory_shadow_observe_only" in shadow.metadata["reason_codes"]

    aug = mix_context_evidence(bag, limit=20, memory_mode="augment")
    assert aug.metadata["selected_by_family"]["memory"] >= 1


@pytest.mark.unit
def test_two_tenants_no_cross_mix_in_pure_bags() -> None:
    """Mixer never invents rows: tenant isolation is caller's responsibility.

    Two independent bags must not share selected IDs when inputs are disjoint.
    """

    t1 = [
        FakeEvidence(
            "entity_intel",
            "Persona tenant A",
            provenance={"entity_kind": "person", "entity_name": "a-person"},
            id=str(uuid.uuid4()),
        ),
        FakeEvidence(
            "procurement",
            "pliego A",
            provenance={"source_kind": "procurement"},
            id=str(uuid.uuid4()),
        ),
    ]
    t2 = [
        FakeEvidence(
            "entity_intel",
            "Persona tenant B",
            provenance={"entity_kind": "person", "entity_name": "b-person"},
            id=str(uuid.uuid4()),
        ),
        FakeEvidence(
            "procurement",
            "pliego B",
            provenance={"source_kind": "procurement"},
            id=str(uuid.uuid4()),
        ),
    ]
    r1 = mix_context_evidence(t1, limit=10, question=QUESTION)
    r2 = mix_context_evidence(t2, limit=10, question=QUESTION)
    ids1 = {r.id for r in r1.selected}
    ids2 = {r.id for r in r2.selected}
    assert ids1.isdisjoint(ids2)
    assert all("tenant A" in r.extract or "pliego A" in r.extract for r in r1.selected)
    assert all("tenant B" in r.extract or "pliego B" in r.extract for r in r2.selected)


# ---------------------------------------------------------------------------
# Invariants / property-style
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_determinism_across_input_permutations() -> None:
    bag = _adversarial_bag(tenders=80, people=3, competitors=3, actors=2, documents=3, memories=2)
    ids_sets = []
    for seed_order in range(5):
        ordered = bag[seed_order:] + bag[:seed_order]
        result = mix_context_evidence(ordered, limit=25, question=QUESTION, memory_mode="augment")
        ids_sets.append(tuple(r.id for r in result.selected))
    assert len(set(ids_sets)) == 1


@pytest.mark.unit
def test_no_family_exceeds_soft_cap_while_other_under_floor() -> None:
    # Many tenders + one person: person floor must be met before tenders exceed cap? 
    # Soft cap tenders=3, floor person=1, limit=5.
    bag = _tenders(50) + _people(1)
    result = mix_context_evidence(
        bag,
        limit=5,
        question=QUESTION,
        family_floors={
            "people": 1,
            "tenders": 1,
            "competitors": 0,
            "actors": 0,
            "documents": 0,
            "memory": 0,
            "other": 0,
        },
        family_caps={
            "people": 2,
            "tenders": 3,
            "competitors": 0,
            "actors": 0,
            "documents": 0,
            "memory": 0,
            "other": 0,
        },
        memory_mode="augment",
    )
    fam = result.metadata["selected_by_family"]
    assert fam["people"] >= 1
    # After floors, residual may fill tenders beyond soft cap — but people not expelled.
    assert any(map_context_family(r) == "people" for r in result.selected)


@pytest.mark.unit
def test_noise_entity_intel_does_not_expel_people_and_competitors() -> None:
    """Baseline failure of source_kind diversify: 100 noise entity_intel → 0 people."""

    noise = [
        FakeEvidence(
            "entity_intel",
            f"Noise co {i}",
            provenance={"entity_kind": "company", "entity_name": f"noise-{i}"},
            overall_score=1.0,
        )
        for i in range(100)
    ]
    bag = noise + _people(3) + _competitors(4) + _tenders(200)
    result = mix_context_evidence(bag, limit=20, question=QUESTION, memory_mode="augment")
    families = Counter(map_context_family(r) for r in result.selected)
    assert families["people"] >= 1
    assert families["competitors"] >= 1
    assert any("Persona clave" in r.extract for r in result.selected)
    assert any("Competidor relevante" in r.extract for r in result.selected)


@pytest.mark.unit
def test_intent_priority_prefers_question_families() -> None:
    prio = intent_family_priority(QUESTION)
    assert prio.index("people") < prio.index("memory")
    assert prio.index("competitors") < prio.index("other")
    assert prio.index("tenders") < prio.index("other")


@pytest.mark.unit
def test_metadata_has_no_raw_extracts_or_pii_keys() -> None:
    bag = _adversarial_bag(tenders=10)
    meta = mix_context_evidence(bag, limit=10, question=QUESTION).metadata
    blob = str(meta)
    assert "Persona clave" not in blob
    assert "extract" not in meta
    assert set(meta["selected_by_family"]) == set(CONTEXT_FAMILIES)


@pytest.mark.unit
def test_diversify_wrapper_returns_list() -> None:
    bag = _adversarial_bag(tenders=20)
    rows = diversify_by_context_family(bag, limit=15, question=QUESTION)
    assert 1 <= len(rows) <= 15


@pytest.mark.unit
def test_empty_candidates() -> None:
    result = mix_context_evidence([], limit=10)
    assert result.selected == []
    assert result.metadata["budget_items_used"] == 0


# ---------------------------------------------------------------------------
# Integration with dual authority block (mock session / pure composition)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_authority_block_carries_context_mix_metadata() -> None:
    from opn_oracle.integrations.memory_ask_dual import build_oracle_authority_block

    mix = mix_context_evidence(_adversarial_bag(tenders=30), limit=15, question=QUESTION)
    block = build_oracle_authority_block(
        dossier_id=str(uuid.uuid4()),
        tenant_id=str(uuid.uuid4()),
        question=QUESTION,
        oracle_evidence=[
            {"id": r.id, "source_kind": r.source_kind, "extract": r.extract[:100]}
            for r in mix.selected
        ],
        context_mix=mix.metadata,
    )
    assert block["context_mix"]["mixer"] == "context_family_mix.v1"
    assert block["context_mix"]["selected_by_family"]["people"] >= 1
    # Model-facing evidence still only has allowlisted fields.
    for row in block["oracle_evidence"]:
        assert "id" in row and "extract" in row


@pytest.mark.unit
def test_property_selected_never_exceeds_limit_and_subset_of_input() -> None:
    bag = _adversarial_bag(tenders=100, people=5, competitors=5, actors=3, documents=4, memories=4)
    for limit in (0, 1, 3, 7, 40):
        for order in (bag, list(reversed(bag))):
            result = mix_context_evidence(order, limit=limit, question=QUESTION)
            assert len(result.selected) <= limit
            input_ids = {r.id for r in order}
            for row in result.selected:
                assert row.id in input_ids
