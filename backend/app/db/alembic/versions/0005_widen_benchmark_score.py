"""放宽主榜分精度：Numeric(5,2) 上限 999.99 无法容纳 Elo 量纲分数

LMArena 等榜单的原始分为 Elo 量纲（约 800–2000），旧列定义会触发
psycopg NumericValueOutOfRange。主榜分虽只取 0–100 量纲来源，但维度分/
历史来源仍需容纳更大数值，故统一放宽到 Numeric(12,2)。

Revision ID: 0005_widen_benchmark_score
Revises: 0004_single_row_per_model
Create Date: 2026-11-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_widen_benchmark_score"
down_revision: str | None = "0004_single_row_per_model"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.alter_column(
        "model_snapshots",
        "benchmark_score",
        existing_type=sa.Numeric(precision=5, scale=2),
        type_=sa.Numeric(precision=12, scale=2),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        "model_snapshots",
        "benchmark_score",
        existing_type=sa.Numeric(precision=12, scale=2),
        type_=sa.Numeric(precision=5, scale=2),
        existing_nullable=True,
    )
