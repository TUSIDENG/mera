"""initial M02 schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-10-13
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

FETCH_STATUSES = (
    "pending",
    "running",
    "succeeded",
    "partial_succeeded",
    "failed_exhausted",
    "captcha_pending",
)
EVALUATION_STATUSES = ("awaiting_data", "awaiting_confirmation", "completed", "failed")
COST_TYPES = ("gpu_rental", "gpu_purchase", "cpu", "electricity", "colocation", "bandwidth")
BILLING_CYCLES = ("monthly", "yearly")
PLAN_SOURCES = ("manual", "fetch")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'authenticated_users') THEN
                CREATE ROLE authenticated_users NOLOGIN;
            END IF;
        END
        $$
        """
    )

    op.create_table(
        "model_snapshots",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("domain", sa.String(length=50), nullable=False),
        sa.Column("benchmark_score", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint("benchmark_score >= 0", name="ck_model_snapshot_score_non_negative"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_id", "domain", name="uq_model_snapshot"),
    )
    op.create_index(
        "idx_model_snapshot_domain",
        "model_snapshots",
        [sa.text("domain"), sa.text("benchmark_score DESC")],
    )
    op.create_index("idx_model_snapshot_data", "model_snapshots", ["data"], postgresql_using="gin")
    op.create_index("idx_model_snapshot_provider", "model_snapshots", ["provider", "domain"])

    op.create_table(
        "fetch_tasks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_type", sa.String(length=30), nullable=False),
        sa.Column("source_key", sa.String(length=80), nullable=False),
        sa.Column("domain", sa.String(length=50), nullable=True),
        sa.Column("triggered_by", sa.String(length=100), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="pending"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("hit_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("auto_start", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("fetch_strategy", sa.String(length=50), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint("attempt_count >= 0", name="ck_fetch_attempt_count_non_negative"),
        sa.CheckConstraint("hit_count >= 0", name="ck_fetch_hit_count_non_negative"),
        sa.CheckConstraint(f"status IN ({_in(FETCH_STATUSES)})", name="ck_fetch_status"),
        sa.CheckConstraint(
            "status <> 'failed_exhausted' OR hit_count = 0",
            name="ck_fetch_terminal_hit_count",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_fetch_task_user",
        "fetch_tasks",
        [sa.text("triggered_by"), sa.text("created_at DESC")],
    )
    op.create_index("idx_fetch_task_data", "fetch_tasks", ["data"], postgresql_using="gin")
    op.create_index("idx_fetch_task_type", "fetch_tasks",
                    ["task_type", "source_key", "domain", "created_at"])
    op.create_index(
        "uq_fetch_in_progress",
        "fetch_tasks",
        [
            sa.text("task_type"),
            sa.text("source_key"),
            sa.text("COALESCE(domain, '')"),
        ],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('pending', 'running') AND triggered_by <> 'system'"
        ),
    )

    op.create_table(
        "user_evaluations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("org_id", sa.String(length=100), nullable=False),
        sa.Column("user_id", sa.String(length=100), nullable=False),
        sa.Column("domain", sa.String(length=50), nullable=False),
        sa.Column("status", sa.String(length=30), nullable=False, server_default="completed"),
        sa.Column("fetch_task_id", sa.Uuid(), nullable=True),
        sa.Column(
            "snapshot_used_ids",
            postgresql.ARRAY(sa.Uuid()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint(
            f"status IN ({_in(EVALUATION_STATUSES)})", name="ck_user_eval_status"
        ),
        sa.ForeignKeyConstraint(["fetch_task_id"], ["fetch_tasks.id"],
                                name="fk_eval_fetch_task"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "idx_user_eval_org",
        "user_evaluations",
        [sa.text("org_id"), sa.text("created_at DESC")],
    )
    op.create_index(
        "idx_user_eval_user",
        "user_evaluations",
        [sa.text("user_id"), sa.text("created_at DESC")],
    )
    op.create_index("idx_user_eval_fetch_task", "user_evaluations", ["fetch_task_id"])
    op.create_index("idx_user_eval_data", "user_evaluations", ["data"], postgresql_using="gin")

    op.create_table(
        "infrastructure_costs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("cost_type", sa.String(length=30), nullable=False),
        sa.Column("name", sa.String(length=150), nullable=False),
        sa.Column("region", sa.String(length=50), nullable=False, server_default="default"),
        sa.Column("unit", sa.String(length=30), nullable=False),
        sa.Column("unit_price", sa.Numeric(precision=12, scale=4), nullable=False),
        sa.Column("source", sa.String(length=50), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint("unit_price >= 0", name="ck_infra_cost_price_non_negative"),
        sa.CheckConstraint(f"cost_type IN ({_in(COST_TYPES)})", name="ck_infra_cost_type"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("cost_type", "name", "region", name="uq_infra_cost"),
    )
    op.create_index("idx_infra_cost_lookup", "infrastructure_costs",
                    ["cost_type", "region", "is_active"])
    op.create_index("idx_infra_cost_data", "infrastructure_costs", ["data"],
                    postgresql_using="gin")

    op.create_table(
        "subscription_plans",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("plan_key", sa.String(length=80), nullable=False),
        sa.Column("plan_name", sa.String(length=150), nullable=False),
        sa.Column("monthly_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="USD"),
        sa.Column("billing_cycle", sa.String(length=20), nullable=False,
                  server_default="monthly"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("source", sa.String(length=50), nullable=False, server_default="manual"),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint("monthly_price >= 0", name="ck_subscription_price_non_negative"),
        sa.CheckConstraint(
            f"billing_cycle IN ({_in(BILLING_CYCLES)})",
            name="ck_subscription_billing_cycle",
        ),
        sa.CheckConstraint(
            f"source IN ({_in(PLAN_SOURCES)})", name="ck_subscription_source"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("provider", "plan_key", "billing_cycle",
                            name="uq_subscription_plan"),
    )
    op.create_index("idx_subscription_active", "subscription_plans", ["is_active", "provider"])
    op.create_index("idx_subscription_data", "subscription_plans", ["data"],
                    postgresql_using="gin")

    op.execute(
        """
        CREATE OR REPLACE FUNCTION set_updated_at()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    for table_name in ("model_snapshots", "fetch_tasks", "infrastructure_costs",
                       "subscription_plans"):
        op.execute(
            f"""
            DROP TRIGGER IF EXISTS trg_{table_name}_updated_at ON {table_name};
            CREATE TRIGGER trg_{table_name}_updated_at
            BEFORE UPDATE ON {table_name}
            FOR EACH ROW EXECUTE FUNCTION set_updated_at()
            """
        )

    op.execute("ALTER TABLE user_evaluations ENABLE ROW LEVEL SECURITY")
    op.execute("ALTER TABLE user_evaluations FORCE ROW LEVEL SECURITY")
    op.execute("DROP POLICY IF EXISTS user_eval_org_isolation_policy ON user_evaluations")
    op.execute(
        """
        CREATE POLICY user_eval_org_isolation_policy ON user_evaluations
            FOR ALL
            TO authenticated_users
            USING (org_id = current_setting('app.current_org_id', true))
            WITH CHECK (org_id = current_setting('app.current_org_id', true))
        """
    )
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mera')
               AND NOT pg_has_role('mera', 'authenticated_users', 'MEMBER') THEN
                GRANT authenticated_users TO mera;
            END IF;
        END
        $$
        """
    )
    for table_name in (
        "model_snapshots",
        "fetch_tasks",
        "user_evaluations",
        "infrastructure_costs",
        "subscription_plans",
    ):
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table_name} TO authenticated_users")
    op.execute("GRANT USAGE ON SCHEMA public TO authenticated_users")


def downgrade() -> None:
    op.execute(
        """
        DO $$
        BEGIN
            IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'mera')
               AND pg_has_role('mera', 'authenticated_users', 'MEMBER') THEN
                REVOKE authenticated_users FROM mera;
            END IF;
        END
        $$
        """
    )
    op.execute("DROP POLICY IF EXISTS user_eval_org_isolation_policy ON user_evaluations")
    op.drop_table("subscription_plans")
    op.drop_table("infrastructure_costs")
    op.drop_table("user_evaluations")
    op.drop_table("fetch_tasks")
    op.drop_table("model_snapshots")
    op.execute("DROP FUNCTION IF EXISTS set_updated_at()")
