"""Behavioral regression for the native release API gate."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


def test_native_release_api_gate_stops_failed_build_before_materialization() -> None:
    result = subprocess.run(
        ["bash", str(ROOT / "tests/operations/test-native-build-release-api-gate.sh")],
        cwd=ROOT,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    assert "fail-closed verificado por comportamiento" in result.stdout
