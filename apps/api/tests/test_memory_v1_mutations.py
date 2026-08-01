"""Mutación J (Oracle): host mode desconocido no puede elevar a augment."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # repo root (apps/api/tests → ../../..)
# worktree root is parents[3] from apps/api/tests/file → apps/api/tests → apps/api → apps → repo
# Actually: file at apps/api/tests/test_... → parents[0]=tests, [1]=api, [2]=apps, [3]=repo
CONTRACT = ROOT / "apps/api/src/opn_oracle/integrations/memory_contract_v1.py"
PY = sys.executable


def _run(node: str) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "apps/api/src")
    return subprocess.run(
        [PY, "-m", "pytest", "-q", "--tb=line", "--no-cov", node],
        cwd=str(ROOT / "apps/api"),
        env=env,
        capture_output=True,
        text=True,
    )


def test_mutation_J_unknown_host_mode_allows_augment():
    """If unknown host is treated as http, host-fail-closed test goes RED."""
    original = CONTRACT.read_text()
    old = """    if host != "http":
        # typo / unknown / accidental shadow|augment as host mode → disabled
        return EffectiveMemoryMode(
            "disabled", "host_invalid", host, connection_healthy, tenant_mode, dossier_mode
        )"""
    new = """    if False and host != "http":
        return EffectiveMemoryMode(
            "disabled", "host_invalid", host, connection_healthy, tenant_mode, dossier_mode
        )"""
    assert old in original, "mutation anchor missing"
    CONTRACT.write_text(original.replace(old, new, 1))
    try:
        red = _run(
            "tests/test_memory_v1_contract.py::test_host_mode_unknown_typo_never_augment_or_shadow"
        )
        assert red.returncode != 0, f"expected RED:\n{red.stdout}\n{red.stderr}"
    finally:
        CONTRACT.write_text(original)
    green = _run(
        "tests/test_memory_v1_contract.py::test_host_mode_unknown_typo_never_augment_or_shadow"
    )
    assert green.returncode == 0, f"restore GREEN failed:\n{green.stdout}\n{green.stderr}"
