"""M06 aider_leaderboard Playwright 方案：公开表格解析、单页终止、可用性。"""

from __future__ import annotations

import importlib.util
from decimal import Decimal

import pytest
from helpers import FakePage, make_fetcher, table_row

from app.fetchers.sites.aider_leaderboard.playwright import (
    collect_rows,
    guess_provider,
    parse_dom,
)

FIELDS = {
    "model": "td:nth-child(2)",
    "score": "td:nth-child(3)",
    "cost": "td:nth-child(4)",
}


class TestGuessProvider:
    @pytest.mark.parametrize(
        ("model", "expected"),
        [
            ("GPT-5 (high)", "openai"),
            ("o3-pro (high)", "openai"),
            ("chatgpt-4o-latest (2025-03-29)", "openai"),
            ("claude-opus-4-20250514 (32k thinking)", "anthropic"),
            ("Gemini 2.5 Pro Preview 06-05", "google"),
            ("gemma-3-27b-it", "google"),
            ("Grok 4 (high)", "x-ai"),
            ("DeepSeek R1 + claude-3-5-sonnet-20241022", "deepseek"),
            ("Qwen3 235B A22B diff, no think, Alibaba API", "qwen"),
            ("QwQ-32B", "qwen"),
            ("Kimi K2", "moonshotai"),
            ("Llama 4 Maverick", "meta"),
            ("command-a-03-2025-quality", "cohere"),
            ("Codestral 25.01", "mistralai"),
            ("some-new-model", "unknown"),
            (None, "unknown"),
        ],
    )
    def test_vendor_mapping(self, model, expected):
        assert guess_provider(model) == expected


class TestParseDom:
    def test_extracts_leaderboard_rows(self):
        rows = [
            table_row({"td:nth-child(1)": "▶", "td:nth-child(2)": " GPT-5 ", "td:nth-child(3)": "88.0%", "td:nth-child(4)": "$29.08"}),
            table_row({"td:nth-child(1)": "▶", "td:nth-child(2)": "Claude Sonnet 4.5", "td:nth-child(3)": "77.2%", "td:nth-child(4)": "$1.02"}),
        ]
        assert parse_dom(rows, FIELDS) == [
            {"model": "GPT-5", "score": "88.0%", "cost": "$29.08", "provider": "openai"},
            {"model": "Claude Sonnet 4.5", "score": "77.2%", "cost": "$1.02", "provider": "anthropic"},
        ]


class TestCollectRows:
    def test_single_page_no_next_selector(self):
        cfg = {
            "rows_selector": "table tbody tr",
            "next_selector": None,
            "fields": FIELDS,
        }
        page = FakePage(
            [[table_row({"td:nth-child(2)": "GPT-5", "td:nth-child(3)": "88.0%", "td:nth-child(4)": "$29.08"})]],
            next_selector="button.next-page",
        )
        rows = collect_rows(page, cfg)
        assert len(rows) == 1
        assert rows[0]["cost"] == "$29.08"
        assert rows[0]["provider"] == "openai"
        assert page.clicks == 0  # next_selector 为空，立即终止


class TestAvailability:
    def test_unavailable_without_playwright_package(self, monkeypatch):
        real_find_spec = importlib.util.find_spec

        def fake_find_spec(name, *args, **kwargs):
            if name == "playwright":
                return None
            return real_find_spec(name, *args, **kwargs)

        monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
        fetcher = make_fetcher("aider_leaderboard", "playwright")
        assert fetcher.is_available() is False
        assert fetcher.unavailable_reason == "未安装 playwright"


class TestNormalizeEndToEnd:
    def test_dom_rows_to_snapshot_records(self):
        fetcher = make_fetcher("aider_leaderboard", "playwright")
        raw = parse_dom(
            [
                table_row({"td:nth-child(2)": " GPT-5 ", "td:nth-child(3)": "88.0%", "td:nth-child(4)": "$29.08"}),
                table_row({"td:nth-child(2)": "", "td:nth-child(3)": "77.2%", "td:nth-child(4)": "$1.02"}),  # 脏行丢弃
            ],
            FIELDS,
        )
        records, truncated = fetcher.normalize(raw)
        assert truncated is False
        assert len(records) == 1
        assert records[0].model_id == "gpt-5"
        assert records[0].provider == "openai"  # 由模型名推断，不再回落到站点 key
        assert records[0].domain == "coding"
        assert records[0].benchmark_score == Decimal("88.0")
        # 成本列取第 4 列（首列是展开箭头占位），原始值保留在采集记录里
        assert records[0].data["sources"]["aider_leaderboard"]["record"]["cost"] == "$29.08"
