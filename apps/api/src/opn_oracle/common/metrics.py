"""Low-cardinality in-process metrics with an explicitly protected scrape endpoint."""

from __future__ import annotations

import hmac
import threading
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

from flask import Blueprint, Response, current_app, request

from opn_oracle.common.request_context import request_log_fields

bp = Blueprint("internal_metrics", __name__, url_prefix="/internal")

_DURATION_BUCKETS = (0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)


def _labels(values: Iterable[tuple[str, str]]) -> str:
    escaped = []
    for name, value in values:
        safe = value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        escaped.append(f'{name}="{safe}"')
    return "{" + ",".join(escaped) + "}"


@dataclass(slots=True)
class DurationAggregate:
    bucket_counts: list[int] = field(default_factory=lambda: [0 for _ in _DURATION_BUCKETS])
    total: float = 0.0
    count: int = 0

    def observe(self, value: float) -> None:
        self.total += value
        self.count += 1
        for index, boundary in enumerate(_DURATION_BUCKETS):
            if value <= boundary:
                self.bucket_counts[index] += 1


@dataclass(slots=True)
class MetricsRegistry:
    """Small registry suitable for one API process and deterministic tests.

    Production with multiple Gunicorn workers must scrape/aggregate every process or replace this
    adapter with the selected telemetry platform. Labels never contain tenant, user or resource IDs.
    """

    requests: dict[tuple[str, str, str], int] = field(default_factory=lambda: defaultdict(int))
    durations: dict[tuple[str, str], DurationAggregate] = field(
        default_factory=lambda: defaultdict(DurationAggregate)
    )
    auth_failures: dict[str, int] = field(default_factory=lambda: defaultdict(int))
    rate_limit_rejections: int = 0
    _lock: threading.Lock = field(default_factory=threading.Lock)

    def observe_request(
        self, *, method: str, route: str, status: int, duration_seconds: float
    ) -> None:
        status_class = f"{status // 100}xx"
        with self._lock:
            self.requests[(method, route, status_class)] += 1
            self.durations[(method, route)].observe(max(0.0, duration_seconds))
            if route.startswith("/api/v1/auth/") and status in {401, 403, 429}:
                self.auth_failures[str(status)] += 1
            if status == 429:
                self.rate_limit_rejections += 1

    def render(self, *, pool_checked_out: int | None = None) -> str:
        lines = [
            "# HELP opn_http_requests_total HTTP requests by templated route and status class.",
            "# TYPE opn_http_requests_total counter",
        ]
        with self._lock:
            requests = sorted(self.requests.items())
            durations = {
                key: (tuple(value.bucket_counts), value.total, value.count)
                for key, value in self.durations.items()
            }
            auth_failures = sorted(self.auth_failures.items())
            rate_limits = self.rate_limit_rejections
        for (method, route, status_class), value in requests:
            label = _labels((("method", method), ("route", route), ("status_class", status_class)))
            lines.append(f"opn_http_requests_total{label} {value}")
        lines.extend(
            (
                "# HELP opn_http_request_duration_seconds HTTP request latency by templated route.",
                "# TYPE opn_http_request_duration_seconds histogram",
            )
        )
        for (method, route), (bucket_counts, total, count) in sorted(durations.items()):
            base = (("method", method), ("route", route))
            for boundary, bucket_count in zip(_DURATION_BUCKETS, bucket_counts, strict=True):
                lines.append(
                    "opn_http_request_duration_seconds_bucket"
                    f"{_labels((*base, ('le', str(boundary))))} {bucket_count}"
                )
            lines.append(
                "opn_http_request_duration_seconds_bucket"
                f"{_labels((*base, ('le', '+Inf')))} {count}"
            )
            lines.append(f"opn_http_request_duration_seconds_sum{_labels(base)} {total:.9f}")
            lines.append(f"opn_http_request_duration_seconds_count{_labels(base)} {count}")
        lines.extend(
            (
                "# HELP opn_auth_failures_total "
                "Authentication/authorization failures on auth routes.",
                "# TYPE opn_auth_failures_total counter",
            )
        )
        for status, value in auth_failures:
            lines.append(f"opn_auth_failures_total{_labels((('status', status),))} {value}")
        lines.extend(
            (
                "# HELP opn_rate_limit_rejections_total Requests rejected by rate limiting.",
                "# TYPE opn_rate_limit_rejections_total counter",
                f"opn_rate_limit_rejections_total {rate_limits}",
            )
        )
        if pool_checked_out is not None:
            lines.extend(
                (
                    "# HELP opn_db_pool_checked_out Current SQLAlchemy checked-out connections.",
                    "# TYPE opn_db_pool_checked_out gauge",
                    f"opn_db_pool_checked_out {pool_checked_out}",
                )
            )
        return "\n".join(lines) + "\n"


def _pool_checked_out() -> int | None:
    try:
        from opn_oracle.extensions import db

        checked_out = getattr(db.engine.pool, "checkedout", None)
        return int(checked_out()) if callable(checked_out) else None
    except (RuntimeError, TypeError, ValueError):
        return None


def init_metrics(app: Any) -> None:
    registry = MetricsRegistry()
    app.extensions["oracle_metrics"] = registry

    @app.after_request
    def observe_response(response: Response) -> Response:
        fields = request_log_fields(response)
        registry.observe_request(
            method=str(fields["method"]),
            route=str(fields["path"]),
            status=int(fields["status"]),
            duration_seconds=float(fields["duration_ms"]) / 1000,
        )
        return response


@bp.get("/metrics")
def metrics() -> Response:
    if not current_app.config["METRICS_ENABLED"]:
        return Response(status=404)
    expected = current_app.config["METRICS_TOKEN"]
    authorization = request.headers.get("Authorization", "")
    supplied = authorization.removeprefix("Bearer ") if authorization.startswith("Bearer ") else ""
    if not expected or not supplied or not hmac.compare_digest(expected, supplied):
        return Response(status=404)
    registry: MetricsRegistry = current_app.extensions["oracle_metrics"]
    return Response(
        registry.render(pool_checked_out=_pool_checked_out()),
        content_type="text/plain; version=0.0.4; charset=utf-8",
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "X-Content-Type-Options": "nosniff",
        },
    )
