"""Platform-wide official source publication activity (BORME, BOE, …).

Superadmins need a daily trail of whether gazettes appeared and how many
items they expose. Counts come from the BOE open-data API (authoritative
publication). Signal's registry is a consumer; when a provider status API
exists it can be attached later without changing this surface.
"""

from __future__ import annotations

import json
import re
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import Any, TypeVar
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

from sqlalchemy import Date, DateTime, Index, Integer, String, Text, UniqueConstraint, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, Session, mapped_column, scoped_session

from opn_oracle.extensions import Base
from opn_oracle.platform.models import TimestampMixin, UUIDPrimaryKeyMixin

SOURCE_KEYS = frozenset({"borme", "boe"})
SOURCE_LABELS = {
    "borme": "BORME",
    "boe": "BOE",
}
_SUMARIO_URL = "https://www.boe.es/datosabiertos/api/{source}/sumario/{yyyymmdd}"
_ID_PREFIX = {
    "borme": re.compile(r"^BORME-[ABC]-"),
    "boe": re.compile(r"^BOE-[AB]-"),
}
_MADRID = ZoneInfo("Europe/Madrid")
SessionT = TypeVar("SessionT", bound=Session)
SessionProvider = Session | scoped_session[SessionT]


class PlatformSourceActivity(UUIDPrimaryKeyMixin, TimestampMixin, Base):
    """One observation of an official gazette day for a source."""

    __tablename__ = "platform_source_activity"
    __table_args__ = (
        UniqueConstraint("source_key", "activity_date", name="uq_platform_source_activity_day"),
        Index("ix_platform_source_activity_checked", "checked_at"),
        Index("ix_platform_source_activity_source_date", "source_key", "activity_date"),
    )

    source_key: Mapped[str] = mapped_column(String(40), nullable=False)
    activity_date: Mapped[date] = mapped_column(Date, nullable=False)
    status: Mapped[str] = mapped_column(String(30), nullable=False)
    item_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    section_counts: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    official_identifier: Mapped[str | None] = mapped_column(String(120))
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    error_message: Mapped[str | None] = mapped_column(Text)
    checked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    raw_meta: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)


def _collect_identifiers(payload: Any) -> list[str]:
    found: list[str] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            ident = value.get("identificador")
            if isinstance(ident, str) and ident:
                found.append(ident)
            for child in value.values():
                walk(child)
        elif isinstance(value, list):
            for child in value:
                walk(child)

    walk(payload)
    return found


def _section_counts(identifiers: list[str], *, source: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for ident in identifiers:
        parts = ident.split("-")
        if len(parts) < 2:
            continue
        section = parts[1]
        allowed = {"A", "B", "C", "S"} if source == "borme" else {"A", "B", "S"}
        if section in allowed:
            counts[section] = counts.get(section, 0) + 1
    return counts


def fetch_official_sumario(
    source: str, day: date, *, timeout_seconds: float = 20.0
) -> dict[str, Any]:
    """Return a normalized observation for one source/day from BOE open data."""

    if source not in SOURCE_KEYS:
        raise ValueError(f"Fuente no soportada: {source}")
    yyyymmdd = day.strftime("%Y%m%d")
    url = _SUMARIO_URL.format(source=source, yyyymmdd=yyyymmdd)
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "OPN-Oracle/1.0"})
    try:
        with urlopen(request, timeout=timeout_seconds) as response:
            body = response.read()
            status_code = getattr(response, "status", 200)
    except HTTPError as exc:
        if exc.code == 404:
            return {
                "status": "not_published",
                "item_count": 0,
                "section_counts": {},
                "official_identifier": None,
                "detail": f"Sin sumario {SOURCE_LABELS[source]} para {day.isoformat()}.",
                "error_message": None,
                "raw_meta": {"http_status": 404, "url": url},
            }
        return {
            "status": "error",
            "item_count": 0,
            "section_counts": {},
            "official_identifier": None,
            "detail": f"Error HTTP {exc.code} al consultar {SOURCE_LABELS[source]}.",
            "error_message": str(exc.reason or exc)[:500],
            "raw_meta": {"http_status": exc.code, "url": url},
        }
    except (URLError, TimeoutError, OSError) as exc:
        return {
            "status": "error",
            "item_count": 0,
            "section_counts": {},
            "official_identifier": None,
            "detail": (
                "No se pudo contactar con la API de datos abiertos del BOE "
                f"({SOURCE_LABELS[source]})."
            ),
            "error_message": str(exc)[:500],
            "raw_meta": {"url": url},
        }

    try:
        payload = json.loads(body.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        return {
            "status": "error",
            "item_count": 0,
            "section_counts": {},
            "official_identifier": None,
            "detail": f"Respuesta no JSON del sumario {SOURCE_LABELS[source]}.",
            "error_message": str(exc)[:500],
            "raw_meta": {"http_status": status_code, "url": url},
        }

    identifiers = _collect_identifiers(payload)
    content_re = _ID_PREFIX[source]
    content_ids = [item for item in identifiers if content_re.match(item)]
    sections = _section_counts(identifiers, source=source)
    diary_id = next((item for item in identifiers if "-S-" in item), None)

    return {
        "status": "published",
        "item_count": len(content_ids),
        "section_counts": sections,
        "official_identifier": diary_id,
        "detail": (
            f"{SOURCE_LABELS[source]} del {day.isoformat()}: "
            f"{len(content_ids)} registros de contenido"
            + (
                f" ({', '.join(f'{k}:{v}' for k, v in sorted(sections.items()))})"
                if sections
                else ""
            )
            + "."
        ),
        "error_message": None,
        "raw_meta": {
            "http_status": status_code,
            "url": url,
            "identifier_total": len(identifiers),
            "content_total": len(content_ids),
        },
    }


def upsert_observation(
    session: SessionProvider[SessionT],
    *,
    source: str,
    day: date,
    observation: dict[str, Any],
    checked_at: datetime | None = None,
) -> PlatformSourceActivity:
    now = checked_at or datetime.now(UTC)
    row = session.scalar(
        select(PlatformSourceActivity).where(
            PlatformSourceActivity.source_key == source,
            PlatformSourceActivity.activity_date == day,
        )
    )
    if row is None:
        row = PlatformSourceActivity(
            id=uuid.uuid4(),
            source_key=source,
            activity_date=day,
            status=str(observation["status"]),
            item_count=int(observation["item_count"]),
            section_counts=dict(observation.get("section_counts") or {}),
            official_identifier=observation.get("official_identifier"),
            detail=str(observation.get("detail") or "")[:2000],
            error_message=observation.get("error_message"),
            checked_at=now,
            raw_meta=dict(observation.get("raw_meta") or {}),
        )
        session.add(row)
    else:
        row.status = str(observation["status"])
        row.item_count = int(observation["item_count"])
        row.section_counts = dict(observation.get("section_counts") or {})
        row.official_identifier = observation.get("official_identifier")
        row.detail = str(observation.get("detail") or "")[:2000]
        row.error_message = observation.get("error_message")
        row.checked_at = now
        row.raw_meta = dict(observation.get("raw_meta") or {})
    return row


def poll_source_activity(
    session: SessionProvider[SessionT],
    *,
    lookback_days: int = 14,
    sources: tuple[str, ...] = ("borme", "boe"),
    as_of: date | None = None,
) -> list[PlatformSourceActivity]:
    """Refresh official gazette observations for recent calendar days."""

    today = as_of or datetime.now(_MADRID).date()
    lookback = max(1, min(int(lookback_days), 60))
    rows: list[PlatformSourceActivity] = []
    checked_at = datetime.now(UTC)
    for offset in range(lookback):
        day = today - timedelta(days=offset)
        for source in sources:
            if source not in SOURCE_KEYS:
                continue
            observation = fetch_official_sumario(source, day)
            rows.append(
                upsert_observation(
                    session,
                    source=source,
                    day=day,
                    observation=observation,
                    checked_at=checked_at,
                )
            )
    session.commit()
    return rows


def serialize_activity(row: PlatformSourceActivity) -> dict[str, Any]:
    return {
        "id": str(row.id),
        "source_key": row.source_key,
        "source_label": SOURCE_LABELS.get(row.source_key, row.source_key.upper()),
        "activity_date": row.activity_date.isoformat(),
        "status": row.status,
        "item_count": row.item_count,
        "section_counts": row.section_counts or {},
        "official_identifier": row.official_identifier,
        "detail": row.detail,
        "error_message": row.error_message,
        "checked_at": row.checked_at.isoformat() if row.checked_at else None,
        "created_at": row.created_at.isoformat() if row.created_at else None,
        "updated_at": row.updated_at.isoformat() if row.updated_at else None,
    }


def list_source_activity(
    session: SessionProvider[SessionT],
    *,
    source: str | None = None,
    search: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    sort: str = "activity_date",
    direction: str = "desc",
    limit: int = 200,
) -> list[PlatformSourceActivity]:
    query = select(PlatformSourceActivity)
    if source and source in SOURCE_KEYS:
        query = query.where(PlatformSourceActivity.source_key == source)
    if date_from is not None:
        query = query.where(PlatformSourceActivity.activity_date >= date_from)
    if date_to is not None:
        query = query.where(PlatformSourceActivity.activity_date <= date_to)
    sort_map = {
        "activity_date": PlatformSourceActivity.activity_date,
        "checked_at": PlatformSourceActivity.checked_at,
        "item_count": PlatformSourceActivity.item_count,
        "source_key": PlatformSourceActivity.source_key,
        "status": PlatformSourceActivity.status,
    }
    column = sort_map.get(sort, PlatformSourceActivity.activity_date)
    query = query.order_by(column.asc() if direction == "asc" else column.desc())
    rows = list(session.scalars(query.limit(min(max(limit, 1), 500))))
    if search:
        needle = search.strip().casefold()
        if needle:
            rows = [
                row
                for row in rows
                if needle
                in " ".join(
                    [
                        row.source_key,
                        SOURCE_LABELS.get(row.source_key, ""),
                        row.status,
                        row.detail or "",
                        row.official_identifier or "",
                        str(row.item_count),
                    ]
                ).casefold()
            ]
    return rows
