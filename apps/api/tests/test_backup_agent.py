from __future__ import annotations

import json
from typing import Any

import click
import pytest

from opn_oracle.cli.backup_agent import _validate_backup_name
from opn_oracle.extensions import db


@pytest.mark.parametrize(
    "value",
    ("20260711T180000Z-manual", "backup_001", "abc.tar.zst"),
)
def test_validate_backup_name_accepts_safe_basename(value: str) -> None:
    assert _validate_backup_name(value) == value


@pytest.mark.parametrize("value", ("", "ab", "../backup", "/backup", "backup name", "ábc"))
def test_validate_backup_name_rejects_paths_and_unsafe_names(value: str) -> None:
    with pytest.raises(click.ClickException, match="backup-name no válido"):
        _validate_backup_name(value)


def test_mark_expired_missing_catalogue_entry_is_safe_replay(
    app: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    with app.app_context():
        monkeypatch.setattr(db.session, "scalar", lambda *_args, **_kwargs: None)
        result = app.test_cli_runner().invoke(
            args=["backup-agent", "mark-expired", "--backup-name", "legacy-backup"]
        )
    assert result.exit_code == 0, result.output
    assert json.loads(result.output) == {
        "backup_name": "legacy-backup",
        "transitioned": False,
        "reason": "not_catalogued",
    }
