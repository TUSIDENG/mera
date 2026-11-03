"""仓储层输入 DTO（不依赖 ORM 会话）。"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class SnapshotRecord:
    model_id: str
    provider: str
    domain: str
    # 主榜分可空：None 表示该来源没有任何可用维度分（区别于真 0 分）
    benchmark_score: Decimal | None
    # 各维度原始分（JSONB 存储，值为 float/None）与主榜分来源维度
    scores: dict[str, float | None] = field(default_factory=dict)
    score_source: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ApiPriceRecord:
    """模型 API 按量价格（每 unit 单价，默认每 token）；与榜单快照分表。"""

    model_id: str
    provider: str
    input_price: Decimal | None = None
    output_price: Decimal | None = None
    currency: str = "USD"
    unit: str = "token"
    is_active: bool = True
    source: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CostRecord:
    cost_type: str
    name: str
    unit: str
    unit_price: Decimal
    region: str = "default"
    source: str | None = None
    is_active: bool = True
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SubscriptionPlanRecord:
    provider: str
    plan_key: str
    plan_name: str
    monthly_price: Decimal
    currency: str = "USD"
    billing_cycle: str = "monthly"
    is_active: bool = True
    source: str = "manual"
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class CreateTaskParams:
    task_type: str
    source_key: str
    triggered_by: str
    domain: str | None = None
    auto_start: bool = False
    data: dict[str, Any] = field(default_factory=dict)
