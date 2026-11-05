"""M06 lmarena Playwright 方案：榜单行解析、Camoufox 可用性判定、normalize 端到端。

注意：load_site 会做 is_available 筛查，camoufox 为重依赖不进 dev 环境，
故用例直接实例化 Fetcher 并按需补丁 importlib.util.find_spec。
"""

from __future__ import annotations

import importlib.util
from decimal import Decimal
from typing import Any

from helpers import FakeElement, site_config

from app.fetchers.sites.lmarena.playwright import Fetcher, collect_rows, parse_leaderboard


def make_fetcher(**cfg_patches: Any) -> Fetcher:
    """直接实例化（绕过 load_site 的 is_available 筛查），可补丁 cfg 顶层键。"""
    cfg = site_config("lmarena")
    cfg.update(cfg_patches)
    return Fetcher(cfg)


def arena_row(
    rank: str,
    model: str,
    vendor: str,
    score: str,
    *,
    title_attr: str | None = None,
) -> FakeElement:
    """构造一行假 DOM：span[title]（模型名）+ svg title（厂商）+ 行文本（排名/百分数）。"""
    text = f"{rank}\n{model}\n{score}"
    return FakeElement(
        text=text,
        children={
            "span[title]": FakeElement(text=model, attrs={"title": title_attr or model}),
            "svg title": FakeElement(text=vendor),
        },
    )


class TestParseLeaderboard:
    def test_extracts_rows(self):
        rows = [
            arena_row("1", "Claude Opus 5.5 (Max)", "Anthropic", "18.88%"),
            arena_row("2", "GPT-6 Astra (Max)", "OpenAI", "14.13%"),
        ]
        assert parse_leaderboard(rows) == [
            {"rank": "1", "model": "Claude Opus 5.5 (Max)", "vendor": "Anthropic", "score": "18.88"},
            {"rank": "2", "model": "GPT-6 Astra (Max)", "vendor": "OpenAI", "score": "14.13"},
        ]

    def test_prefers_title_attr_over_truncated_text(self):
        row = arena_row("3", "Gemini 4 Argon (Hig…", "Google", "13.23%", title_attr="Gemini 4 Argon (High)")
        records = parse_leaderboard([row])
        assert records[0]["model"] == "Gemini 4 Argon (High)"

    def test_missing_vendor_and_score(self):
        row = FakeElement(
            text="5\nSome Model",
            children={"span[title]": FakeElement(text="Some Model", attrs={"title": "Some Model"})},
        )
        records = parse_leaderboard([row])
        assert records == [{"rank": "5", "model": "Some Model", "vendor": "", "score": ""}]

    def test_skips_row_without_model(self):
        empty = FakeElement(text="", children={})
        assert parse_leaderboard([empty]) == []

    def test_dedupes_hidden_dom_copies(self):
        rows = [
            arena_row("1", "Claude Opus 5.5 (Max)", "Anthropic", "18.88%"),
            arena_row("", "Claude Opus 5.5 (Max)", "Anthropic", "18.88%"),  # 隐藏副本，去重
            arena_row("2", "GPT-6 Astra (Max)", "OpenAI", "14.13%"),
        ]
        records = parse_leaderboard(rows)
        assert len(records) == 2
        assert records[0]["rank"] == "1"  # 保留首条（带排名）


class _SectionPage:
    """多区块假页面：query_selector_all 命中 section_selector 时返回区块列表。"""

    def __init__(self, sections: list[FakeElement], section_selector: str) -> None:
        self._sections = sections
        self._section_selector = section_selector
        self.ready_selectors: list[str] = []

    def wait_for_selector(self, selector: str, timeout: int | None = None) -> None:
        self.ready_selectors.append(selector)

    def query_selector_all(self, selector: str) -> list[FakeElement]:
        return self._sections if selector == self._section_selector else []


class TestCollectRows:
    def test_scopes_to_first_section(self):
        cfg = site_config("lmarena")["playwright"]
        main = FakeElement(
            children_all={
                cfg["rows_selector"]: [
                    arena_row("1", "Claude Opus 5.5 (Max)", "Anthropic", "18.88%"),
                    arena_row("2", "GPT-6 Astra (Max)", "OpenAI", "14.13%"),
                ]
            }
        )
        secondary = FakeElement(
            children_all={cfg["rows_selector"]: [arena_row("4", "Solar Pro 4", "Upstage", "20.06%")]}
        )
        page = _SectionPage([main, secondary], cfg["section_selector"])
        records = collect_rows(page, cfg)
        assert [r["model"] for r in records] == ["Claude Opus 5.5 (Max)", "GPT-6 Astra (Max)"]
        assert page.ready_selectors == [f"{cfg['section_selector']} {cfg['rows_selector']}"]


def _patch_find_spec(monkeypatch, camoufox_present: bool):
    real_find_spec = importlib.util.find_spec

    def fake_find_spec(name, *args, **kwargs):
        if name == "camoufox":
            return object() if camoufox_present else None
        return real_find_spec(name, *args, **kwargs)

    monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)


class TestAvailability:
    def test_unavailable_without_camoufox(self, monkeypatch):
        _patch_find_spec(monkeypatch, camoufox_present=False)
        fetcher = make_fetcher()
        assert fetcher.is_available() is False
        assert "camoufox" in (fetcher.unavailable_reason or "")

    def test_unavailable_when_fingerprint_disabled(self, monkeypatch):
        _patch_find_spec(monkeypatch, camoufox_present=True)
        fetcher = make_fetcher(playwright={"fingerprint_browser": {"enabled": False}})
        assert fetcher.is_available() is False
        assert "必须启用指纹浏览器" in (fetcher.unavailable_reason or "")

    def test_unavailable_with_unknown_provider(self, monkeypatch):
        _patch_find_spec(monkeypatch, camoufox_present=True)
        fetcher = make_fetcher(
            playwright={"fingerprint_browser": {"enabled": True, "provider": "unknown"}}
        )
        assert fetcher.is_available() is False
        assert "未知指纹浏览器" in (fetcher.unavailable_reason or "")

    def test_available_with_camoufox(self, monkeypatch):
        _patch_find_spec(monkeypatch, camoufox_present=True)
        fetcher = make_fetcher()
        assert fetcher.is_available() is True
        assert fetcher.unavailable_reason is None


class TestNormalizeEndToEnd:
    def test_rows_to_snapshot_records(self):
        fetcher = make_fetcher()
        raw = [
            {"rank": "1", "model": " Claude Opus 5.5 (Max) ", "vendor": "Anthropic", "score": "18.88"},
            {"rank": "-", "model": "", "vendor": "?", "score": "-"},  # 脏行丢弃
        ]
        records, truncated = fetcher.normalize(raw)
        assert truncated is False
        assert len(records) == 1
        record = records[0]
        assert record.model_id == "claude-opus-5.5"  # 推理档位括号 (max) 剥离，分隔符归一
        assert record.provider == "anthropic"  # vendor 映射为 provider，统一小写
        assert record.domain == "chat"
        assert record.benchmark_score == Decimal("18.88")
        assert record.data["sources"]["lmarena"]["record"]["rank"] == "1"

    def test_provider_fallback_to_site_key(self):
        fetcher = make_fetcher()
        raw = [{"rank": "3", "model": "Qwen3-Max", "vendor": "", "score": "12.5"}]
        records, _ = fetcher.normalize(raw)
        assert len(records) == 1
        assert records[0].provider == "lmarena"  # defaults 回落
