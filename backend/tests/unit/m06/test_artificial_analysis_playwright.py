"""M06 artificial_analysis Playwright 方案：DOM 解析、翻页循环、可用性、指纹浏览器 Local API。"""

from __future__ import annotations

import importlib.util
from typing import ClassVar

import pytest
import responses
from helpers import FakePage, make_fetcher, table_row

from app.core.exceptions import FetchFailed
from app.fetchers.sites.artificial_analysis.playwright import (
    collect_rows,
    parse_dom,
    start_fp_browser,
)

FIELDS = {
    "model": "td:nth-child(1)",
    "score": "td:nth-child(2)",
    "provider": "td:nth-child(3)",
}


class TestParseDom:
    def test_extracts_fields(self):
        rows = [
            table_row({"td:nth-child(1)": " GPT-4o ", "td:nth-child(2)": "89.5", "td:nth-child(3)": "OpenAI"}),
            table_row({"td:nth-child(1)": "Claude 4", "td:nth-child(2)": "90.1", "td:nth-child(3)": "Anthropic"}),
        ]
        assert parse_dom(rows, FIELDS) == [
            {"model": "GPT-4o", "score": "89.5", "provider": "OpenAI"},
            {"model": "Claude 4", "score": "90.1", "provider": "Anthropic"},
        ]

    def test_missing_cell_yields_none(self):
        rows = [table_row({"td:nth-child(1)": "GPT-4o"})]
        assert parse_dom(rows, FIELDS)[0]["score"] is None


class TestCollectRows:
    def pw_cfg(self) -> dict:
        return {
            "rows_selector": "table.leaderboard tbody tr",
            "next_selector": "button.next-page",
            "fields": FIELDS,
        }

    def test_pagination_loop_terminates_at_last_page(self):
        page1 = [table_row({"td:nth-child(1)": "m1", "td:nth-child(2)": "1", "td:nth-child(3)": "p"})]
        page2 = [table_row({"td:nth-child(1)": "m2", "td:nth-child(2)": "2", "td:nth-child(3)": "p"})]
        page = FakePage([page1, page2])
        rows = collect_rows(page, self.pw_cfg())
        assert [r["model"] for r in rows] == ["m1", "m2"]
        assert page.clicks == 1
        assert page.waits == [1500]

    def test_single_page_when_no_next(self):
        page = FakePage(
            [[table_row({"td:nth-child(1)": "m1", "td:nth-child(2)": "1", "td:nth-child(3)": "p"})]]
        )
        rows = collect_rows(page, self.pw_cfg())
        assert len(rows) == 1
        assert page.clicks == 0


class TestAvailability:
    def test_unavailable_without_playwright_package(self, monkeypatch):
        real_find_spec = importlib.util.find_spec

        def fake_find_spec(name, *args, **kwargs):
            if name == "playwright":
                return None
            return real_find_spec(name, *args, **kwargs)

        monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
        fetcher = make_fetcher("artificial_analysis", "playwright")
        assert fetcher.is_available() is False
        assert fetcher.unavailable_reason == "未安装 playwright"

    def test_unknown_fp_provider_unavailable(self, monkeypatch):
        monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a, **k: object())
        fetcher = make_fetcher("artificial_analysis", "playwright")
        fetcher.cfg["playwright"]["fingerprint_browser"] = {
            "enabled": True,
            "provider": "unknown",
        }
        assert fetcher.is_available() is False
        assert "unknown" in fetcher.unavailable_reason

    def test_adspower_requires_local_api_and_profile(self, monkeypatch):
        monkeypatch.setattr(importlib.util, "find_spec", lambda name, *a, **k: object())
        fetcher = make_fetcher("artificial_analysis", "playwright")
        fetcher.cfg["playwright"]["fingerprint_browser"] = {
            "enabled": True,
            "provider": "adspower",
        }
        assert fetcher.is_available() is False
        assert "local_api/profile_id" in fetcher.unavailable_reason


class TestStartFpBrowser:
    FP: ClassVar[dict] = {
        "local_api": "http://host.docker.internal:50325",
        "profile_id": "mera_aa_01",
        "startup_wait_sec": 30,
    }

    @responses.activate
    def test_returns_cdp_endpoint(self):
        responses.get(
            "http://host.docker.internal:50325/api/v1/browser/start",
            json={"code": 0, "data": {"ws": {"selenium": "ws://127.0.0.1:9222/devtools/abc"}}},
        )
        assert start_fp_browser(self.FP) == "ws://127.0.0.1:9222/devtools/abc"
        query = responses.calls[0].request.url
        assert "user_id=mera_aa_01" in query

    @responses.activate
    def test_start_failure_raises_fetch_failed(self):
        responses.get(
            "http://host.docker.internal:50325/api/v1/browser/start",
            json={"code": -1, "msg": "profile not found"},
        )
        with pytest.raises(FetchFailed, match="启动失败"):
            start_fp_browser(self.FP)
