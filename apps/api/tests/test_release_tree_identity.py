"""SV2-SANEO-ANIDADO · identidad de release desde el árbol (una fuente)."""

from __future__ import annotations

from pathlib import Path

from opn_oracle.config import resolve_release_from_tree


def test_resolve_release_from_tree_reads_nearest_release_id(tmp_path: Path) -> None:
    release_root = tmp_path / "20260804T120000Z-native-abcdef1"
    release_root.mkdir()
    (release_root / "RELEASE_ID").write_text("20260804T120000Z-native-abcdef1\n", encoding="utf-8")
    nested = release_root / "apps" / "api" / "src" / "opn_oracle"
    nested.mkdir(parents=True)
    marker = nested / "config.py"
    marker.write_text("# stub\n", encoding="utf-8")

    assert resolve_release_from_tree(start=marker) == "20260804T120000Z-native-abcdef1"


def test_resolve_release_from_tree_missing_returns_none(tmp_path: Path) -> None:
    orphan = tmp_path / "no-release" / "pkg"
    orphan.mkdir(parents=True)
    start = orphan / "module.py"
    start.write_text("x\n", encoding="utf-8")
    assert resolve_release_from_tree(start=start) is None
