"""采集记录留痕表 + 清理 openrouter 厂商榜单错数据

- 新增 fetch_records（append-only 采集历史：哪次任务/哪个平台/采了什么，仅 model_metrics）
- 删除 model_snapshots 中 provider='openrouter' 的榜单行：openrouter 是聚合平台
  而非模型研发厂商，这些行全部来自站点 normalize 默认兜底，属错数据；清理后
  重新触发采集即按真实厂商（模型 id vendor 前缀）回填。价格表 model_api_prices
  不受影响（openrouter 作为厂商仅在价格/成本域保留）。

Revision ID: 0003_fetch_records
Revises: 0002_data_domain_split
Create Date: 2026-11-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0003_fetch_records"
down_revision: str | None = "0002_data_domain_split"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "fetch_records",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("task_id", sa.Uuid(), nullable=False),
        sa.Column("source_key", sa.String(length=50), nullable=False),
        sa.Column("model_id", sa.String(length=100), nullable=False),
        sa.Column("raw_model_id", sa.String(length=200), nullable=True),
        sa.Column("domain", sa.String(length=50), nullable=False),
        sa.Column(
            "record",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.text("now()"),
        ),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["fetch_tasks.id"],
            name="fk_fetch_record_task",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_fetch_record_task", "fetch_records", ["task_id"])
    op.create_index(
        "idx_fetch_record_model",
        "fetch_records",
        ["model_id", sa.text("created_at DESC")],
    )
    op.create_index("idx_fetch_record_source", "fetch_records", ["source_key"])
    op.execute("GRANT SELECT, INSERT, UPDATE, DELETE ON fetch_records TO authenticated_users")

    # 清理 openrouter 兜底产生的榜单错数据（价格表不动）
    op.execute("DELETE FROM model_snapshots WHERE provider = 'openrouter'")


def downgrade() -> None:
    op.execute(
        "REVOKE SELECT, INSERT, UPDATE, DELETE ON fetch_records FROM authenticated_users"
    )
    op.drop_table("fetch_records")
