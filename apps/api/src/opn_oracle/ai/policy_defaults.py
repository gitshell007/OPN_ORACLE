"""Safe, explicit AI policy provisioned with every new tenant."""

from __future__ import annotations

import uuid
from collections.abc import Mapping
from typing import Any

from opn_oracle.ai.models import AITenantPolicy


def default_ai_policy(tenant_id: uuid.UUID, config: Mapping[str, Any]) -> AITenantPolicy:
    enabled = bool(config.get("AI_ENABLED", False))
    mode = str(config.get("AI_MODE", "disabled")) if enabled else "disabled"
    model = str(config.get("AI_DEFAULT_MODEL", "")).strip()
    # Signal owns model routing per task_key. An empty allowlist avoids pretending
    # Oracle knows the effective primary/fallback models.
    allowed_models = [model] if mode in {"mock", "ollama"} and model else []
    return AITenantPolicy(
        tenant_id=tenant_id,
        enabled=enabled and mode != "disabled",
        provider=mode,
        allowed_models=allowed_models,
        max_classification="public",
        monthly_soft_budget_micros=0,
        monthly_hard_budget_micros=0,
        daily_call_limit=100,
        max_concurrency=2,
        max_context_tokens=8000,
        max_output_tokens=6500,
        kill_switch=not enabled or mode == "disabled",
        redaction_profile={"version": "default-v1", "pii": "block-unreviewed"},
    )
