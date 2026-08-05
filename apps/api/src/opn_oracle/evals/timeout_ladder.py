"""Oracle effective timeout ladder (MDEV-09).

Invariant:
  provider_attempt < signal_request_deadline < oracle_http_retry_budget
  < celery_soft < celery_hard < lease_reconciler
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class OracleTimeoutLadder:
    provider_attempt_seconds: float
    signal_request_deadline_seconds: float
    oracle_http_retry_budget_seconds: float
    celery_soft_seconds: float
    celery_hard_seconds: float
    lease_reconciler_seconds: float

    def as_dict(self) -> dict[str, float]:
        return {
            "provider_attempt_seconds": self.provider_attempt_seconds,
            "signal_request_deadline_seconds": self.signal_request_deadline_seconds,
            "oracle_http_retry_budget_seconds": self.oracle_http_retry_budget_seconds,
            "celery_soft_seconds": self.celery_soft_seconds,
            "celery_hard_seconds": self.celery_hard_seconds,
            "lease_reconciler_seconds": self.lease_reconciler_seconds,
        }

    def violations(self) -> list[str]:
        seq = list(self.as_dict().items())
        bad: list[str] = []
        for i in range(len(seq) - 1):
            na, a = seq[i]
            nb, b = seq[i + 1]
            if not (a < b):
                bad.append(f"{na}={a} !< {nb}={b}")
        return bad

    def assert_valid(self) -> None:
        bad = self.violations()
        if bad:
            raise ValueError("timeout ladder invalid: " + "; ".join(bad))


def oracle_timeout_ladder(
    *,
    signal_ai_timeout: float = 300.0,
    celery_soft: float = 690.0,
    celery_hard: float = 720.0,
    lease_extra: float = 60.0,
    provider_attempt: float = 240.0,
) -> OracleTimeoutLadder:
    """Effective defaults from opn_oracle.config + jobs lease formula.

    Observed:
    - SIGNAL_AI_TIMEOUT_SECONDS = 300
    - CELERY_TASK_SOFT_TIME_LIMIT = 690
    - CELERY_TASK_TIME_LIMIT = 720
    - lease = CELERY_TASK_TIME_LIMIT + 60 = 780

    provider_attempt aligned to 240 (strict < signal deadline) rather than
    inflating outer timeouts.
    """

    signal_deadline = float(signal_ai_timeout)
    # Retry budget sits between Signal deadline and Celery soft.
    retry_budget = min(float(celery_soft) - 10.0, signal_deadline + 120.0)
    if not (provider_attempt < signal_deadline):
        provider_attempt = max(1.0, signal_deadline - 30.0)
    if not (signal_deadline < retry_budget):
        retry_budget = min(celery_soft - 10.0, signal_deadline + 60.0)
    ladder = OracleTimeoutLadder(
        provider_attempt_seconds=float(provider_attempt),
        signal_request_deadline_seconds=signal_deadline,
        oracle_http_retry_budget_seconds=float(retry_budget),
        celery_soft_seconds=float(celery_soft),
        celery_hard_seconds=float(celery_hard),
        lease_reconciler_seconds=float(celery_hard) + float(lease_extra),
    )
    ladder.assert_valid()
    return ladder


def ladder_document() -> dict[str, Any]:
    ladder = oracle_timeout_ladder()
    return {
        "ladder": ladder.as_dict(),
        "violations": ladder.violations(),
        "invariant": (
            "provider_attempt < signal_request_deadline < oracle_http_retry_budget "
            "< celery_soft < celery_hard < lease_reconciler"
        ),
        "config_keys": {
            "SIGNAL_AI_TIMEOUT_SECONDS": 300.0,
            "CELERY_TASK_SOFT_TIME_LIMIT": 690,
            "CELERY_TASK_TIME_LIMIT": 720,
            "lease_formula": "CELERY_TASK_TIME_LIMIT + 60",
            "provider_attempt_budget_aligned": 240.0,
        },
    }
