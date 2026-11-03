"""M09 选型分析引擎的数据结构：全部为 frozen dataclass，零 I/O。

引擎的所有输入输出均通过这些 dataclass 传递，仓储/网络等副作用只允许出现在调用方。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class Weights:
    """benchmark 与 price 的权重；权重和的合法性校验统一在 engine.rank_models。"""

    benchmark: float = 0.6
    price: float = 0.4


@dataclass(frozen=True)
class ModelInput:
    """单个候选模型的输入：榜单分 + 每 token 单价（价格可缺项）。"""

    model_id: str
    provider: str
    benchmark_score: Decimal | float
    input_price: Decimal | None = None
    output_price: Decimal | None = None
    display_name: str | None = None


@dataclass(frozen=True)
class RankInputs:
    """排名输入：候选模型集合与用量假设（input_ratio 为输入 token 占比）。"""

    models: list[ModelInput]
    tokens_per_month: int = 1_000_000
    input_ratio: float = 0.7


@dataclass(frozen=True)
class RankedModel:
    """排名结果：归一化分值、月成本与综合得分。"""

    model_id: str
    provider: str
    display_name: str | None
    benchmark_score: float
    benchmark_norm: float
    price_norm: float
    monthly_cost: float | None
    composite_score: float
    rank: int


@dataclass(frozen=True)
class InfraCost:
    """自部署月度 TCO 输入：固定项（租赁 / 采购折旧）+ 变动项（电费 / 带宽，按每百万 token）。"""

    rental_monthly: Decimal = Decimal(0)
    purchase_price: Decimal = Decimal(0)
    depreciation_months: int = 36
    electricity_per_million_tokens: Decimal = Decimal(0)
    bandwidth_per_million_tokens: Decimal = Decimal(0)


@dataclass(frozen=True)
class PlanInput:
    """订阅套餐输入：月费与用量上限（tokens_limit=None 视为不限量）。"""

    provider: str
    plan_key: str
    plan_name: str
    monthly_price: Decimal
    tokens_limit: int | None = None
    billing_cycle: str = "monthly"
    currency: str = "USD"
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BreakEvenResult:
    """API vs 订阅的盈亏结果：sufficient=False 表示套餐用量上限低于输入量级。"""

    plan: PlanInput
    monthly_savings: float
    sufficient: bool
