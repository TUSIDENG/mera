"""自部署基础设施成本。"""

from __future__ import annotations

import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Index,
    Numeric,
    String,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db.enums import CostType
from app.db.models.base import Base
from app.db.types import JSONBType
from app.db.uuid7 import uuid7


class InfrastructureCost(Base):
    __tablename__ = "infrastructure_costs"
    __table_args__ = (
        UniqueConstraint("cost_type", "name", "region", name="uq_infra_cost"),
        Index("idx_infra_cost_lookup", "cost_type", "region", "is_active"),
        Index("idx_infra_cost_data", "data", postgresql_using="gin"),
        CheckConstraint("unit_price >= 0", name="ck_infra_cost_price_non_negative"),
        CheckConstraint(
            f"cost_type IN ({', '.join(repr(v.value) for v in CostType)})",
            name="ck_infra_cost_type",
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid7)
    cost_type: Mapped[str] = mapped_column(String(30), nullable=False)
    name: Mapped[str] = mapped_column(String(150), nullable=False)
    region: Mapped[str] = mapped_column(String(50), nullable=False, default="default")
    unit: Mapped[str] = mapped_column(String(30), nullable=False)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(12, 4), nullable=False)
    source: Mapped[str | None] = mapped_column(String(50), nullable=True)
    is_active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    data: Mapped[dict[str, Any]] = mapped_column(JSONBType, nullable=False, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
        onupdate=func.now(),
    )
