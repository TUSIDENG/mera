"""M02 三类 UPSERT 仓储测试（SQLite 内存库）。"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.enums import CostType
from app.db.models import InfrastructureCost, ModelSnapshot, SubscriptionPlan
from app.repositories import (
    CostRecord,
    Repository,
    SnapshotRecord,
    SubscriptionPlanRecord,
)


def test_upsert_snapshots_is_idempotent_and_updates_values(db_session: Session) -> None:
    repo = Repository(db_session)
    records = [
        SnapshotRecord(
            model_id="openai/gpt",
            provider="openai",
            domain="coding",
            benchmark_score=Decimal("88.00"),
            data={"version": "a"},
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
            data={"version": "b"},
        )
    ]) == 1
    db_session.commit()

    count = db_session.scalar(select(func.count()).select_from(ModelSnapshot))
    snapshot = db_session.scalar(select(ModelSnapshot))
    assert count == 1
    assert snapshot is not None
    assert snapshot.benchmark_score == Decimal("92.50")
    assert snapshot.data == {"version": "b"}


def test_upsert_snapshots_supports_partial_conflict_batch(db_session: Session) -> None:
    repo = Repository(db_session)
    repo.upsert_snapshots([
        SnapshotRecord(
            model_id="a/model",
            provider="a",
            domain="general_office",
            benchmark_score=Decimal("70.00"),
        )
    ])
    db_session.commit()

    repo.upsert_snapshots([
        SnapshotRecord(
            model_id="a/model",
            provider="a",
            domain="general_office",
            benchmark_score=Decimal("75.00"),
        ),
        SnapshotRecord(
            model_id="b/model",
            provider="b",
            domain="general_office",
            benchmark_score=Decimal("80.00"),
        ),
    ])
    db_session.commit()

    assert db_session.scalar(select(func.count()).select_from(ModelSnapshot)) == 2


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
        ),
        SnapshotRecord(
            model_id="a/model",
            provider="a",
            domain="coding",
            benchmark_score=Decimal("95.00"),
        ),
        SnapshotRecord(
            model_id="c/model",
            provider="c",
            domain="other",
            benchmark_score=Decimal("99.00"),
        ),
    ])
    db_session.commit()

    snapshots = repo.latest_snapshots("coding")
    assert [snapshot.model_id for snapshot in snapshots] == ["a/model", "b/model"]


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
                    domain="coding",
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
