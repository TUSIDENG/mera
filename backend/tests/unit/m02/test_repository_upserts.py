"""M02 三类 UPSERT 仓储测试（SQLite 内存库）。"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.enums import CostType
from app.db.models import (
    InfrastructureCost,
    ModelSnapshot,
    SubscriptionPlan,
)
from app.repositories import (
    CostRecord,
    Repository,
    SnapshotRecord,
    SubscriptionPlanRecord,
)
from app.repositories.dto import ApiPriceRecord
from app.repositories.repository import _dedupe_for_upsert


def test_dedupe_for_upsert_last_wins() -> None:
    """同业务键去重，后写覆盖先写（PG 批量 ON CONFLICT 不允许同命令两次命中同行）。"""
    records = [
        SnapshotRecord(model_id="m", provider="p", domain="d",
                       benchmark_score=Decimal("1.0"), data={"v": 1}),
        SnapshotRecord(model_id="other", provider="p", domain="d",
                       benchmark_score=Decimal("2.0")),
        SnapshotRecord(model_id="m", provider="p", domain="d",
                       benchmark_score=Decimal("3.0"), data={"v": 3}),
    ]
    deduped = _dedupe_for_upsert(records)
    assert len(deduped) == 2
    by_id = {record.model_id: record for record in deduped}
    assert by_id["m"].benchmark_score == Decimal("3.0")
    assert by_id["m"].data == {"v": 3}
    assert by_id["other"].benchmark_score == Decimal("2.0")


def test_upsert_prices_roundtrip(db_session: Session) -> None:
    repo = Repository(db_session)
    repo.upsert_prices([
        ApiPriceRecord(
            model_id="openai/gpt-5",
            provider="openrouter",
            input_price=Decimal("0.00000075"),
            output_price=Decimal("0.0000045"),
            source="openrouter",
        )
    ])
    db_session.commit()
    repo.upsert_prices([
        ApiPriceRecord(
            model_id="openai/gpt-5",
            provider="openrouter",
            input_price=Decimal("0.000001"),
            source="openrouter",
        )
    ])
    db_session.commit()
    prices = repo.latest_prices()
    assert len(prices) == 1
    assert prices[0].input_price == Decimal("0.000001")
    assert prices[0].output_price is None
    assert prices[0].unit == "token"
    assert repo.get_price("openai/gpt-5", "openrouter") is not None
    assert repo.get_price("openai/gpt-5", "other") is None


def test_upsert_snapshots_is_idempotent_and_updates_values(db_session: Session) -> None:
    repo = Repository(db_session)
    records = [
        SnapshotRecord(
            model_id="openai/gpt",
            provider="openai",
            domain="coding",
            benchmark_score=Decimal("88.00"),
            source_key="demo",
            data={
                "sources": {
                    "demo": {"benchmark_score": 88.0, "scores": {}, "record": {}}
                }
            },
        )
    ]

    assert repo.upsert_snapshots(records) == 1
    db_session.commit()
    assert repo.upsert_snapshots([
        SnapshotRecord(
            model_id="openai/gpt",
            provider="openai",
            domain="coding",
            benchmark_score=Decimal("92.50"),
            source_key="demo",
            data={
                "sources": {
                    "demo": {"benchmark_score": 92.5, "scores": {}, "record": {}}
                }
            },
        )
    ]) == 1
    db_session.commit()

    count = db_session.scalar(select(func.count()).select_from(ModelSnapshot))
    snapshot = db_session.scalar(select(ModelSnapshot))
    assert count == 1
    assert snapshot is not None
    assert snapshot.benchmark_score == Decimal("92.50")
    assert snapshot.data["sources"]["demo"]["benchmark_score"] == 92.5


def test_upsert_snapshots_supports_partial_conflict_batch(db_session: Session) -> None:
    repo = Repository(db_session)
    repo.upsert_snapshots([
        SnapshotRecord(
            model_id="a/model",
            provider="a",
            domain="general_office",
            benchmark_score=Decimal("70.00"),
            source_key="demo",
            data={"sources": {"demo": {"benchmark_score": 70.0, "record": {}}}},
        )
    ])
    db_session.commit()

    repo.upsert_snapshots([
        SnapshotRecord(
            model_id="a/model",
            provider="a",
            domain="general_office",
            benchmark_score=Decimal("75.00"),
            source_key="demo",
            data={"sources": {"demo": {"benchmark_score": 75.0, "record": {}}}},
        ),
        SnapshotRecord(
            model_id="b/model",
            provider="b",
            domain="general_office",
            benchmark_score=Decimal("80.00"),
            source_key="demo",
            data={"sources": {"demo": {"benchmark_score": 80.0, "record": {}}}},
        ),
    ])
    db_session.commit()

    assert db_session.scalar(select(func.count()).select_from(ModelSnapshot)) == 2


def test_upsert_snapshots_replaces_site_provider(db_session: Session) -> None:
    """站点兜底厂商（旧数据的 aider）在能推断出真实厂商后被覆盖，真实厂商之间不互相覆盖。"""
    repo = Repository(db_session)
    repo.upsert_snapshots([
        SnapshotRecord(
            model_id="gpt-5",
            provider="aider",
            domain="coding",
            benchmark_score=Decimal("88.00"),
            source_key="aider_leaderboard",
            data={"sources": {"aider_leaderboard": {"benchmark_score": 88.0, "record": {}}}},
        )
    ])
    db_session.commit()

    repo.upsert_snapshots([
        SnapshotRecord(
            model_id="gpt-5",
            provider="openai",
            domain="coding",
            benchmark_score=Decimal("88.00"),
            source_key="aider_leaderboard",
            data={"sources": {"aider_leaderboard": {"benchmark_score": 88.0, "record": {}}}},
        )
    ])
    db_session.commit()
    assert db_session.scalar(select(ModelSnapshot)).provider == "openai"

    # 已有真实厂商时，后续来源的站点兜底值不覆盖
    repo.upsert_snapshots([
        SnapshotRecord(
            model_id="gpt-5",
            provider="lmarena",
            domain="chat",
            benchmark_score=Decimal("90.00"),
            source_key="lmarena",
            data={"sources": {"lmarena": {"benchmark_score": 90.0, "record": {}}}},
        )
    ])
    db_session.commit()
    assert db_session.scalar(select(ModelSnapshot)).provider == "openai"


def test_upsert_costs_uses_type_name_region_key(db_session: Session) -> None:
    repo = Repository(db_session)
    record = CostRecord(
        cost_type=CostType.GPU_RENTAL.value,
        name="H100",
        region="us-east",
        unit="hour",
        unit_price=Decimal("3.0000"),
        source="manual",
    )

    assert repo.upsert_costs([record]) == 1
    db_session.commit()
    assert repo.upsert_costs([
        CostRecord(
            cost_type=CostType.GPU_RENTAL.value,
            name="H100",
            region="us-east",
            unit="hour",
            unit_price=Decimal("2.5000"),
        )
    ]) == 1
    db_session.commit()

    assert db_session.scalar(select(func.count()).select_from(InfrastructureCost)) == 1
    cost = db_session.scalar(select(InfrastructureCost))
    assert cost is not None
    assert cost.unit_price == Decimal("2.5000")


def test_upsert_plans_uses_provider_key_cycle_key(db_session: Session) -> None:
    repo = Repository(db_session)
    plan = SubscriptionPlanRecord(
        provider="anthropic",
        plan_key="pro",
        plan_name="Claude Pro",
        monthly_price=Decimal("20.00"),
        data={"messages": 45},
    )

    assert repo.upsert_subscription_plans([plan]) == 1
    db_session.commit()
    assert repo.upsert_subscription_plans([
        SubscriptionPlanRecord(
            provider="anthropic",
            plan_key="pro",
            plan_name="Claude Pro",
            monthly_price=Decimal("18.00"),
            data={"messages": 60},
        )
    ]) == 1
    db_session.commit()

    assert db_session.scalar(select(func.count()).select_from(SubscriptionPlan)) == 1
    stored = repo.cheapest_active_plan("anthropic")
    assert stored is not None
    assert stored.monthly_price == Decimal("18.00")


def test_cheapest_active_plan_ignores_inactive_and_orders_by_price(
    db_session: Session,
) -> None:
    repo = Repository(db_session)
    repo.upsert_subscription_plans([
        SubscriptionPlanRecord(
            provider="openai",
            plan_key="plus",
            plan_name="Plus",
            monthly_price=Decimal("20.00"),
        ),
        SubscriptionPlanRecord(
            provider="openai",
            plan_key="pro",
            plan_name="Pro",
            monthly_price=Decimal("200.00"),
        ),
        SubscriptionPlanRecord(
            provider="openai",
            plan_key="legacy",
            plan_name="Legacy",
            monthly_price=Decimal("1.00"),
            is_active=False,
        ),
    ])
    db_session.commit()

    plan = repo.cheapest_active_plan("openai")
    assert plan is not None
    assert plan.plan_key == "plus"
    assert repo.cheapest_active_plan("unknown") is None


def test_latest_snapshots_orders_by_score_then_model_id(db_session: Session) -> None:
    repo = Repository(db_session)
    repo.upsert_snapshots([
        SnapshotRecord(
            model_id="b/model",
            provider="b",
            domain="coding",
            benchmark_score=Decimal("90.00"),
            source_key="demo",
            data={"sources": {"demo": {"benchmark_score": 90.0, "record": {}}}},
        ),
        SnapshotRecord(
            model_id="a/model",
            provider="a",
            domain="coding",
            benchmark_score=Decimal("95.00"),
            source_key="demo",
            data={"sources": {"demo": {"benchmark_score": 95.0, "record": {}}}},
        ),
        SnapshotRecord(
            model_id="c/model",
            provider="c",
            domain="other",
            benchmark_score=Decimal("99.00"),
            source_key="other_source",
            data={"sources": {"other_source": {"benchmark_score": 99.0, "record": {}}}},
        ),
    ])
    db_session.commit()

    # 一个模型一行，不再按域过滤：按主榜分降序、同分按 model_id
    snapshots = repo.latest_snapshots()
    assert [snapshot.model_id for snapshot in snapshots] == ["c/model", "a/model", "b/model"]


def test_empty_upsert_returns_zero(db_session: Session) -> None:
    repo = Repository(db_session)
    assert repo.upsert_snapshots([]) == 0
    assert repo.upsert_costs([]) == 0
    assert repo.upsert_subscription_plans([]) == 0


@pytest.mark.parametrize(
    "method",
    ["upsert_snapshots", "upsert_costs", "upsert_subscription_plans"],
)
def test_invalid_record_rolls_back(db_session: Session, method: str) -> None:
    repo = Repository(db_session)
    valid_records = {
        "upsert_snapshots": [
            SnapshotRecord(
                model_id="ok/model",
                provider="ok",
                domain="coding",
                benchmark_score=Decimal("80.00"),
            )
        ],
        "upsert_costs": [
            CostRecord(
                cost_type=CostType.CPU.value,
                name="cpu",
                unit="hour",
                unit_price=Decimal("1.00"),
            )
        ],
        "upsert_subscription_plans": [
            SubscriptionPlanRecord(
                provider="ok",
                plan_key="plus",
                plan_name="Plus",
                monthly_price=Decimal("20.00"),
            )
        ],
    }
    getattr(repo, method)(valid_records[method])
    db_session.commit()

    with pytest.raises(IntegrityError), db_session.begin():
        if method == "upsert_snapshots":
            db_session.add(
                ModelSnapshot(
                    model_id="bad",
                    provider="bad",
                    benchmark_score=Decimal("-1.00"),
                )
            )
        elif method == "upsert_costs":
            db_session.add(
                InfrastructureCost(
                    cost_type="bad",
                    name="bad",
                    unit="hour",
                    unit_price=Decimal("1.00"),
                )
            )
        else:
            db_session.add(
                SubscriptionPlan(
                    provider="bad",
                    plan_key="bad",
                    plan_name="bad",
                    monthly_price=Decimal("-1.00"),
                )
            )

    assert db_session.scalar(
        select(func.count()).select_from(
            {
                "upsert_snapshots": ModelSnapshot,
                "upsert_costs": InfrastructureCost,
                "upsert_subscription_plans": SubscriptionPlan,
            }[method]
        )
    ) == 1


class TestSnapshotMergeUpsert:
    """合并式 upsert（通用路径）：null 维度不覆盖、多来源共存、LLM 分受保护。"""

    def _snapshot(self, db_session: Session, model_id: str = "m") -> ModelSnapshot:
        return db_session.scalar(
            select(ModelSnapshot).where(ModelSnapshot.model_id == model_id)
        )

    def test_null_dims_do_not_overwrite(self, db_session: Session) -> None:
        repo = Repository(db_session)
        repo.upsert_snapshots([
            SnapshotRecord(
                model_id="m", provider="p", domain="general",
                benchmark_score=Decimal("80.0"), score_source="intelligence",
                source_key="aa",
                scores={"intelligence": 80.0, "coding": 70.0},
                data={"sources": {"aa": {
                    "raw_model_id": "m",
                    "benchmark_score": 80.0,
                    "scores": {"intelligence": 80.0, "coding": 70.0},
                    "record": {},
                }}},
            )
        ])
        db_session.commit()
        # 第二次采集 coding 维度缺失（null），不得覆盖已有 70.0
        repo.upsert_snapshots([
            SnapshotRecord(
                model_id="m", provider="p", domain="general",
                benchmark_score=Decimal("81.5"), score_source="intelligence",
                source_key="aa",
                scores={"intelligence": 81.5, "coding": None},
                data={"sources": {"aa": {
                    "raw_model_id": "m:v2",
                    "benchmark_score": 81.5,
                    "scores": {"intelligence": 81.5, "coding": None},
                    "record": {},
                }}},
            )
        ])
        db_session.commit()
        snap = self._snapshot(db_session)
        assert snap.scores == {"intelligence": 81.5, "coding": 70.0}
        assert snap.benchmark_score == Decimal("81.5")
        # 同源重采覆盖该 source key
        assert snap.data["sources"]["aa"]["raw_model_id"] == "m:v2"

    def test_multi_source_coexist(self, db_session: Session) -> None:
        repo = Repository(db_session)
        repo.upsert_snapshots([
            SnapshotRecord(
                model_id="m", provider="anthropic", domain="general",
                benchmark_score=Decimal("80.0"), score_source="intelligence",
                source_key="artificial_analysis",
                scores={"intelligence": 80.0},
                data={"sources": {"artificial_analysis": {
                    "raw_model_id": "m",
                    "benchmark_score": 80.0,
                    "scores": {"intelligence": 80.0},
                    "record": {},
                }}},
            )
        ])
        db_session.commit()
        repo.upsert_snapshots([
            SnapshotRecord(
                model_id="m", provider="openai", domain="general",
                benchmark_score=None, score_source=None,
                source_key="openrouter",
                scores={"coding": 66.0},
                data={"sources": {"openrouter": {
                    "raw_model_id": "anthropic/m",
                    "benchmark_score": None,
                    "scores": {"coding": 66.0},
                    "record": {},
                }}},
            )
        ])
        db_session.commit()
        snap = self._snapshot(db_session)
        # 不同 source_key 共存
        assert set(snap.data["sources"]) == {"artificial_analysis", "openrouter"}
        # 新维度分并入；主榜分新值为空保留旧值；provider 首采为准
        assert snap.scores == {"intelligence": 80.0, "coding": 66.0}
        assert snap.benchmark_score == Decimal("80.0")
        assert snap.provider == "anthropic"

    def test_same_batch_multi_source_merge(self, db_session: Session) -> None:
        """同一批次内同模型的多来源记录逐条合并，不能去重丢掉较早来源。"""
        repo = Repository(db_session)
        repo.upsert_snapshots([
            SnapshotRecord(
                model_id="m", provider="p", domain="chat",
                benchmark_score=Decimal("70.0"), score_source="intelligence",
                source_key="lmarena",
                scores={"intelligence": 70.0},
                data={"sources": {"lmarena": {
                    "domain": "chat", "benchmark_score": 70.0,
                    "scores": {"intelligence": 70.0}, "record": {},
                }}},
            ),
            SnapshotRecord(
                model_id="m", provider="p", domain="general",
                benchmark_score=Decimal("65.0"), score_source="intelligence",
                source_key="artificial_analysis",
                scores={"intelligence": 80.0, "coding": 75.0},
                data={"sources": {"artificial_analysis": {
                    "domain": "general", "benchmark_score": 65.0,
                    "scores": {"intelligence": 80.0, "coding": 75.0}, "record": {},
                }}},
            ),
        ])
        db_session.commit()
        snap = self._snapshot(db_session)
        assert set(snap.data["sources"]) == {"lmarena", "artificial_analysis"}
        # 主榜分与维度分按源优先级取 AA
        assert snap.benchmark_score == Decimal("65.0")
        assert snap.score_source == "artificial_analysis"
        assert snap.scores == {"intelligence": 80.0, "coding": 75.0}

    def test_llm_scored_row_protected_from_overwrite(self, db_session: Session) -> None:
        repo = Repository(db_session)
        repo.upsert_snapshots([
            SnapshotRecord(
                model_id="m", provider="p", domain="general",
                benchmark_score=Decimal("80.0"), score_source="intelligence",
                source_key="artificial_analysis",
                scores={"intelligence": 80.0},
                data={"sources": {"artificial_analysis": {
                    "raw_model_id": "m",
                    "benchmark_score": 80.0,
                    "scores": {"intelligence": 80.0},
                    "record": {},
                }}},
            )
        ])
        db_session.commit()
        repo.apply_llm_score(
            "m", overall=88.5,
            dims={"intelligence": 88.5, "coding": 90.0, "agentic": None,
                  "long_context": None, "image": None, "video": None},
            rationale="基于 AA 采集数据", scorer="deepseek/deepseek-chat",
        )
        db_session.commit()
        snap = self._snapshot(db_session)
        assert snap.score_source == "llm:deepseek/deepseek-chat"
        assert snap.data["llm_score"]["rationale"] == "基于 AA 采集数据"
        # 重采：展示分与 score_source 保留 LLM 结果，仅 data.sources 合并
        repo.upsert_snapshots([
            SnapshotRecord(
                model_id="m", provider="p", domain="general",
                benchmark_score=Decimal("10.0"), score_source="coding",
                scores={"intelligence": 10.0, "coding": 10.0},
                data={"sources": {"openrouter": {"raw_model_id": "m", "record": {}}}},
            )
        ])
        db_session.commit()
        snap = self._snapshot(db_session)
        assert snap.score_source == "llm:deepseek/deepseek-chat"
        assert snap.benchmark_score == Decimal("88.5")
        assert snap.scores["coding"] == 90.0
        assert set(snap.data["sources"]) == {"artificial_analysis", "openrouter"}
        assert snap.data["llm_score"]["overall"] == 88.5


class TestFetchRecords:
    def test_insert_and_query_by_model_and_task(self, db_session: Session) -> None:
        import uuid

        from app.db.enums import FetchTaskStatus
        from app.db.models import FetchTask

        repo = Repository(db_session)
        task = FetchTask(
            task_type="model_metrics", source_key="demo", triggered_by="test",
            status=FetchTaskStatus.RUNNING.value,
        )
        db_session.add(task)
        db_session.commit()
        count = repo.insert_fetch_records(
            task.id,
            [
                SnapshotRecord(
                    model_id="gpt-4o", provider="openai", domain="general",
                    benchmark_score=Decimal("89.5"), score_source="score",
                    scores={}, data={"sources": {"demo": {}}},
                    raw_model_id="openai/gpt-4o", source_key="demo",
                ),
                SnapshotRecord(
                    model_id="claude-opus-5", provider="anthropic", domain="general",
                    benchmark_score=None, score_source=None,
                    scores={}, data={"sources": {"demo": {}}},
                    raw_model_id="anthropic/claude-opus-5:batch", source_key="demo",
                ),
            ],
        )
        db_session.commit()
        assert count == 2
        items, total = repo.list_fetch_records_by_model("gpt-4o", limit=10, offset=0)
        assert total == 1
        assert items[0].raw_model_id == "openai/gpt-4o"
        # Decimal 已转 float 以适配 JSONB
        assert items[0].record["benchmark_score"] == 89.5
        items, total = repo.list_fetch_records_by_task(task.id, limit=10, offset=0)
        assert total == 2
        assert set(repo.fetch_record_model_ids_by_task(task.id)) == {
            "gpt-4o",
            "claude-opus-5",
        }
        assert isinstance(task.id, uuid.UUID)
