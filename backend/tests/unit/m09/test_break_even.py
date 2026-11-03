"""M09 API vs 订阅盈亏（break_even）用例。"""

from __future__ import annotations

from decimal import Decimal

from app.scoring.engine import break_even_subscription
from app.scoring.models import PlanInput


def make_plan(
    monthly_price: str,
    tokens_limit: int | None = None,
    *,
    provider: str = "openai",
    plan_key: str = "pro",
) -> PlanInput:
    return PlanInput(
        provider=provider,
        plan_key=plan_key,
        plan_name=plan_key,
        monthly_price=Decimal(monthly_price),
        tokens_limit=tokens_limit,
    )


def test_empty_plans_returns_none() -> None:
    assert break_even_subscription(Decimal(50), []) is None


def test_no_cheaper_plan_returns_none() -> None:
    plans = [make_plan("50"), make_plan("80", plan_key="max")]
    assert break_even_subscription(Decimal(50), plans) is None


def test_picks_lowest_price_among_cheaper_plans() -> None:
    plans = [
        make_plan("40", 10_000_000, plan_key="medium"),
        make_plan("20", 1_000_000, plan_key="cheap", provider="other"),
        make_plan("30", 2_000_000, plan_key="plus"),
    ]
    result = break_even_subscription(Decimal(50), plans)
    assert result is not None
    assert result.plan.plan_key == "cheap"
    assert result.plan.provider == "other"
    assert result.monthly_savings == 30.0
    assert result.sufficient is True


def test_tokens_limit_below_usage_is_insufficient() -> None:
    result = break_even_subscription(
        Decimal(100), [make_plan("10", 500_000)], tokens_per_month=1_000_000
    )
    assert result is not None
    assert result.sufficient is False


def test_unlimited_plan_is_sufficient() -> None:
    result = break_even_subscription(
        Decimal(100), [make_plan("10", None)], tokens_per_month=10_000_000
    )
    assert result is not None
    assert result.sufficient is True


def test_limit_equal_to_usage_is_sufficient() -> None:
    result = break_even_subscription(
        Decimal(100), [make_plan("10", 1_000_000)], tokens_per_month=1_000_000
    )
    assert result is not None
    assert result.sufficient is True
