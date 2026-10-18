"""M04 订阅套餐与基础设施成本请求/响应模型。"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

BillingCycleStr = Literal["monthly", "yearly"]
CostTypeStr = Literal[
    "gpu_rental", "gpu_purchase", "cpu", "electricity", "colocation", "bandwidth"
]


class PlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    provider: str
    plan_key: str
    plan_name: str
    monthly_price: Decimal
    currency: str
    billing_cycle: str
    is_active: bool
    source: str
    data: dict[str, Any]
    updated_at: datetime


class PlanPut(BaseModel):
    """管理端套餐 upsert（业务键 provider+plan_key+billing_cycle 由路径携带）。"""

    plan_name: str = Field(min_length=1, max_length=150)
    monthly_price: Decimal = Field(ge=0)
    currency: str = Field(default="USD", max_length=8)
    is_active: bool = True
    data: dict[str, Any] = Field(default_factory=dict)


class CostOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    cost_type: str
    name: str
    region: str
    unit: str
    unit_price: Decimal
    source: str | None
    is_active: bool
    data: dict[str, Any]
    updated_at: datetime


class CostPut(BaseModel):
    """管理端成本 upsert（业务键 cost_type+name+region 由路径携带）。"""

    unit: str = Field(min_length=1, max_length=30)
    unit_price: Decimal = Field(ge=0)
    is_active: bool = True
    data: dict[str, Any] = Field(default_factory=dict)
