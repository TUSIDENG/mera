"""数据域拆分：API 价格独立表 + 榜单多维评分 + token 包周期

- 新增 model_api_prices（按量 API 价格，业务键 model_id+provider，与榜单分表）
- model_snapshots 增加 scores JSONB / score_source，benchmark_score 改可空
  （区分「无分」与「真 0 分」；存量 0 分行来自旧的错误单字段映射，重置为 NULL
  由下次采集按新映射回填）
- subscription_plans.billing_cycle 放开 one_off（token 包等一次性买断）

Revision ID: 0002_data_domain_split
Revises: 0001_initial
Create Date: 2026-11-03
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_data_domain_split"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

BILLING_CYCLES = ("monthly", "yearly", "one_off")
BILLING_CYCLES_LEGACY = ("monthly", "yearly")


def _in(values: tuple[str, ...]) -> str:
    return ", ".join(f"'{value}'" for value in values)


def upgrade() -> None:
    op.create_table(
        "model_api_prices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("model_id", sa.String(length=100), nullable=False),
        sa.Column("provider", sa.String(length=50), nullable=False),
        sa.Column("input_price", sa.Numeric(precision=20, scale=10), nullable=True),
        sa.Column("output_price", sa.Numeric(precision=20, scale=10), nullable=True),
        sa.Column("currency", sa.String(length=8), nullable=False, server_default="USD"),
        sa.Column("unit", sa.String(length=30), nullable=False, server_default="token"),
        sa.Column("source", sa.String(length=50), nullable=False, server_default="fetch"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("data", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False,
                  server_default=sa.text("now()")),
        sa.CheckConstraint("input_price IS NULL OR input_price >= 0",
                           name="ck_model_api_price_input_non_negative"),
        sa.CheckConstraint("output_price IS NULL OR output_price >= 0",
                           name="ck_model_api_price_output_non_negative"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("model_id", "provider", name="uq_model_api_price"),
    )
    op.create_index("idx_model_api_price_provider", "model_api_prices", ["provider"])
    op.create_index("idx_model_api_price_data", "model_api_prices", ["data"],
                    postgresql_using="gin")
    op.execute(
        """
        DROP TRIGGER IF EXISTS trg_model_api_prices_updated_at ON model_api_prices;
        CREATE TRIGGER trg_model_api_prices_updated_at
        BEFORE UPDATE ON model_api_prices
        FOR EACH ROW EXECUTE FUNCTION set_updated_at()
        """
    )
    op.execute(
        "GRANT SELECT, INSERT, UPDATE, DELETE ON model_api_prices TO authenticated_users"
    )

    op.add_column(
        "model_snapshots",
        sa.Column("scores", postgresql.JSONB(astext_type=sa.Text()), nullable=False,
                  server_default=sa.text("'{}'::jsonb")),
    )
    op.add_column(
        "model_snapshots",
        sa.Column("score_source", sa.String(length=50), nullable=True),
    )
    op.alter_column(
        "model_snapshots",
        "benchmark_score",
        existing_type=sa.Numeric(precision=5, scale=2),
        nullable=True,
    )
    op.execute("UPDATE model_snapshots SET benchmark_score = NULL")

    op.drop_constraint(
        "ck_subscription_billing_cycle", "subscription_plans", type_="check"
    )
    op.create_check_constraint(
        "ck_subscription_billing_cycle",
        "subscription_plans",
        f"billing_cycle IN ({_in(BILLING_CYCLES)})",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_subscription_billing_cycle", "subscription_plans", type_="check"
    )
    op.create_check_constraint(
        "ck_subscription_billing_cycle",
        "subscription_plans",
        f"billing_cycle IN ({_in(BILLING_CYCLES_LEGACY)})",
    )

    op.execute("UPDATE model_snapshots SET benchmark_score = 0 WHERE benchmark_score IS NULL")
    op.alter_column(
        "model_snapshots",
        "benchmark_score",
        existing_type=sa.Numeric(precision=5, scale=2),
        nullable=False,
    )
    op.drop_column("model_snapshots", "score_source")
    op.drop_column("model_snapshots", "scores")

    op.execute(
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON model_api_prices FROM authenticated_users"
    )
    op.execute(
        "DROP TRIGGER IF EXISTS trg_model_api_prices_updated_at ON model_api_prices"
    )
    op.drop_table("model_api_prices")
