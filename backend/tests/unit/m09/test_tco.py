"""M09 自部署 TCO 各成本项公式用例。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.scoring.engine import estimate_tco
from app.scoring.models import InfraCost


def test_rental_only() -> None:
    cost = InfraCost(rental_monthly=Decimal(100))
    assert estimate_tco(cost, 1_000_000) == pytest.approx(100.0)


def test_purchase_depreciation_only() -> None:
    cost = InfraCost(purchase_price=Decimal(3600), depreciation_months=36)
    assert estimate_tco(cost, 1_000_000) == pytest.approx(100.0)


def test_rental_plus_purchase_depreciation() -> None:
    cost = InfraCost(
        rental_monthly=Decimal(100),
        purchase_price=Decimal(3600),
        depreciation_months=36,
    )
    assert estimate_tco(cost, 1_000_000) == pytest.approx(200.0)


def test_electricity_and_bandwidth_scale_with_tokens() -> None:
    cost = InfraCost(
        electricity_per_million_tokens=Decimal(10),
        bandwidth_per_million_tokens=Decimal(5),
    )
    assert estimate_tco(cost, 1_000_000) == pytest.approx(15.0)
    assert estimate_tco(cost, 2_000_000) == pytest.approx(30.0)
    assert estimate_tco(cost, 3_000_000) == pytest.approx(45.0)


def test_zero_cost() -> None:
    assert estimate_tco(InfraCost(), 1_000_000) == 0.0


def test_zero_depreciation_months_skips_purchase_amortization() -> None:
    cost = InfraCost(purchase_price=Decimal(3600), depreciation_months=0)
    assert estimate_tco(cost, 1_000_000) == 0.0
