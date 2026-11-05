"""一个模型一行：合并榜单快照、移除冗余 domain 列

- model_snapshots：唯一键由 (model_id, domain) 改为 (model_id)；同一模型的多域/多来源
  行合并为一行（sources 合并、维度分取非空、主榜分取最高、provider 取保留行），
  域信息随来源落到 data.sources[key].domain，不再占用列。
- fetch_records：`source_key` 已能表达来源平台，域信息保留在 record JSON 内，删除
  domain 列（消除重复）。

Revision ID: 0004_single_row_per_model
Revises: 0003_fetch_records
Create Date: 2026-11-05
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0004_single_row_per_model"
down_revision: str | None = "0003_fetch_records"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 合并期临时表：保留行/来源合并/维度合并/最高分
_STAGE_TABLES = (
    "_keeper",
    "_merged_sources",
    "_sources_agg",
    "_merged_scores",
    "_scores_agg",
    "_best",
)


def upgrade() -> None:
    # 1) 域信息回填到来源条目，保证删除列后仍可溯源「这条数据来自哪个榜」
    op.execute(
        """
        UPDATE model_snapshots AS m
        SET data = jsonb_set(
            COALESCE(m.data, '{}'::jsonb),
            '{sources}',
            (
                SELECT COALESCE(
                    jsonb_object_agg(e.key, e.value || jsonb_build_object('domain', m.domain)),
                    '{}'::jsonb
                )
                FROM jsonb_each(COALESCE(m.data -> 'sources', '{}'::jsonb)) AS e(key, value)
            ),
            true
        )
        WHERE m.data -> 'sources' IS NOT NULL
        """
    )

    # 2) 每个模型保留一行：主榜分最高（同分取最近更新），其余行删除
    op.execute(
        """
        CREATE TEMP TABLE _keeper AS
        SELECT DISTINCT ON (model_id) id, model_id
        FROM model_snapshots
        ORDER BY model_id, benchmark_score DESC NULLS LAST, updated_at DESC
        """
    )
    op.execute(
        """
        CREATE TEMP TABLE _merged_sources AS
        SELECT DISTINCT ON (m.model_id, e.key) m.model_id, e.key, e.value
        FROM model_snapshots AS m
        CROSS JOIN LATERAL jsonb_each(COALESCE(m.data -> 'sources', '{}'::jsonb)) AS e(key, value)
        ORDER BY m.model_id, e.key, m.updated_at DESC
        """
    )
    op.execute(
        """
        CREATE TEMP TABLE _sources_agg AS
        SELECT model_id, jsonb_object_agg(key, value) AS sources
        FROM _merged_sources GROUP BY model_id
        """
    )
    op.execute(
        """
        CREATE TEMP TABLE _merged_scores AS
        SELECT DISTINCT ON (m.model_id, e.key) m.model_id, e.key, e.value
        FROM model_snapshots AS m
        CROSS JOIN LATERAL jsonb_each(COALESCE(m.scores, '{}'::jsonb)) AS e(key, value)
        WHERE e.value <> 'null'::jsonb
        ORDER BY m.model_id, e.key, m.updated_at DESC
        """
    )
    op.execute(
        """
        CREATE TEMP TABLE _scores_agg AS
        SELECT model_id, jsonb_object_agg(key, value) AS scores
        FROM _merged_scores GROUP BY model_id
        """
    )
    op.execute(
        """
        CREATE TEMP TABLE _best AS
        SELECT model_id, max(benchmark_score) AS benchmark_score
        FROM model_snapshots GROUP BY model_id
        """
    )
    op.execute(
        """
        UPDATE model_snapshots AS m
        SET benchmark_score = b.benchmark_score,
            scores = COALESCE(s.scores, m.scores),
            data = (COALESCE(m.data, '{}'::jsonb) - 'sources')
                   || jsonb_build_object('sources', COALESCE(g.sources, '{}'::jsonb)),
            updated_at = now()
        FROM _keeper AS k
        LEFT JOIN _best AS b ON b.model_id = k.model_id
        LEFT JOIN _scores_agg AS s ON s.model_id = k.model_id
        LEFT JOIN _sources_agg AS g ON g.model_id = k.model_id
        WHERE m.id = k.id
        """
    )
    op.execute(
        """
        DELETE FROM model_snapshots AS m
        USING _keeper AS k
        WHERE m.model_id = k.model_id AND m.id <> k.id
        """
    )
    for table in _STAGE_TABLES:
        op.execute(f"DROP TABLE IF EXISTS {table}")

    # 3) 唯一键改为 model_id，索引去掉 domain
    op.drop_constraint("uq_model_snapshot", "model_snapshots", type_="unique")
    op.drop_index("idx_model_snapshot_domain", table_name="model_snapshots")
    op.drop_index("idx_model_snapshot_provider", table_name="model_snapshots")
    op.drop_column("model_snapshots", "domain")
    op.create_unique_constraint("uq_model_snapshot", "model_snapshots", ["model_id"])
    op.create_index("idx_model_snapshot_score", "model_snapshots", ["benchmark_score"])
    op.create_index("idx_model_snapshot_provider", "model_snapshots", ["provider"])

    # 4) 采集留痕：来源平台由 source_key 表达，域保留在 record JSON 内
    op.drop_column("fetch_records", "domain")


def downgrade() -> None:
    op.add_column(
        "fetch_records",
        sa.Column("domain", sa.String(length=50), nullable=False, server_default="general"),
    )
    op.alter_column("fetch_records", "domain", server_default=None)

    op.drop_index("idx_model_snapshot_score", table_name="model_snapshots")
    op.drop_index("idx_model_snapshot_provider", table_name="model_snapshots")
    op.drop_constraint("uq_model_snapshot", "model_snapshots", type_="unique")
    op.add_column(
        "model_snapshots",
        sa.Column("domain", sa.String(length=50), nullable=False, server_default="general"),
    )
    op.alter_column("model_snapshots", "domain", server_default=None)
    op.create_unique_constraint(
        "uq_model_snapshot", "model_snapshots", ["model_id", "domain"]
    )
    op.create_index(
        "idx_model_snapshot_domain", "model_snapshots", ["domain", "benchmark_score"]
    )
    op.create_index(
        "idx_model_snapshot_provider", "model_snapshots", ["provider", "domain"]
    )
