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
    benchmark_score: Decimal
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
