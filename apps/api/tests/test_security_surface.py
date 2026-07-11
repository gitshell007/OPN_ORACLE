"""Cross-cutting security invariants for the complete Flask route surface."""

from __future__ import annotations

import re
import uuid
from collections import defaultdict
from typing import Any

import pytest
from flask import Flask

MUTATING_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def _normalized_rule(rule: str) -> str:
    return re.sub(r"<(?:[^:>]+:)?[^>]+>", "{}", rule)


def _concrete_path(rule: Any) -> str:
    path = rule.rule
    placeholders = re.compile(r"<(?:([^:>]+):)?([^>]+)>")

    def replacement(match: re.Match[str]) -> str:
        converter, argument = match.groups()
        if converter == "uuid":
            value = str(uuid.UUID(int=0))
        elif argument == "action":
            value = "pause"
        elif argument == "agent":
            value = "signal_triage"
        else:
            value = "security-canary"
        return value

    return placeholders.sub(replacement, path)


@pytest.mark.unit
def test_route_map_has_one_authoritative_handler_per_method_and_path(app: Flask) -> None:
    routes: dict[tuple[str, str], list[str]] = defaultdict(list)
    for rule in app.url_map.iter_rules():
        for method in rule.methods - {"HEAD", "OPTIONS"}:
            routes[(method, _normalized_rule(rule.rule))].append(rule.endpoint)

    ambiguous = {key: endpoints for key, endpoints in routes.items() if len(endpoints) > 1}
    assert ambiguous == {}

    endpoint, values = app.url_map.bind("").match(
        f"/api/v1/signal-monitors/{uuid.UUID(int=0)}", method="PATCH"
    )
    assert endpoint == "signal_integrations.update_monitor"
    assert values == {"monitor_id": uuid.UUID(int=0)}


@pytest.mark.unit
def test_every_browser_mutation_is_csrf_protected_by_default(app: Flask, client: Any) -> None:
    checked: set[tuple[str, str]] = set()
    for rule in app.url_map.iter_rules():
        if rule.endpoint == "signal_webhooks.webhook":
            continue
        for method in sorted(rule.methods & MUTATING_METHODS):
            path = _concrete_path(rule)
            response = client.open(path, method=method)
            checked.add((method, _normalized_rule(rule.rule)))
            assert response.status_code == 403, (method, rule.rule, response.get_data(as_text=True))
            assert response.is_json, (method, rule.rule)
            assert response.get_json()["code"] == "csrf_failed", (method, rule.rule)

    declared = {
        (method, _normalized_rule(rule.rule))
        for rule in app.url_map.iter_rules()
        if rule.endpoint != "signal_webhooks.webhook"
        for method in rule.methods & MUTATING_METHODS
    }
    assert checked == declared
