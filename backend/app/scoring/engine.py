"""M09 选型分析引擎：榜单归一化、TCO 估算、订阅盈亏、加权排名。

纯函数模块：零 I/O，不依赖数据库/网络，所有输入输出均为 dataclass 或基础类型。
"""

from __future__ import annotations

from dataclasses import replace
from decimal import Decimal

from app.core.exceptions import AppError, InvalidWeights
from app.scoring.models import (
    BreakEvenResult,
    InfraCost,
    PlanInput,
    RankedModel,
    RankInputs,
    Weights,
)

_MILLION = Decimal(1_000_000)
_WEIGHT_TOLERANCE = 1e-6


def normalize_benchmark(
    scores: dict[str, float], method: str = "minmax"
) -> dict[str, float]:
    """把榜单分 minmax 归一化到 [0, 1]；空/单值/全相同值均返回中性分 0.5。"""
    if method != "minmax":
        raise AppError(
            f"不支持的归一化方法: {method}", code="config_error", status_code=400
        )
    if not scores:
        return {}
    values = list(scores.values())
    if len(values) == 1:
        return {key: 0.5 for key in scores}
    low, high = min(values), max(values)
    if high == low:
        return {key: 0.5 for key in scores}
    span = high - low
    return {key: (value - low) / span for key, value in scores.items()}


def estimate_tco(cost: InfraCost, tokens_per_month: int) -> float:
    """估算自部署月度 TCO：租赁月费 + 采购价/折旧月数 +（电费+带宽）× 百万 token 数。"""
    fixed = Decimal(cost.rental_monthly)
    if cost.depreciation_months > 0:
        fixed += Decimal(cost.purchase_price) / Decimal(cost.depreciation_months)
    per_million = Decimal(cost.electricity_per_million_tokens) + Decimal(
        cost.bandwidth_per_million_tokens
    )
    variable = per_million * (Decimal(tokens_per_month) / _MILLION)
    return float(fixed + variable)


def break_even_subscription(
    api_cost: float | Decimal,
    plans: list[PlanInput],
    tokens_per_month: int = 1_000_000,
) -> BreakEvenResult | None:
    """比较月度 API 成本与订阅月费：只在「订阅更便宜」的套餐中取最低月费者。

    无套餐或全部套餐月费 >= api_cost 时返回 None（订阅不划算）。
    sufficient=False 表示该套餐的用量上限低于 tokens_per_month，即「不够用」。
    """
    api = api_cost if isinstance(api_cost, Decimal) else Decimal(str(api_cost))
    candidates = [plan for plan in plans if plan.monthly_price < api]
    if not candidates:
        return None
    cheapest = min(
        candidates, key=lambda plan: (plan.monthly_price, plan.provider, plan.plan_key)
    )
    sufficient = (
        cheapest.tokens_limit is None or cheapest.tokens_limit >= tokens_per_month
    )
    return BreakEvenResult(
        plan=cheapest,
        monthly_savings=float(api - cheapest.monthly_price),
        sufficient=sufficient,
    )


def rank_models(inputs: RankInputs, weights: Weights) -> list[RankedModel]:
    """加权排名：榜单分 minmax 归一，价格 minmax 后取反，缺价格项记 0.5 中性分。"""
    total = weights.benchmark + weights.price
    if abs(total - 1.0) > _WEIGHT_TOLERANCE:
        raise InvalidWeights(f"权重之和必须为 1，当前为 {total}")
    if not 0.0 <= weights.benchmark <= 1.0 or not 0.0 <= weights.price <= 1.0:
        raise InvalidWeights(
            f"权重必须位于 [0, 1]，当前 benchmark={weights.benchmark}, price={weights.price}"
        )

    models = inputs.models
    if not models:
        return []

    benchmark_norm = normalize_benchmark(
        {model.model_id: float(model.benchmark_score) for model in models}
    )
    ratio = Decimal(str(inputs.input_ratio))
    blended: dict[str, float] = {}
    monthly_cost: dict[str, float | None] = {}
    for model in models:
        if model.input_price is None or model.output_price is None:
            monthly_cost[model.model_id] = None
            continue
        blended_price = (
            ratio * _as_decimal(model.input_price)
            + (Decimal(1) - ratio) * _as_decimal(model.output_price)
        )
        blended[model.model_id] = float(blended_price)
        monthly_cost[model.model_id] = float(
            blended_price * Decimal(inputs.tokens_per_month)
        )

    price_norm: dict[str, float] = {}
    if blended:
        for model_id, value in normalize_benchmark(blended).items():
            price_norm[model_id] = 1.0 - value

    ranked: list[RankedModel] = []
    for model in models:
        benchmark_score_norm = benchmark_norm[model.model_id]
        price_score_norm = price_norm.get(model.model_id, 0.5)
        composite = (
            weights.benchmark * benchmark_score_norm
            + weights.price * price_score_norm
        )
        ranked.append(
            RankedModel(
                model_id=model.model_id,
                provider=model.provider,
                display_name=model.display_name,
                benchmark_score=float(model.benchmark_score),
                benchmark_norm=benchmark_score_norm,
                price_norm=price_score_norm,
                monthly_cost=monthly_cost[model.model_id],
                composite_score=composite,
                rank=0,
            )
        )

    ranked.sort(key=lambda item: (-item.composite_score, item.model_id))
    return [replace(item, rank=index) for index, item in enumerate(ranked, start=1)]


def _as_decimal(value: Decimal | float) -> Decimal:
    """把价格统一成 Decimal；float 经 str 转换避免二进制尾差进入成本计算。"""
    return value if isinstance(value, Decimal) else Decimal(str(value))
