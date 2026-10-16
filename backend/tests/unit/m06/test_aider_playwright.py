"""M06 aider_leaderboard Playwright 方案：公开表格解析、单页终止、可用性。"""

from __future__ import annotations

import importlib.util
from decimal import Decimal

from helpers import FakePage, make_fetcher, table_row

from app.fetchers.sites.aider_leaderboard.playwright import collect_rows, parse_dom

FIELDS = {
    "model": "td:nth-child(2)",
    "score": "td:nth-child(3)",
    "cost": "td:nth-child(5)",
}


class TestParseDom:
    def test_extracts_leaderboard_rows(self):
        rows = [
            table_row({"td:nth-child(2)": " GPT-5 ", "td:nth-child(3)": "88.0%", "td:nth-child(5)": "$3.14"}),
            table_row({"td:nth-child(2)": "Claude Sonnet 4.5", "td:nth-child(3)": "77.2%", "td:nth-child(5)": "$1.02"}),
        ]
        assert parse_dom(rows, FIELDS) == [
            {"model": "GPT-5", "score": "88.0%", "cost": "$3.14"},
            {"model": "Claude Sonnet 4.5", "score": "77.2%", "cost": "$1.02"},
        ]


class TestCollectRows:
    def test_single_page_no_next_selector(self):
        cfg = {
            "rows_selector": "table tbody tr",
            "next_selector": None,
            "fields": FIELDS,
        }
        page = FakePage(
            [[table_row({"td:nth-child(2)": "GPT-5", "td:nth-child(3)": "88.0%", "td:nth-child(5)": "$3.14"})]],
            next_selector="button.next-page",
        )
        rows = collect_rows(page, cfg)
        assert len(rows) == 1
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
        raw = [
            {"model": " GPT-5 ", "score": "88.0%", "cost": "$3.14"},
            {"model": "", "score": "77.2%", "cost": "$1.02"},  # 脏行丢弃
        ]
        records, truncated = fetcher.normalize(raw)
        assert truncated is False
        assert len(records) == 1
        assert records[0].model_id == "gpt-5"
        assert records[0].provider == "aider"  # config defaults 填充
        assert records[0].domain == "coding"
        assert records[0].benchmark_score == Decimal("88.0")
