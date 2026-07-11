"""Harden Oracle core authorization, scoring and referential invariants.

Revision ID: 20260710_0005
Revises: 20260710_0004
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "20260710_0005"
down_revision: str | None = "20260710_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "dossier_signals",
        sa.Column("overall_score", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "dossier_signals",
        sa.Column(
            "score_details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.create_unique_constraint(
        "uq_dossier_signals_id_dossier_tenant",
        "dossier_signals",
        ["id", "dossier_id", "tenant_id"],
    )
    op.create_unique_constraint(
        "uq_dossier_signals_signal_dossier_tenant",
        "dossier_signals",
        ["signal_id", "dossier_id", "tenant_id"],
    )
    op.drop_constraint("dossier_signal_scores", "dossier_signals", type_="check")
    op.create_check_constraint(
        "dossier_signal_scores",
        "dossier_signals",
        "relevance BETWEEN 0 AND 100 AND novelty BETWEEN 0 AND 100 "
        "AND confidence BETWEEN 0 AND 100 AND strategic_impact BETWEEN 0 AND 100 "
        "AND overall_score BETWEEN 0 AND 100",
    )
    op.create_table(
        "evidence_dossiers",
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("evidence_id", sa.UUID(), nullable=False),
        sa.Column("dossier_id", sa.UUID(), nullable=False),
        sa.ForeignKeyConstraint(
            ["evidence_id", "tenant_id"],
            ["evidence.id", "evidence.tenant_id"],
            name="fk_evidence_dossier_evidence_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["dossier_id", "tenant_id"],
            ["strategic_dossiers.id", "strategic_dossiers.tenant_id"],
            name="fk_evidence_dossier_dossier_tenant",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("tenant_id", "evidence_id", "dossier_id"),
    )
    op.execute("""
      INSERT INTO evidence_dossiers(tenant_id,evidence_id,dossier_id)
      SELECT e.tenant_id,e.id,ds.dossier_id
      FROM evidence e
      JOIN dossier_signals ds
        ON ds.tenant_id=e.tenant_id AND ds.signal_id=e.signal_id
      ON CONFLICT DO NOTHING
    """)
    op.execute("ALTER TABLE evidence_dossiers ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE evidence_dossiers FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON evidence_dossiers USING "
        "(tenant_id=oracle_current_tenant()) WITH CHECK (tenant_id=oracle_current_tenant())"
    )
    op.execute("""
      DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='oracle_app') THEN
        GRANT SELECT,INSERT,UPDATE,DELETE ON evidence_dossiers TO oracle_app;
      END IF; END $$
    """)

    for table in ("opportunities", "risk_items"):
        op.add_column(table, sa.Column("score_override_reason", sa.String(1000), nullable=True))
        op.add_column(table, sa.Column("score_override_by_user_id", sa.UUID(), nullable=True))
        op.add_column(table, sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column(
        "dossier_actors",
        sa.Column(
            "score_details",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
    )
    op.add_column(
        "dossier_actors", sa.Column("version", sa.Integer(), nullable=False, server_default="1")
    )
    for table in (
        "dossier_objectives",
        "hypotheses",
        "watchlists",
        "signal_monitors",
        "evidence",
        "actors",
        "relationships",
        "insights",
        "feedback",
    ):
        op.add_column(table, sa.Column("version", sa.Integer(), nullable=False, server_default="1"))
    op.add_column("feedback", sa.Column("dossier_id", sa.UUID(), nullable=True))
    op.execute("""
      UPDATE feedback f SET dossier_id = CASE f.target_type
        WHEN 'dossier' THEN f.target_id
        WHEN 'opportunity' THEN (SELECT dossier_id FROM opportunities WHERE id=f.target_id AND tenant_id=f.tenant_id)
        WHEN 'risk' THEN (SELECT dossier_id FROM risk_items WHERE id=f.target_id AND tenant_id=f.tenant_id)
        WHEN 'meeting' THEN (SELECT dossier_id FROM meetings WHERE id=f.target_id AND tenant_id=f.tenant_id)
        WHEN 'task' THEN (SELECT dossier_id FROM tasks WHERE id=f.target_id AND tenant_id=f.tenant_id)
        WHEN 'insight' THEN (SELECT dossier_id FROM insights WHERE id=f.target_id AND tenant_id=f.tenant_id)
        ELSE NULL END
    """)
    op.execute("""
      DO $$ BEGIN
        IF EXISTS (SELECT 1 FROM feedback WHERE dossier_id IS NULL) THEN
          RAISE EXCEPTION 'Feedback rows need an explicit dossier before phase 06 hardening';
        END IF;
      END $$
    """)
    op.alter_column("feedback", "dossier_id", nullable=False)
    op.create_foreign_key(
        "fk_feedback_dossier_tenant",
        "feedback",
        "strategic_dossiers",
        ["dossier_id", "tenant_id"],
        ["id", "tenant_id"],
        ondelete="CASCADE",
    )
    for table in ("meetings", "decisions", "tasks"):
        op.add_column(table, sa.Column("version", sa.Integer(), nullable=False, server_default="1"))

    op.execute("UPDATE meetings SET status='planned' WHERE status='open'")
    op.execute("UPDATE decisions SET status='proposed' WHERE status='open'")
    op.execute("UPDATE insights SET status='draft' WHERE status='open'")
    op.execute("UPDATE reports SET status='pending' WHERE status='open'")
    op.execute("""
      UPDATE opportunities o SET
        score_override_reason=COALESCE(score_override_reason,'Migrated legacy override'),
        score_override_by_user_id=COALESCE(
          score_override_by_user_id,
          CASE WHEN EXISTS (
            SELECT 1 FROM tenant_memberships tm
            WHERE tm.tenant_id=o.tenant_id AND tm.user_id=o.owner_user_id
          ) THEN o.owner_user_id ELSE NULL END
        )
      WHERE score_override IS NOT NULL
    """)
    op.execute("""
      UPDATE risk_items r SET
        score_override_reason=COALESCE(score_override_reason,'Migrated legacy override'),
        score_override_by_user_id=COALESCE(
          score_override_by_user_id,
          CASE WHEN EXISTS (
            SELECT 1 FROM tenant_memberships tm
            WHERE tm.tenant_id=r.tenant_id AND tm.user_id=r.owner_user_id
          ) THEN r.owner_user_id ELSE NULL END
        )
      WHERE score_override IS NOT NULL
    """)
    op.execute("""
      DO $$ BEGIN
        IF EXISTS (
          SELECT 1 FROM opportunities WHERE score_override IS NOT NULL
            AND (score_override_reason IS NULL OR score_override_by_user_id IS NULL)
        ) OR EXISTS (
          SELECT 1 FROM risk_items WHERE score_override IS NOT NULL
            AND (score_override_reason IS NULL OR score_override_by_user_id IS NULL)
        ) THEN RAISE EXCEPTION 'Legacy score overrides require an attributable tenant member';
        END IF;
        IF EXISTS (
          SELECT 1 FROM strategic_dossiers d WHERE d.owner_user_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM tenant_memberships tm
            WHERE tm.tenant_id=d.tenant_id AND tm.user_id=d.owner_user_id
          )
        ) OR EXISTS (
          SELECT 1 FROM opportunities o WHERE o.owner_user_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM tenant_memberships tm
            WHERE tm.tenant_id=o.tenant_id AND tm.user_id=o.owner_user_id
          )
        ) OR EXISTS (
          SELECT 1 FROM risk_items r WHERE r.owner_user_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM tenant_memberships tm
            WHERE tm.tenant_id=r.tenant_id AND tm.user_id=r.owner_user_id
          )
        ) OR EXISTS (
          SELECT 1 FROM tasks t WHERE t.owner_user_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM tenant_memberships tm
            WHERE tm.tenant_id=t.tenant_id AND tm.user_id=t.owner_user_id
          )
        ) OR EXISTS (
          SELECT 1 FROM dossier_collaborators c WHERE NOT EXISTS (
            SELECT 1 FROM tenant_memberships tm
            WHERE tm.tenant_id=c.tenant_id AND tm.user_id=c.user_id
          )
        ) OR EXISTS (
          SELECT 1 FROM dossier_signals ds WHERE ds.reviewer_user_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM tenant_memberships tm
            WHERE tm.tenant_id=ds.tenant_id AND tm.user_id=ds.reviewer_user_id
          )
        ) OR EXISTS (
          SELECT 1 FROM decisions d WHERE d.decided_by_user_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM tenant_memberships tm
            WHERE tm.tenant_id=d.tenant_id AND tm.user_id=d.decided_by_user_id
          )
        ) OR EXISTS (
          SELECT 1 FROM reports r WHERE r.generated_by_user_id IS NOT NULL AND NOT EXISTS (
            SELECT 1 FROM tenant_memberships tm
            WHERE tm.tenant_id=r.tenant_id AND tm.user_id=r.generated_by_user_id
          )
        ) THEN RAISE EXCEPTION 'Oracle owners must belong to the same tenant';
        END IF;
      END $$
    """)

    op.create_table(
        "status_history",
        sa.Column("dossier_id", sa.UUID(), nullable=False),
        sa.Column("resource_type", sa.String(50), nullable=False),
        sa.Column("resource_id", sa.UUID(), nullable=False),
        sa.Column("from_status", sa.String(40), nullable=False),
        sa.Column("to_status", sa.String(40), nullable=False),
        sa.Column("actor_user_id", sa.UUID(), nullable=False),
        sa.Column("reason", sa.String(1000), nullable=False, server_default=""),
        sa.Column("tenant_id", sa.UUID(), nullable=False),
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(["tenant_id"], ["tenants.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["dossier_id", "tenant_id"],
            ["strategic_dossiers.id", "strategic_dossiers.tenant_id"],
            name="fk_status_history_dossier_tenant",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["tenant_id", "actor_user_id"],
            ["tenant_memberships.tenant_id", "tenant_memberships.user_id"],
            name="fk_status_history_actor_membership",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_status_history_resource",
        "status_history",
        ["tenant_id", "resource_type", "resource_id", "created_at"],
    )
    op.execute("ALTER TABLE status_history ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE status_history FORCE ROW LEVEL SECURITY")
    op.execute(
        "CREATE POLICY tenant_isolation ON status_history USING "
        "(tenant_id=oracle_current_tenant()) WITH CHECK (tenant_id=oracle_current_tenant())"
    )
    op.execute("""
      DO $$ BEGIN IF EXISTS(SELECT 1 FROM pg_roles WHERE rolname='oracle_app') THEN
        GRANT SELECT,INSERT,UPDATE,DELETE ON status_history TO oracle_app;
      END IF; END $$
    """)

    checks = (
        (
            "opportunities",
            "opportunity_status",
            "status IN ('identified','qualified','pursuing','won','lost','dismissed')",
        ),
        (
            "opportunities",
            "opportunity_version_positive",
            "version >= 1",
        ),
        (
            "opportunities",
            "opportunity_override_attribution",
            "score_override IS NULL OR (score_override_reason IS NOT NULL "
            "AND score_override_by_user_id IS NOT NULL)",
        ),
        (
            "risk_items",
            "risk_status",
            "status IN ('open','monitoring','mitigated','accepted','closed')",
        ),
        ("risk_items", "risk_version_positive", "version >= 1"),
        (
            "risk_items",
            "risk_override_attribution",
            "score_override IS NULL OR (score_override_reason IS NOT NULL "
            "AND score_override_by_user_id IS NOT NULL)",
        ),
        (
            "dossier_actors",
            "dossier_actor_scores",
            "influence BETWEEN 0 AND 100 AND relevance_to_dossier BETWEEN 0 AND 100 "
            "AND relationship_strength BETWEEN 0 AND 100 AND accessibility BETWEEN 0 AND 100 "
            "AND strategic_alignment BETWEEN 0 AND 100 AND recent_activity BETWEEN 0 AND 100 "
            "AND priority BETWEEN 0 AND 100",
        ),
        ("dossier_actors", "dossier_actor_version_positive", "version >= 1"),
        ("dossier_objectives", "objective_version_positive", "version >= 1"),
        ("hypotheses", "hypothesis_version_positive", "version >= 1"),
        ("watchlists", "watchlist_version_positive", "version >= 1"),
        ("signal_monitors", "signal_monitor_version_positive", "version >= 1"),
        ("evidence", "evidence_version_positive", "version >= 1"),
        ("actors", "actor_version_positive", "version >= 1"),
        ("relationships", "relationship_version_positive", "version >= 1"),
        ("insights", "insight_version_positive", "version >= 1"),
        ("feedback", "feedback_version_positive", "version >= 1"),
        ("watchlists", "watchlist_status", "status IN ('active','paused','archived')"),
        (
            "signal_monitors",
            "signal_monitor_status",
            "status IN ('active','paused','error')",
        ),
        ("meetings", "meeting_status", "status IN ('planned','completed','cancelled')"),
        ("meetings", "meeting_version_positive", "version >= 1"),
        (
            "decisions",
            "decision_status",
            "status IN ('proposed','approved','rejected','superseded')",
        ),
        ("decisions", "decision_version_positive", "version >= 1"),
        (
            "tasks",
            "task_status",
            "status IN ('open','in_progress','blocked','done','cancelled')",
        ),
        ("tasks", "task_version_positive", "version >= 1"),
        ("insights", "insight_status", "status IN ('draft','valid','rejected')"),
        (
            "reports",
            "report_status",
            "status IN ('pending','generating','completed','failed')",
        ),
        (
            "strategic_dossiers",
            "dossier_scoring_config_object",
            "jsonb_typeof(scoring_config) = 'object'",
        ),
    )
    for table, name, condition in checks:
        op.create_check_constraint(name, table, condition)

    op.create_unique_constraint("uq_ai_audit_logs_id_tenant", "ai_audit_logs", ["id", "tenant_id"])
    foreign_keys = (
        (
            "fk_dossier_collaborator_membership",
            "dossier_collaborators",
            "tenant_memberships",
            ["tenant_id", "user_id"],
            ["tenant_id", "user_id"],
            "CASCADE",
        ),
        (
            "fk_dossiers_owner_membership",
            "strategic_dossiers",
            "tenant_memberships",
            ["tenant_id", "owner_user_id"],
            ["tenant_id", "user_id"],
            None,
        ),
        (
            "fk_dossier_signals_reviewer_membership",
            "dossier_signals",
            "tenant_memberships",
            ["tenant_id", "reviewer_user_id"],
            ["tenant_id", "user_id"],
            None,
        ),
        (
            "fk_opportunities_owner_membership",
            "opportunities",
            "tenant_memberships",
            ["tenant_id", "owner_user_id"],
            ["tenant_id", "user_id"],
            None,
        ),
        (
            "fk_opportunities_override_membership",
            "opportunities",
            "tenant_memberships",
            ["tenant_id", "score_override_by_user_id"],
            ["tenant_id", "user_id"],
            None,
        ),
        (
            "fk_risks_owner_membership",
            "risk_items",
            "tenant_memberships",
            ["tenant_id", "owner_user_id"],
            ["tenant_id", "user_id"],
            None,
        ),
        (
            "fk_risks_override_membership",
            "risk_items",
            "tenant_memberships",
            ["tenant_id", "score_override_by_user_id"],
            ["tenant_id", "user_id"],
            None,
        ),
        (
            "fk_tasks_owner_membership",
            "tasks",
            "tenant_memberships",
            ["tenant_id", "owner_user_id"],
            ["tenant_id", "user_id"],
            None,
        ),
        (
            "fk_decisions_actor_membership",
            "decisions",
            "tenant_memberships",
            ["tenant_id", "decided_by_user_id"],
            ["tenant_id", "user_id"],
            None,
        ),
        (
            "fk_reports_generator_membership",
            "reports",
            "tenant_memberships",
            ["tenant_id", "generated_by_user_id"],
            ["tenant_id", "user_id"],
            None,
        ),
        (
            "fk_opportunities_source_signal_context",
            "opportunities",
            "dossier_signals",
            ["source_dossier_signal_id", "dossier_id", "tenant_id"],
            ["id", "dossier_id", "tenant_id"],
            None,
        ),
        (
            "fk_risks_source_signal_context",
            "risk_items",
            "dossier_signals",
            ["source_dossier_signal_id", "dossier_id", "tenant_id"],
            ["id", "dossier_id", "tenant_id"],
            None,
        ),
        (
            "fk_background_jobs_dossier_tenant",
            "background_jobs",
            "strategic_dossiers",
            ["dossier_id", "tenant_id"],
            ["id", "tenant_id"],
            "CASCADE",
        ),
        (
            "fk_ai_audit_logs_dossier_tenant",
            "ai_audit_logs",
            "strategic_dossiers",
            ["dossier_id", "tenant_id"],
            ["id", "tenant_id"],
            "CASCADE",
        ),
        (
            "fk_score_history_dossier_tenant",
            "score_history",
            "strategic_dossiers",
            ["dossier_id", "tenant_id"],
            ["id", "tenant_id"],
            "CASCADE",
        ),
        (
            "fk_insights_ai_audit_tenant",
            "insights",
            "ai_audit_logs",
            ["ai_audit_log_id", "tenant_id"],
            ["id", "tenant_id"],
            None,
        ),
    )
    for name, source, target, local, remote, ondelete in foreign_keys:
        op.create_foreign_key(name, source, target, local, remote, ondelete=ondelete)


def downgrade() -> None:
    op.drop_index("ix_status_history_resource", table_name="status_history")
    op.drop_table("status_history")
    op.drop_constraint("fk_feedback_dossier_tenant", "feedback", type_="foreignkey")
    op.drop_column("feedback", "dossier_id")
    op.drop_table("evidence_dossiers")
    foreign_keys = (
        ("fk_insights_ai_audit_tenant", "insights"),
        ("fk_score_history_dossier_tenant", "score_history"),
        ("fk_ai_audit_logs_dossier_tenant", "ai_audit_logs"),
        ("fk_background_jobs_dossier_tenant", "background_jobs"),
        ("fk_risks_source_signal_context", "risk_items"),
        ("fk_opportunities_source_signal_context", "opportunities"),
        ("fk_reports_generator_membership", "reports"),
        ("fk_decisions_actor_membership", "decisions"),
        ("fk_tasks_owner_membership", "tasks"),
        ("fk_risks_override_membership", "risk_items"),
        ("fk_risks_owner_membership", "risk_items"),
        ("fk_opportunities_override_membership", "opportunities"),
        ("fk_opportunities_owner_membership", "opportunities"),
        ("fk_dossier_signals_reviewer_membership", "dossier_signals"),
        ("fk_dossiers_owner_membership", "strategic_dossiers"),
        ("fk_dossier_collaborator_membership", "dossier_collaborators"),
    )
    for name, table in foreign_keys:
        op.drop_constraint(name, table, type_="foreignkey")
    op.drop_constraint("uq_ai_audit_logs_id_tenant", "ai_audit_logs", type_="unique")

    checks = (
        ("report_status", "reports"),
        ("insight_status", "insights"),
        ("task_version_positive", "tasks"),
        ("task_status", "tasks"),
        ("decision_version_positive", "decisions"),
        ("decision_status", "decisions"),
        ("meeting_version_positive", "meetings"),
        ("meeting_status", "meetings"),
        ("signal_monitor_status", "signal_monitors"),
        ("watchlist_status", "watchlists"),
        ("dossier_actor_scores", "dossier_actors"),
        ("dossier_actor_version_positive", "dossier_actors"),
        ("objective_version_positive", "dossier_objectives"),
        ("hypothesis_version_positive", "hypotheses"),
        ("watchlist_version_positive", "watchlists"),
        ("signal_monitor_version_positive", "signal_monitors"),
        ("evidence_version_positive", "evidence"),
        ("actor_version_positive", "actors"),
        ("relationship_version_positive", "relationships"),
        ("insight_version_positive", "insights"),
        ("feedback_version_positive", "feedback"),
        ("risk_override_attribution", "risk_items"),
        ("risk_version_positive", "risk_items"),
        ("risk_status", "risk_items"),
        ("opportunity_override_attribution", "opportunities"),
        ("opportunity_version_positive", "opportunities"),
        ("opportunity_status", "opportunities"),
        ("dossier_scoring_config_object", "strategic_dossiers"),
    )
    for name, table in checks:
        op.drop_constraint(name, table, type_="check")

    for table in ("tasks", "decisions", "meetings"):
        op.drop_column(table, "version")
    op.drop_column("dossier_actors", "score_details")
    op.drop_column("dossier_actors", "version")
    for table in (
        "feedback",
        "insights",
        "relationships",
        "actors",
        "evidence",
        "signal_monitors",
        "watchlists",
        "hypotheses",
        "dossier_objectives",
    ):
        op.drop_column(table, "version")
    for table in ("risk_items", "opportunities"):
        op.drop_column(table, "version")
        op.drop_column(table, "score_override_by_user_id")
        op.drop_column(table, "score_override_reason")
    op.drop_constraint("uq_dossier_signals_id_dossier_tenant", "dossier_signals", type_="unique")
    op.drop_constraint(
        "uq_dossier_signals_signal_dossier_tenant", "dossier_signals", type_="unique"
    )
    op.drop_constraint("dossier_signal_scores", "dossier_signals", type_="check")
    op.create_check_constraint(
        "dossier_signal_scores",
        "dossier_signals",
        "relevance BETWEEN 0 AND 100 AND novelty BETWEEN 0 AND 100 "
        "AND confidence BETWEEN 0 AND 100 AND strategic_impact BETWEEN 0 AND 100",
    )
    op.drop_column("dossier_signals", "score_details")
    op.drop_column("dossier_signals", "overall_score")
