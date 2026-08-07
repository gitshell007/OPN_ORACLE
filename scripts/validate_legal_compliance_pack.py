#!/usr/bin/env python3
"""Validate docs/legal commercial compliance pack (G-21).

Checks:
1. Required documents exist.
2. Mandatory draft header, version, owner and estado metadata.
3. Relative markdown links resolve.
4. Adversarial language scanner (absolute claims without honest framing).
5. Every matrix row marked ``verified`` points at an existing repo path.

Exit code 0 on success, 1 on failure. No network, no secrets, cost 0.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
LEGAL = ROOT / "docs" / "legal"

REQUIRED_DOCS = [
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

HEADER = (
    "BORRADOR · requiere revisión jurídica y validación del "
    "despliegue antes de enviar o firmar"
)

# Absolute claims that must not appear as unframed product promises.
FORBIDDEN_CLAIM_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    (
        "cumplimos plenamente",
        re.compile(r"cumplimos\s+plenamente", re.IGNORECASE),
    ),
    (
        "certificado ISO/SOC/ENS como hecho",
        re.compile(
            r"\b(estamos\s+certificados?|certificaci[oó]n\s+ISO|"
            r"certificado\s+ISO|SOC\s*2\s+certificad|ENS\s+certificad)",
            re.IGNORECASE,
        ),
    ),
    (
        "todos los datos residen",
        re.compile(r"todos\s+los\s+datos\s+residen", re.IGNORECASE),
    ),
    (
        "cifrado en reposo activo",
        re.compile(r"cifrado\s+en\s+reposo\s+activo", re.IGNORECASE),
    ),
    (
        "MFA disponible/activo",
        re.compile(r"\bMFA\s+(disponible|activo)\b", re.IGNORECASE),
    ),
    (
        "PITR activo",
        re.compile(r"\bPITR\s+activo\b", re.IGNORECASE),
    ),
    (
        "production ready global afirmativo",
        re.compile(
            r"(?<!no\s)(?<!NO\s)\bproduction\s+ready\b(?!\s*\))",
            re.IGNORECASE,
        ),
    ),
]

# Lines that discuss the ban itself are allowed.
ALLOW_LINE_MARKERS = (
    "prohibid",
    "no afirmar",
    "no se afirma",
    "no declar",
    "no ofrec",
    "no hay",
    "no existe",
    "no dispon",
    "no implement",
    "no está",
    "no estan",
    "no están",
    "sin ",
    "falta",
    "lenguaje",
    "frases prohib",
    "qué no",
    "que no",
    "never",
    "must not",
    "no puede",
    "no deben",
    "no debe",
    "alternativa honesta",
    "estado `not_available`",
    "not_available",
    "needs_deployment_confirmation",
    "borrador",
    "no contractual",
    "sin evidencia",
    "sin certificación",
    "sin certificados",
    "«",  # quoted negative examples in Spanish docs
    "\"",
    "`",
)

LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
VERIFIED_ROW_RE = re.compile(
    r"^\|\s*(C\d+)\s*\|[^|]+\|\s*`verified`\s*\|([^|]+)\|",
    re.MULTILINE,
)
PATH_CANDIDATE_RE = re.compile(
    r"(?:(?:\.\./)?(?:docs|apps|scripts|infra)/[A-Za-z0-9_./\-]+"
    r"|apps/[A-Za-z0-9_./\-]+|scripts/[A-Za-z0-9_./\-]+"
    r"|docs/[A-Za-z0-9_./\-]+)"
)


def fail(errors: list[str], msg: str) -> None:
    errors.append(msg)


def check_presence(errors: list[str]) -> None:
    for name in REQUIRED_DOCS:
        path = LEGAL / name
        if not path.is_file():
            fail(errors, f"missing document: docs/legal/{name}")


def check_headers_and_meta(errors: list[str]) -> None:
    for name in REQUIRED_DOCS:
        path = LEGAL / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        if HEADER not in text:
            fail(errors, f"{name}: missing mandatory BORRADOR header")
        lower = text.lower()
        if "versión" not in lower and "version" not in lower:
            fail(errors, f"{name}: missing version metadata")
        if "owner" not in lower:
            fail(errors, f"{name}: missing owner metadata")
        if "estado" not in lower:
            fail(errors, f"{name}: missing estado metadata")
        if "0.1.0-g21" not in text:
            fail(errors, f"{name}: expected package version 0.1.0-g21")


def _resolve_link(source: Path, target: str) -> Path | None:
    if target.startswith(("http://", "https://", "mailto:", "#")):
        return None
    href = target.split("#", 1)[0].strip()
    if not href:
        return None
    return (source.parent / href).resolve()


def check_relative_links(errors: list[str]) -> None:
    for name in REQUIRED_DOCS:
        path = LEGAL / name
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8")
        for match in LINK_RE.finditer(text):
            target = match.group(2).strip()
            resolved = _resolve_link(path, target)
            if resolved is None:
                continue
            try:
                resolved.relative_to(ROOT.resolve())
            except ValueError:
                # Outside repo — only allow if exists (e.g. absolute mistake)
                fail(errors, f"{name}: link escapes repo: {target}")
                continue
            if not resolved.exists():
                fail(errors, f"{name}: broken relative link -> {target}")


def _line_allowed(line: str) -> bool:
    low = line.lower()
    return any(marker in low for marker in ALLOW_LINE_MARKERS)


def check_adversarial_language(errors: list[str]) -> None:
    for name in REQUIRED_DOCS:
        path = LEGAL / name
        if not path.is_file():
            continue
        for lineno, line in enumerate(
            path.read_text(encoding="utf-8").splitlines(), start=1
        ):
            if _line_allowed(line):
                continue
            for label, pattern in FORBIDDEN_CLAIM_PATTERNS:
                if pattern.search(line):
                    fail(
                        errors,
                        f"{name}:{lineno}: forbidden absolute claim "
                        f"({label}): {line.strip()[:120]}",
                    )


def _extract_evidence_paths(cell: str) -> list[str]:
    paths: list[str] = []
    # markdown links first
    for match in LINK_RE.finditer(cell):
        href = match.group(2).split("#", 1)[0].strip()
        if href and not href.startswith(("http://", "https://", "mailto:")):
            paths.append(href)
    # bare paths
    for match in PATH_CANDIDATE_RE.finditer(cell):
        paths.append(match.group(0))
    # de-dup preserving order
    seen: set[str] = set()
    out: list[str] = []
    for p in paths:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out


def check_verified_evidence(errors: list[str]) -> None:
    matrix = LEGAL / "MATRIZ_CONTROLES_Y_ALEGACIONES.md"
    if not matrix.is_file():
        return
    text = matrix.read_text(encoding="utf-8")
    rows = list(VERIFIED_ROW_RE.finditer(text))
    if len(rows) < 5:
        fail(
            errors,
            f"matrix: expected several verified rows, found {len(rows)}",
        )
    for row in rows:
        control_id = row.group(1)
        evidence_cell = row.group(2)
        paths = _extract_evidence_paths(evidence_cell)
        if not paths:
            # allow code-path mentions without markdown link if cell has backticks paths
            bare = re.findall(
                r"`([^`]+)`",
                evidence_cell,
            )
            for item in bare:
                if "/" in item or item.endswith(".py") or item.endswith(".md"):
                    paths.append(item)
        if not paths:
            fail(
                errors,
                f"matrix {control_id}: verified row has no parseable evidence path",
            )
            continue
        ok_any = False
        for rel in paths:
            # evidence may be relative to docs/legal or repo root
            candidates = [
                (LEGAL / rel).resolve(),
                (ROOT / rel).resolve(),
                (ROOT / "docs" / "legal" / rel).resolve(),
            ]
            # strip leading ./
            rel_clean = rel[2:] if rel.startswith("./") else rel
            candidates.append((ROOT / rel_clean).resolve())
            if any(c.exists() for c in candidates):
                ok_any = True
                break
        if not ok_any:
            fail(
                errors,
                f"matrix {control_id}: verified evidence path missing: {paths}",
            )


def check_min_controls(errors: list[str]) -> None:
    matrix = LEGAL / "MATRIZ_CONTROLES_Y_ALEGACIONES.md"
    if not matrix.is_file():
        return
    text = matrix.read_text(encoding="utf-8")
    control_ids = re.findall(r"^\|\s*(C\d+)\s*\|", text, re.MULTILINE)
    if len(control_ids) < 15:
        fail(errors, f"matrix: need >=15 controls, found {len(control_ids)}")
    non_verified = len(
        re.findall(
            r"\|\s*`(?:partial|planned|not_available|needs_deployment_confirmation)`\s*\|",
            text,
        )
    )
    if non_verified < 5:
        fail(
            errors,
            f"matrix: need >=5 partial/planned/not_available/"
            f"needs_deployment_confirmation rows, found {non_verified}",
        )


def main() -> int:
    errors: list[str] = []
    if not LEGAL.is_dir():
        print("FAIL: docs/legal/ does not exist", file=sys.stderr)
        return 1

    check_presence(errors)
    check_headers_and_meta(errors)
    check_relative_links(errors)
    check_adversarial_language(errors)
    check_verified_evidence(errors)
    check_min_controls(errors)

    if errors:
        print("LEGAL COMPLIANCE PACK VALIDATION: FAIL")
        for err in errors:
            print(f"  - {err}")
        print(f"Total issues: {len(errors)}")
        return 1

    print("LEGAL COMPLIANCE PACK VALIDATION: PASS")
    print(f"  documents: {len(REQUIRED_DOCS)}")
    print(f"  root: {ROOT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
