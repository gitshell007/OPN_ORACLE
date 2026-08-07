#!/usr/bin/env python3
"""Smoke tests for scripts/validate_legal_compliance_pack.py."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VALIDATOR = ROOT / "scripts" / "validate_legal_compliance_pack.py"


def test_validator_passes_on_pack() -> None:
    result = subprocess.run(
        [sys.executable, str(VALIDATOR)],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "PASS" in result.stdout


def test_required_docs_exist() -> None:
    legal = ROOT / "docs" / "legal"
    required = [
        "README.md",
        "DPA_BORRADOR.md",
        "REGISTRO_ACTIVIDADES_TRATAMIENTO.md",
        "SUBENCARGADOS_Y_RESIDENCIA.md",
        "PRIVACIDAD_RETENCION_Y_SUPRESION.md",
        "BASE_JURIDICA_INVESTIGACIONES.md",
        "MATRIZ_CONTROLES_Y_ALEGACIONES.md",
        "CUESTIONARIO_DUE_DILIGENCE_COMERCIAL.md",
        "PRODUCTION_READINESS_STATEMENT.md",
    ]
    for name in required:
        path = legal / name
        assert path.is_file(), name
        text = path.read_text(encoding="utf-8")
        assert "BORRADOR · requiere revisión jurídica" in text
        assert "0.1.0-g21" in text


if __name__ == "__main__":
    test_required_docs_exist()
    test_validator_passes_on_pack()
    print("test_validate_legal_compliance_pack: OK")
