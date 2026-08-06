"""Deterministic inputs for read-only Oracle↔Signal contract tests."""

from __future__ import annotations

import os
from collections.abc import Mapping, Sequence
from pathlib import Path

SIGNAL_ROOT_ENV_VARS = ("SIGNAL_REPO_ROOT", "OPN_SIGNAL_ROOT")
SIGNAL_CONTRACT_FIXTURE_ROOT = Path(__file__).resolve().parent / "fixtures" / "signal_contract"


def resolve_signal_checkout(
    required_paths: Sequence[str],
    *,
    candidate_roots: Sequence[Path] | None = None,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Resolve a checkout containing every required contract asset or fail closed.

    ``SIGNAL_REPO_ROOT`` (preferred) and ``OPN_SIGNAL_ROOT`` opt into verification
    against a real checkout. Without either, the committed, versioned Oracle test
    fixture is the only default. CI therefore never depends on sibling repositories
    or developer worktrees. An explicitly configured but incomplete checkout never
    falls back silently to the fixture.
    """

    env = os.environ if environ is None else environ
    explicit = next((env.get(name) for name in SIGNAL_ROOT_ENV_VARS if env.get(name)), None)
    roots = (
        [Path(explicit).expanduser()]
        if explicit
        else list(candidate_roots or (SIGNAL_CONTRACT_FIXTURE_ROOT,))
    )
    required = tuple(Path(relative) for relative in required_paths)
    inspected: list[str] = []
    seen: set[str] = set()
    for root in roots:
        identity = str(root.resolve()) if root.exists() else str(root.absolute())
        if identity in seen:
            continue
        seen.add(identity)
        missing = [str(relative) for relative in required if not (root / relative).is_file()]
        if root.is_dir() and not missing:
            return root.resolve()
        inspected.append(f"{root} (missing={missing[:3]!r})")

    required_text = ", ".join(str(path) for path in required)
    inspected_text = "; ".join(inspected) or "<none>"
    raise RuntimeError(
        "Signal contractual checkout unavailable. Set SIGNAL_REPO_ROOT or "
        f"OPN_SIGNAL_ROOT to a checkout containing: {required_text}. "
        f"Inspected: {inspected_text}"
    )


def resolve_explicit_signal_checkout(
    required_paths: Sequence[str],
    *,
    environ: Mapping[str, str] | None = None,
) -> Path | None:
    """Return a validated live checkout only when the caller configured one."""

    env = os.environ if environ is None else environ
    if not any(env.get(name) for name in SIGNAL_ROOT_ENV_VARS):
        return None
    return resolve_signal_checkout(required_paths, environ=env)
