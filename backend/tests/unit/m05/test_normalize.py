"""M05 用例②⑤：parse_score/parse_price 脏值矩阵、normalize 幂等。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from app.core.exceptions import ConfigError
from app.fetchers.normalize import (
    canonical_model_name,
    normalize_records,
    parse_price,
    parse_score,
)
from app.repositories.dto import CostRecord, SnapshotRecord, SubscriptionPlanRecord


class TestParseScore:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("89.5 分", Decimal("89.5")),
            ("89.5", Decimal("89.5")),
            (89.5, Decimal("89.5")),
            (90, Decimal(90)),
            ("得分：1,234.5", Decimal("1234.5")),
            ("0", Decimal(0)),
        ],
    )
    def test_valid(self, value, expected):
        assert parse_score(value) == expected

    @pytest.mark.parametrize("value", ["N/A", "", None, "abc", "-3", -1.5, True, []])
    def test_dirty_returns_none(self, value):
        assert parse_score(value) is None


class TestParsePrice:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            ("$3.00", Decimal("3.00")),
            ("¥1,234.5", Decimal("1234.5")),
            ("$0.25 / 1M tokens", Decimal("0.25")),
            ("0.00", Decimal("0.00")),
            (3, Decimal(3)),
        ],
    )
    def test_valid(self, value, expected):
        assert parse_price(value) == expected

    @pytest.mark.parametrize("value", ["N/A", "", None, "-$3.00", -0.5, "免费"])
    def test_dirty_returns_none(self, value):
        assert parse_price(value) is None


class TestCanonicalModelName:
    @pytest.mark.parametrize(
        ("value", "expected"),
        [
            (" GPT-4o ", "gpt-4o"),
            ("Claude   Sonnet  4", "claude sonnet 4"),
            ("glm-4.6", "glm-4.6"),
        ],
    )
    def test_normalize(self, value, expected):
        assert canonical_model_name(value) == expected

    @pytest.mark.parametrize("value", ["", "   ", None, 42])
    def test_dirty_returns_none(self, value):
        assert canonical_model_name(value) is None


def snapshot_cfg(**overrides) -> dict:
    cfg = {
        "key": "demo",
        "domain": "coding",
        "data_type": "model_metrics",
        "normalize": {"fields": {"model_id": "model", "score": "score"}},
    }
    cfg.update(overrides)
    return cfg


class TestNormalizeRecords:
    def test_model_metrics_mapping(self):
        raw = [{"model": " GPT-4o ", "score": "89.5 分", "extra": 1}]
        records, truncated = normalize_records(raw, snapshot_cfg())
        assert truncated is False
        assert records == [
            SnapshotRecord(
                model_id="gpt-4o",
                provider="demo",
                domain="coding",
                benchmark_score=Decimal("89.5"),
                data={"extra": 1},
            )
        ]

    def test_provider_from_defaults(self):
        cfg = snapshot_cfg()
        cfg["normalize"] = {
            "defaults": {"provider": "openrouter"},
            "fields": {"model_id": "id"},
        }
        records, _ = normalize_records([{"id": "a/b"}], cfg)
        assert records[0].provider == "openrouter"

    def test_nested_field_path(self):
        cfg = snapshot_cfg()
        cfg["normalize"]["fields"] = {"model_id": "id", "input_price": "pricing.prompt"}
        records, _ = normalize_records(
            [{"id": "m", "provider": "p", "pricing": {"prompt": "$3.00"}}], cfg
        )
        assert records[0].data["input_price"] == "$3.00"
        assert "pricing" not in records[0].data  # 已消费的顶层键不重复进 data

    def test_dirty_records_dropped_without_raising(self):
        raw = [
            {"model": "", "score": "10"},  # model_id 脏值 -> 丢弃
            "not-a-dict",  # 非映射 -> 丢弃
            {"model": "ok", "score": "N/A"},  # score 脏值 -> 0 且保留 score_raw
        ]
        records, _ = normalize_records(raw, snapshot_cfg())
        assert len(records) == 1
        assert records[0].benchmark_score == Decimal(0)
        assert records[0].data["score_raw"] == "N/A"

    def test_dict_payload_with_truncated_flag(self):
        raw = {"records": [{"model": "m", "score": "1"}], "truncated": True}
        records, truncated = normalize_records(raw, snapshot_cfg())
        assert len(records) == 1
        assert truncated is True

    def test_infrastructure_cost(self):
        cfg = snapshot_cfg(data_type="infrastructure_cost")
        cfg["normalize"] = {
            "fields": {"cost_type": "kind", "name": "gpu", "price": "hourly"}
        }
        records, _ = normalize_records(
            [{"kind": "gpu_rental", "gpu": "H100", "hourly": "$2.50", "unit": "hour"}], cfg
        )
        assert records == [
            CostRecord(
                cost_type="gpu_rental",
                name="H100",
                unit="hour",
                unit_price=Decimal("2.50"),
                region="default",
                source="demo",
                is_active=True,
                data={},
            )
        ]

    def test_subscription_plan(self):
        cfg = snapshot_cfg(data_type="subscription_plan")
        cfg["normalize"] = {"fields": {"monthly_price": "price"}}
        records, _ = normalize_records(
            [{"provider": "openai", "plan_key": "plus", "plan_name": "Plus", "price": "$20"}],
            cfg,
        )
        assert records == [
            SubscriptionPlanRecord(
                provider="openai",
                plan_key="plus",
                plan_name="Plus",
                monthly_price=Decimal(20),
                currency="USD",
                billing_cycle="monthly",
                is_active=True,
                source="fetch",
                data={},
            )
        ]

    def test_unknown_data_type_raises_config_error(self):
        with pytest.raises(ConfigError):
            normalize_records([], snapshot_cfg(data_type="mystery"))

    def test_idempotent(self):
        raw = [{"model": " GPT-4o ", "score": "89.5 分", "extra": 1}]
        first = normalize_records(raw, snapshot_cfg())
        second = normalize_records(raw, snapshot_cfg())
        assert first == second
