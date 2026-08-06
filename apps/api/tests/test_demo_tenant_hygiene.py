"""Safety gates for the reversible demo hygiene utility."""

from __future__ import annotations

import importlib.util
from pathlib import Path

SCRIPT = Path(__file__).resolve().parents[3] / "scripts" / "demo_tenant_hygiene.py"
SPEC = importlib.util.spec_from_file_location("demo_tenant_hygiene", SCRIPT)
assert SPEC and SPEC.loader
hygiene = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(hygiene)


class _DryRunSession:
    def __init__(self) -> None:
        self.calls: list[tuple[str, str]] = []

    def request(self, method: str, path: str, **_kwargs):
        self.calls.append((method, path))
        if path == "/api/v1/dossiers?page=1&page_size=100":
            return 200, {
                "data": [
                    {
                        "id": "d-qa",
                        "title": "ALTA-HONESTA smoke tip",
                        "status": "active",
                    }
                ]
            }
        if path == "/api/v1/procurement-search-watches":
            return 200, {
                "items": [
                    {
                        "id": "w-qa",
                        "name": "Vigilia UI SCOPE-403",
                        "enabled": True,
                        "notifications_enabled": True,
                        "cadence_seconds": 3600,
                    }
                ]
            }
        raise AssertionError(f"dry-run intentó una llamada mutante: {method} {path}")


def test_real_qa_titles_are_selected_but_demo_goldens_are_preserved() -> None:
    assert hygiene.should_archive("ALTA-HONESTA smoke tip — no mentir FR v2", "active")
    assert hygiene.should_archive("Playwright UAT prueba real", "active")
    assert not hygiene.should_archive("Concurso bomberos", "active")
    assert not hygiene.should_archive("CATL gigafactoría", "active")
    assert not hygiene.should_archive("ALTA-HONESTA smoke tip", "archived")


def test_real_scope_403_watches_are_disabled_reversibly() -> None:
    assert hygiene.should_disable_watch("Vigilia UI SCOPE-403", True, True)
    assert hygiene.should_disable_watch("SCOPE-403 vigilia demo", True, False)
    assert not hygiene.should_disable_watch("Licitaciones de ropa laboral", True, True)
    assert not hygiene.should_disable_watch("Vigilia UI SCOPE-403", False, False)


def test_dry_run_never_calls_detail_archive_or_patch() -> None:
    session = _DryRunSession()
    assert hygiene.archive_junk(session, apply=False) == ["ALTA-HONESTA smoke tip"]
    assert hygiene.disable_junk_watches(session, apply=False) == ["Vigilia UI SCOPE-403"]
    assert session.calls == [
        ("GET", "/api/v1/dossiers?page=1&page_size=100"),
        ("GET", "/api/v1/procurement-search-watches"),
    ]
