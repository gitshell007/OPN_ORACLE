"""Unit tests for sv2_memory_baseline scorer (no network, coste 0).

Freeze surface: DEFAULT_ABSTENTION_MARKERS + score_trap.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

SCRIPT = (
    Path(__file__).resolve().parents[1] / "scripts" / "sv2_memory_baseline.py"
)


def _load_baseline():
    name = "sv2_memory_baseline_under_test"
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod  # required so dataclasses can resolve module dict
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture(scope="module")
def baseline():
    return _load_baseline()


def test_q16_authorized_evidence_phrase_is_abstention(baseline) -> None:
    answer = (
        "No hay información disponible en las evidencias autorizadas sobre el "
        "número de empleados de Nexus Ibérica Sistemas S.L. a 31 de diciembre de 2025."
    )
    hit, reason = baseline.score_trap(
        answer, {"trap": True, "abstention_markers": []}
    )
    assert hit is True
    assert reason == "abstained"


def test_empty_answer_is_not_abstention(baseline) -> None:
    hit, reason = baseline.score_trap("", {"trap": True})
    assert hit is False
    assert reason == "empty_answer"


def test_invented_number_is_not_abstention(baseline) -> None:
    hit, reason = baseline.score_trap(
        "Nexus tiene 247 empleados a cierre de 2025.",
        {"trap": True, "abstention_markers": []},
    )
    assert hit is False
    assert reason == "no_abstention"


def test_classic_no_consta_still_hits(baseline) -> None:
    hit, reason = baseline.score_trap(
        "No consta el número de empleados en el expediente.",
        {"trap": True, "abstention_markers": []},
    )
    assert hit is True
    assert reason == "abstained"


def test_fetch_release_meta_parses_short_sha(baseline, monkeypatch) -> None:
    class _Resp:
        status = 200

        def read(self) -> bytes:
            return (
                b'{"release":"20260805T161948Z-native-2ee7072",'
                b'"environment":"production","version":"0.1.0"}'
            )

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        baseline.urllib.request,
        "urlopen",
        lambda *a, **k: _Resp(),
    )
    meta = baseline.fetch_release_meta("https://example.test")
    assert meta["release_id"] == "20260805T161948Z-native-2ee7072"
    assert meta["release_sha"] == "2ee7072"


def test_fetch_release_meta_fails_closed_without_release(baseline, monkeypatch) -> None:
    class _Resp:
        status = 200

        def read(self) -> bytes:
            return b'{"environment":"production"}'

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

    monkeypatch.setattr(
        baseline.urllib.request,
        "urlopen",
        lambda *a, **k: _Resp(),
    )
    with pytest.raises(RuntimeError, match="no se mide a ciegas"):
        baseline.fetch_release_meta("https://example.test")
