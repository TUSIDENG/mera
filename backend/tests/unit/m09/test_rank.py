"""M09 加权排名、缺项处理、性质与 golden case 用例。"""

from __future__ import annotations

import json
import random
from decimal import Decimal
from pathlib import Path

import pytest

from app.core.exceptions import InvalidWeights
from app.scoring.engine import rank_models
from app.scoring.models import ModelInput, RankInputs, Weights

GOLDEN_PATH = Path(__file__).with_name("golden_rank.json")


def make_model(
    model_id: str,
    benchmark: float,
    input_price: str | None = None,
    output_price: str | None = None,
    provider: str = "p",
) -> ModelInput:
    """构造模型输入；价格为每 token 单价（字符串便于 Decimal 精确转换）。"""
    return ModelInput(
        model_id=model_id,
        provider=provider,
        benchmark_score=benchmark,
        input_price=None if input_price is None else Decimal(input_price),
        output_price=None if output_price is None else Decimal(output_price),
    )


def test_empty_input_returns_empty() -> None:
    assert rank_models(RankInputs(models=[]), Weights()) == []


def test_price_only_weight_ranks_cheapest_first() -> None:
    models = [
        make_model("expensive", 100.0, "0.00001", "0.00001"),
        make_model("cheap", 0.0, "0.000001", "0.000001"),
    ]
    ranked = rank_models(RankInputs(models=models), Weights(benchmark=0.0, price=1.0))
    assert [item.model_id for item in ranked] == ["cheap", "expensive"]
    assert ranked[0].price_norm == 1.0
    assert ranked[1].price_norm == 0.0
    assert ranked[0].composite_score == 1.0


def test_benchmark_only_weight_ranks_highest_score_first() -> None:
    models = [
        make_model("low", 10.0, "0.00001", "0.00001"),
        make_model("high", 90.0, "0.000001", "0.000001"),
    ]
    ranked = rank_models(RankInputs(models=models), Weights(benchmark=1.0, price=0.0))
    assert [item.model_id for item in ranked] == ["high", "low"]
    assert ranked[0].benchmark_norm == 1.0
    assert ranked[0].composite_score == 1.0


def test_invalid_weight_sum_raises() -> None:
    with pytest.raises(InvalidWeights) as exc_info:
        rank_models(
            RankInputs(models=[make_model("a", 50.0)]), Weights(benchmark=0.5, price=0.6)
        )
    assert exc_info.value.code == "invalid_weights"
    assert "权重之和必须为 1" in exc_info.value.message


def test_negative_weight_raises() -> None:
    with pytest.raises(InvalidWeights):
        rank_models(
            RankInputs(models=[make_model("a", 50.0)]),
            Weights(benchmark=-0.1, price=1.1),
        )


def test_missing_price_is_neutral_and_excluded_from_price_minmax() -> None:
    models = [
        make_model("cheap", 50.0, "0.000001", "0.000001"),
        make_model("expensive", 50.0, "0.00001", "0.00001"),
        make_model("unknown", 50.0),
    ]
    ranked = rank_models(RankInputs(models=models), Weights())

    by_id = {item.model_id: item for item in ranked}
    assert by_id["cheap"].price_norm == 1.0
    assert by_id["expensive"].price_norm == 0.0
    assert by_id["unknown"].price_norm == 0.5
    assert by_id["unknown"].monthly_cost is None
    assert by_id["cheap"].monthly_cost == pytest.approx(1.0)
    assert by_id["expensive"].monthly_cost == pytest.approx(10.0)


def test_monthly_cost_uses_input_ratio_and_tokens() -> None:
    model = make_model("m", 50.0, "0.000002", "0.00001")
    ranked = rank_models(
        RankInputs(models=[model], tokens_per_month=2_000_000, input_ratio=0.7),
        Weights(),
    )
    # 0.7*2e-6 + 0.3*1e-5 = 4.4e-6 / token × 2,000,000 = 8.8
    assert ranked[0].monthly_cost == pytest.approx(8.8)


def test_rank_numbers_and_order_are_consistent() -> None:
    models = [
        make_model("a", 60.0, "0.000005", "0.000005"),
        make_model("b", 90.0, "0.000002", "0.000002"),
        make_model("c", 75.0, "0.000003", "0.000003"),
    ]
    ranked = rank_models(RankInputs(models=models), Weights())
    assert [item.rank for item in ranked] == [1, 2, 3]
    composites = [item.composite_score for item in ranked]
    assert composites == sorted(composites, reverse=True)


def test_property_ranges_and_determinism() -> None:
    rng = random.Random(20260101)
    models: list[ModelInput] = []
    for index in range(12):
        benchmark = rng.uniform(0.0, 100.0)
        if index % 5 == 0:
            models.append(make_model(f"m{index}", benchmark))
            continue
        input_price = rng.uniform(1e-8, 1e-5)
        models.append(
            make_model(
                f"m{index}",
                benchmark,
                f"{input_price:.12f}",
                f"{input_price * 3:.12f}",
            )
        )

    inputs = RankInputs(models=models, tokens_per_month=1_000_000, input_ratio=0.7)
    weights = Weights(benchmark=0.5, price=0.5)

    first = rank_models(inputs, weights)
    second = rank_models(inputs, weights)

    assert first == second
    for item in first:
        assert 0.0 <= item.benchmark_norm <= 1.0
        assert 0.0 <= item.price_norm <= 1.0
        assert 0.0 <= item.composite_score <= 1.0
        if item.monthly_cost is not None:
            assert item.monthly_cost >= 0.0
    assert [item.rank for item in first] == list(range(1, len(models) + 1))


def test_golden_case_matches_archived_snapshot() -> None:
    golden = json.loads(GOLDEN_PATH.read_text(encoding="utf-8"))
    models = [
        ModelInput(
            model_id=entry["model_id"],
            provider=entry["provider"],
            benchmark_score=entry["benchmark_score"],
            input_price=Decimal(entry["input_price"]),
            output_price=Decimal(entry["output_price"]),
            display_name=entry["display_name"],
        )
        for entry in golden["models"]
    ]
    weights = Weights(
        benchmark=golden["weights"]["benchmark"], price=golden["weights"]["price"]
    )
    ranked = rank_models(
        RankInputs(
            models=models,
            tokens_per_month=golden["tokens_per_month"],
            input_ratio=golden["input_ratio"],
        ),
        weights,
    )

    assert [item.model_id for item in ranked] == golden["expected_order"]
    assert [item.rank for item in ranked] == [1, 2, 3, 4, 5]
    for item in ranked:
        assert item.composite_score == pytest.approx(
            golden["expected_composite"][item.model_id], abs=1e-6
        )
