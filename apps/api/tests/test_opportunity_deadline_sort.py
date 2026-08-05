"""Product contract: opportunity deadline sort keeps nulls last (working week)."""

from __future__ import annotations

from datetime import date

import pytest
from sqlalchemy import Column, Date, Integer, MetaData, String, Table, create_engine, select
from sqlalchemy.dialects import postgresql
from sqlalchemy.orm import Session

from opn_oracle.oracle.service import order_with_nulls_last


@pytest.mark.unit
def test_order_with_nulls_last_compiles_nulls_last_for_postgres() -> None:
    column = Column("deadline", Date)
    for descending in (False, True):
        clause = order_with_nulls_last(column, descending=descending)
        sql = str(
            clause.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True})
        ).upper()
        assert "NULLS LAST" in sql


@pytest.mark.unit
def test_deadline_sort_nulls_last_never_covers_dated_rows() -> None:
    """Asc/desc on deadline: undated opportunities always trail dated ones."""

    metadata = MetaData()
    opportunities = Table(
        "opportunities_sort_probe",
        metadata,
        Column("id", Integer, primary_key=True),
        Column("title", String(80)),
        Column("deadline", Date),
        Column("status", String(40)),
    )

    engine = create_engine("sqlite+pysqlite:///:memory:")
    metadata.create_all(engine)

    with Session(engine) as session:
        rows = [
            (1, "Sin fecha A", None),
            (2, "Vence media", date(2026, 8, 10)),
            (3, "Vence pronto", date(2026, 8, 6)),
            (4, "Sin fecha B", None),
            (5, "Vence tarde", date(2026, 9, 1)),
        ]
        session.execute(
            opportunities.insert(),
            [
                {
                    "id": row_id,
                    "title": title,
                    "deadline": deadline,
                    "status": "identified",
                }
                for row_id, title, deadline in rows
            ],
        )
        session.commit()

        # Same helper list_page / nested and global list use for sort=deadline.
        asc_order = order_with_nulls_last(opportunities.c.deadline, descending=False)
        asc_ids = [
            row[0]
            for row in session.execute(
                select(opportunities.c.id).order_by(asc_order, opportunities.c.id.asc())
            ).all()
        ]
        assert asc_ids[:3] == [3, 2, 5]
        assert set(asc_ids[3:]) == {1, 4}

        desc_order = order_with_nulls_last(opportunities.c.deadline, descending=True)
        desc_ids = [
            row[0]
            for row in session.execute(
                select(opportunities.c.id).order_by(desc_order, opportunities.c.id.asc())
            ).all()
        ]
        assert desc_ids[:3] == [5, 2, 3]
        assert set(desc_ids[3:]) == {1, 4}
