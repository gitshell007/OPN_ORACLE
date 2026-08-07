"""Behavioural guard against integration fixtures leaking into unit tests."""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


@pytest.mark.unit
def test_memsol_collection_before_unit_test_does_not_force_integration_fixture() -> None:
    """A unit test still runs when the MEMSOL integration module is collected first.

    This exact order used to register the whole domain integration test module through
    ``pytest_plugins``.  Its autouse fixture requested PostgreSQL and skipped every later
    unit test when ``ORACLE_RUN_INTEGRATION`` was absent.
    """

    api_root = Path(__file__).resolve().parents[1]
    env = os.environ.copy()
    for name in (
        "ORACLE_RUN_INTEGRATION",
        "TEST_DATABASE_URL",
        "TEST_RUNTIME_DATABASE_URL",
        "TEST_REDIS_URL",
    ):
        env.pop(name, None)

    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            "--no-cov",
            "-q",
            "-m",
            "not integration",
            "tests/test_integration_memsol_http.py",
            "tests/test_app.py::test_create_test_app",
            "-rs",
        ],
        cwd=api_root,
        env=env,
        capture_output=True,
        text=True,
        timeout=30,
        check=False,
    )
    output = f"{result.stdout}\n{result.stderr}"
    assert result.returncode == 0, output
    assert "1 passed" in output, output
    assert "3 deselected" in output, output
    assert "skipped" not in output.lower(), output
