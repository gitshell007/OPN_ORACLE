"""Parity: situation summary and Preguntar share one evidence source_kind allowlist.

If someone re-inlines a divergent tuple in either consumer, this suite fails.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from opn_oracle.oracle.evidence_source_kinds import DOSSIER_CORPUS_EVIDENCE_SOURCE_KINDS

API_SRC = Path(__file__).resolve().parents[1] / "src" / "opn_oracle"
CONTEXT_PATH = API_SRC / "ai" / "context.py"
ASK_PATH = API_SRC / "integrations" / "memory_ask_dual.py"
KINDS_PATH = API_SRC / "oracle" / "evidence_source_kinds.py"


def test_shared_allowlist_includes_memory_signal_and_classic_kinds() -> None:
    kinds = set(DOSSIER_CORPUS_EVIDENCE_SOURCE_KINDS)
    assert "memory_signal" in kinds
    for required in ("signal", "document", "procurement", "entity_intel"):
        assert required in kinds
    # Frozen contract: no accidental extras without an explicit review.
    assert kinds == {
        "signal",
        "document",
        "procurement",
        "entity_intel",
        "memory_signal",
    }


def test_context_and_ask_import_the_same_shared_constant() -> None:
    """Both corpus loaders must bind the identical object, not a copy."""
    from opn_oracle.ai import context as context_mod
    from opn_oracle.integrations import memory_ask_dual as ask_mod

    assert context_mod.DOSSIER_CORPUS_EVIDENCE_SOURCE_KINDS is DOSSIER_CORPUS_EVIDENCE_SOURCE_KINDS
    assert ask_mod.DOSSIER_CORPUS_EVIDENCE_SOURCE_KINDS is DOSSIER_CORPUS_EVIDENCE_SOURCE_KINDS
    assert (
        context_mod.DOSSIER_CORPUS_EVIDENCE_SOURCE_KINDS
        is ask_mod.DOSSIER_CORPUS_EVIDENCE_SOURCE_KINDS
    )


def _inline_source_kind_tuples(path: Path) -> list[tuple[int, tuple[str, ...]]]:
    """Return any string-tuples passed to Evidence.source_kind.in_(...)."""
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    found: list[tuple[int, tuple[str, ...]]] = []

    class Visitor(ast.NodeVisitor):
        def visit_Call(self, node: ast.Call) -> None:  # noqa: N802
            func = node.func
            # Match *.source_kind.in_(...)
            if (
                isinstance(func, ast.Attribute)
                and func.attr == "in_"
                and isinstance(func.value, ast.Attribute)
                and func.value.attr == "source_kind"
            ):
                if node.args and isinstance(node.args[0], (ast.Tuple, ast.List)):
                    values: list[str] = []
                    for elt in node.args[0].elts:
                        if isinstance(elt, ast.Constant) and isinstance(elt.value, str):
                            values.append(elt.value)
                        else:
                            values = []
                            break
                    if values:
                        found.append((node.lineno, tuple(values)))
            self.generic_visit(node)

    Visitor().visit(tree)
    return found


@pytest.mark.parametrize(
    "path",
    [CONTEXT_PATH, ASK_PATH],
    ids=["ai.context", "integrations.memory_ask_dual"],
)
def test_consumers_do_not_inline_source_kind_tuples(path: Path) -> None:
    """Guardrail: no hard-coded kind lists next to source_kind.in_."""
    assert path.is_file(), f"missing consumer {path}"
    inlined = _inline_source_kind_tuples(path)
    assert inlined == [], (
        f"{path.relative_to(API_SRC.parent)} still inlines source_kind tuples "
        f"at lines {[lineno for lineno, _ in inlined]}; "
        "import DOSSIER_CORPUS_EVIDENCE_SOURCE_KINDS instead."
    )


def test_shared_module_is_the_only_kind_list_definition() -> None:
    text = KINDS_PATH.read_text(encoding="utf-8")
    assert "memory_signal" in text
    assert "DOSSIER_CORPUS_EVIDENCE_SOURCE_KINDS" in text
