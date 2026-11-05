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
            ("Claude   Sonnet  4", "claude-sonnet-4"),
            ("glm-4.6", "glm-4.6"),
            # vendor 前缀剥离
            ("anthropic/claude-opus-5", "claude-opus-5"),
            ("openai/gpt-5.1-codex-mini", "gpt-5.1-codex-mini"),  # mini 是独立 SKU，不剥
            ("~openai/gpt-astra-latest", "gpt-astra-latest"),  # openrouter "~" 别名前缀
            # 冒号变体后缀剥离（循环）
            ("claude-opus-5:batch", "claude-opus-5"),
            ("google/gemini-3-pro:high:batch", "gemini-3-pro"),
            # 推理档位括号剥离
            ("claude opus 5.5 (high with fallback)", "claude-opus-5.5"),
            ("Claude Opus 5.5 (max)", "claude-opus-5.5"),
            ("Claude Opus 5.5 (high, default fallback)", "claude-opus-5.5"),
            ("GPT-6.1 Sol (Xhigh)", "gpt-6.1-sol"),
            # 版本号差异不合并
            ("claude-opus-5", "claude-opus-5"),
            ("claude-opus-5.5", "claude-opus-5.5"),
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
                scores={},
                score_source="score",
                data={
                    "sources": {
                        "demo": {"raw_model_id": "GPT-4o", "record": raw[0]},
                    }
                },
                raw_model_id="GPT-4o",
                source_key="demo",
            )
        ]

    def test_scores_mapping_and_fallback(self):
        """scores 映射产出多维分；score 字段缺失时按 intelligence->coding->agentic 回落。"""
        cfg = snapshot_cfg()
        cfg["normalize"]["scores"] = {
            "intelligence": "aa.intelligence_index",
            "coding": "aa.coding_index",
            "agentic": "aa.agentic_index",
        }
        cfg["normalize"]["fields"] = {"model_id": "model"}
        raw = [
            {"model": "m1", "aa": {"intelligence_index": 51, "coding_index": None}},
            {"model": "m2", "aa": {"intelligence_index": None, "coding_index": 70.1}},
            {"model": "m3", "aa": {}},  # 全部维度缺失 -> benchmark_score=None
        ]
        records, _ = normalize_records(raw, cfg)
        assert records[0].scores == {"intelligence": 51.0, "coding": None, "agentic": None}
        assert records[0].benchmark_score == Decimal(51)
        assert records[0].score_source == "intelligence"
        assert records[1].benchmark_score == Decimal("70.1")
        assert records[1].score_source == "coding"
        assert records[2].benchmark_score is None
        assert records[2].score_source is None
        # 原始维度路径保留在 data.sources 的采集记录里
        assert records[0].data["sources"]["demo"]["record"]["aa"]

    def test_api_price_record(self):
        cfg = snapshot_cfg(data_type="api_price")
        cfg["normalize"] = {
            "defaults": {"provider": "openrouter", "currency": "USD", "unit": "token"},
            "fields": {"model_id": "id", "input_price": "pricing.prompt"},
        }
        records, _ = normalize_records(
            [
                {"id": "openai/gpt-5", "pricing": {"prompt": "0.00000075"}},
                {"id": "no-price"},  # 双边价格均缺失 -> 丢弃
            ],
            cfg,
        )
        assert len(records) == 1
        record = records[0]
        assert record.model_id == "gpt-5"  # vendor 前缀剥离，便于与榜单按 model_id 关联
        assert record.provider == "openrouter"  # 价格域保留聚合平台作为厂商
        assert record.input_price == Decimal("0.00000075")
        assert record.output_price is None
        assert record.currency == "USD"
        assert record.unit == "token"
        assert record.source == "demo"

    def test_data_type_override(self):
        """调用方按任务类型覆盖站点 data_type。"""
        cfg = snapshot_cfg()
        cfg["normalize"] = {
            "defaults": {"provider": "demo"},
            "fields": {"model_id": "id", "input_price": "pricing.prompt"},
        }
        records, _ = normalize_records(
            [{"id": "m", "pricing": {"prompt": "1"}}],
            cfg,
            data_type="api_price",
        )
        assert len(records) == 1

    def test_provider_vendor_prefix_wins_over_defaults(self):
        """榜单厂商优先取模型 id 的 vendor 前缀（真实研发厂商），defaults 不覆盖。"""
        cfg = snapshot_cfg()
        cfg["normalize"] = {
            "defaults": {"provider": "openrouter"},
            "fields": {"model_id": "id"},
        }
        records, _ = normalize_records([{"id": "a/b"}], cfg)
        assert records[0].provider == "a"

    def test_provider_lowercased(self):
        """provider 统一小写（OpenAI/openai 归一，避免同一厂商多行）。"""
        cfg = snapshot_cfg()
        cfg["normalize"]["fields"] = {"model_id": "model", "provider": "vendor"}
        records, _ = normalize_records([{"model": "m", "vendor": "Anthropic"}], cfg)
        assert records[0].provider == "anthropic"

    def test_provider_defaults_fallback_without_vendor(self):
        """无 vendor 前缀且记录缺 provider 时回落 defaults（单来源站点）。"""
        cfg = snapshot_cfg()
        cfg["normalize"] = {
            "defaults": {"provider": "aider"},
            "fields": {"model_id": "id"},
        }
        records, _ = normalize_records([{"id": "gpt-4o"}], cfg)
        assert records[0].provider == "aider"

    def test_nested_field_path(self):
        cfg = snapshot_cfg()
        cfg["normalize"]["fields"] = {"model_id": "id", "input_price": "pricing.prompt"}
        records, _ = normalize_records(
            [{"id": "m", "provider": "p", "pricing": {"prompt": "$3.00"}}], cfg
        )
        # 原始字段完整保留在 data.sources 的采集记录里
        entry = records[0].data["sources"]["demo"]["record"]
        assert entry["pricing"] == {"prompt": "$3.00"}

    def test_dirty_records_dropped_without_raising(self):
        raw = [
            {"model": "", "score": "10"},  # model_id 脏值 -> 丢弃
            "not-a-dict",  # 非映射 -> 丢弃
            {"model": "ok", "score": "N/A"},  # score 脏值 -> 无分且保留 score_raw
        ]
        records, _ = normalize_records(raw, snapshot_cfg())
        assert len(records) == 1
        assert records[0].benchmark_score is None
        assert records[0].score_source is None
        assert records[0].data["sources"]["demo"]["score_raw"] == "N/A"

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
