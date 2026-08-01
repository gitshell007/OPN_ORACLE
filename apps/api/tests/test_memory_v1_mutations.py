"""Mutación J (Oracle): host mode desconocido no puede elevar a augment.

El pytest hijo NO debe heredar ORACLE_RUN_INTEGRATION / TEST_*_URL: con
ORACLE_RUN_INTEGRATION=1 el padre retiene un advisory lock PostgreSQL en
pytest_sessionstart y el hijo se auto-deadlockea al intentar el mismo lock.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]  # repo root
CONTRACT = ROOT / "apps/api/src/opn_oracle/integrations/memory_contract_v1.py"
PY = sys.executable

# Integration env vars that arm conftest advisory lock / real DB session.
_CHILD_STRIP_ENV = (
    "ORACLE_RUN_INTEGRATION",
    "TEST_DATABASE_URL",
    "TEST_RUNTIME_DATABASE_URL",
    "TEST_REDIS_URL",
)

_CHILD_TIMEOUT_S = 60


def _run(node: str) -> subprocess.CompletedProcess[str]:
    """Run a unit nodeid in a child pytest without integration lock/DB env."""
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "apps/api/src")
    for key in _CHILD_STRIP_ENV:
        env.pop(key, None)
    try:
        return subprocess.run(
            [PY, "-m", "pytest", "-q", "--tb=line", "--no-cov", node],
            cwd=str(ROOT / "apps/api"),
            env=env,
            capture_output=True,
            text=True,
            timeout=_CHILD_TIMEOUT_S,
        )
    except subprocess.TimeoutExpired as exc:
        out = (exc.stdout or b"") if isinstance(exc.stdout, (bytes, bytearray)) else (exc.stdout or "")
        err = (exc.stderr or b"") if isinstance(exc.stderr, (bytes, bytearray)) else (exc.stderr or "")
        if isinstance(out, bytes):
            out = out.decode("utf-8", errors="replace")
        if isinstance(err, bytes):
            err = err.decode("utf-8", errors="replace")
        raise AssertionError(
            f"child pytest timed out after {_CHILD_TIMEOUT_S}s for {node}\n"
            f"stdout:\n{out}\nstderr:\n{err}\n"
            "(likely inherited ORACLE_RUN_INTEGRATION / DB URLs → advisory lock deadlock)"
        ) from exc


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
