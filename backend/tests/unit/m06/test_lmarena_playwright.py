"""M06 lmarena Playwright 方案：榜单行解析、Camoufox 可用性判定、normalize 端到端。

注意：load_site 会做 is_available 筛查，camoufox 为重依赖不进 dev 环境，
故用例直接实例化 Fetcher 并按需补丁 importlib.util.find_spec。

单站点覆盖五个领域：fetch() 遍历 playwright.pages，每条记录带各自 domain；
标准化时只写维度分（维度名=领域），不参与跨源主榜分。
"""

from __future__ import annotations

import importlib.util
from typing import Any

import yaml
from helpers import SITES_DIR, FakeElement

from app.fetchers.sites.lmarena.playwright import Fetcher, collect_rows, parse_leaderboard

_CFG = yaml.safe_load((SITES_DIR / "lmarena" / "config.yaml").read_text(encoding="utf-8"))


def make_fetcher(**cfg_patches: Any) -> Fetcher:
    """直接实例化（绕过 load_site 的 is_available 筛查）。"""
    cfg = {**_CFG, **cfg_patches}
    return Fetcher(cfg)


def _page_cfg(domain: str = "chat") -> dict:
    return next(p for p in _CFG["playwright"]["pages"] if p["domain"] == domain)


def arena_row(
    model: str,
    vendor: str,
    score_text: str,
    *,
    title_attr: str | None = None,
    score_column: int = 4,
    total_cells: int = 6,
) -> FakeElement:
    """构造一行假 DOM：模型 span[title] + 厂商 svg title + 按列放置分数的 td 列表。"""
    cells = [FakeElement(text="") for _ in range(total_cells)]
    # 分数放在第 score_column 列（1-based）
    cells[score_column - 1] = FakeElement(text=score_text)
    return FakeElement(
        text=f"{model} {score_text}",
        children={
            "td span[title]": FakeElement(text=model, attrs={"title": title_attr or model}),
            "svg title": FakeElement(text=vendor),
        },
        children_all={"td": cells},
    )


class TestParseLeaderboard:
    def test_extracts_absolute_score(self):
        rows = [
            arena_row("Claude Opus 5.5 (Max)", "Anthropic", "1541±15"),
            arena_row("GPT-6 Astra (Max)", "OpenAI", "1814+12/-12"),
        ]
        assert parse_leaderboard(rows, score_column=4, domain="chat") == [
            {
                "model": "Claude Opus 5.5 (Max)",
                "vendor": "Anthropic",
                "score": "1541",
                "domain": "chat",
                "score_type": "absolute",
                "score_raw": "1541±15",
            },
            {
                "model": "GPT-6 Astra (Max)",
                "vendor": "OpenAI",
                "score": "1814",
                "domain": "chat",
                "score_type": "absolute",
                "score_raw": "1814+12/-12",
            },
        ]

    def test_extracts_percent_score(self):
        row = arena_row("Claude Opus 5.5 (Max)", "Anthropic", "20.14%±2.09%", score_column=3)
        records = parse_leaderboard([row], score_column=3, score_type="percent", domain="agent")
        assert records[0]["score"] == "20.14"
        assert records[0]["score_type"] == "percent"
        assert records[0]["domain"] == "agent"

    def test_prefers_title_attr_over_truncated_text(self):
        row = arena_row("Gemini 4 Argon (Hig…", "Google", "1300±10", title_attr="Gemini 4 Argon (High)")
        records = parse_leaderboard([row], score_column=4, domain="chat")
        assert records[0]["model"] == "Gemini 4 Argon (High)"

    def test_missing_vendor_and_score(self):
        row = FakeElement(
            text="Some Model",
            children={
                "td span[title]": FakeElement(text="Some Model", attrs={"title": "Some Model"}),
            },
            children_all={"td": [FakeElement(text="") for _ in range(6)]},
        )
        records = parse_leaderboard([row], score_column=4, domain="image")
        assert records == [
            {
                "model": "Some Model",
                "vendor": "",
                "score": "",
                "domain": "image",
                "score_type": "absolute",
                "score_raw": "",
            }
        ]

    def test_skips_row_without_model(self):
        empty = FakeElement(text="", children={}, children_all={"td": []})
        assert parse_leaderboard([empty], score_column=4) == []

    def test_dedupes_duplicate_rows(self):
        rows = [
            arena_row("Claude Opus 5.5 (Max)", "Anthropic", "1541±15"),
            arena_row("Claude Opus 5.5 (Max)", "Anthropic", "1541±15"),  # 重复，去重
            arena_row("GPT-6 Astra (Max)", "OpenAI", "1814+12/-12"),
        ]
        records = parse_leaderboard(rows, score_column=4)
        assert len(records) == 2


class _TablePage:
    """单页表格假页面。"""

    def __init__(self, rows: list[FakeElement]) -> None:
        self._rows = rows
        self.ready_selectors: list[str] = []

    def wait_for_selector(self, selector: str, timeout: int | None = None) -> None:
        self.ready_selectors.append(selector)

    def query_selector_all(self, selector: str) -> list[FakeElement]:
        return self._rows


class TestCollectRows:
    def test_parses_table_rows(self):
        cfg = _CFG["playwright"]
        rows = [
            arena_row("Claude Opus 5.5 (Max)", "Anthropic", "1541±15"),
            arena_row("GPT-6 Astra (Max)", "OpenAI", "1814+12/-12"),
        ]
        page = _TablePage(rows)
        records = collect_rows(page, cfg, _page_cfg("chat"))
        assert [r["model"] for r in records] == ["Claude Opus 5.5 (Max)", "GPT-6 Astra (Max)"]
        assert {r["domain"] for r in records} == {"chat"}
        assert page.ready_selectors == [cfg["rows_selector"]]

    def test_uses_page_score_column(self):
        cfg = _CFG["playwright"]
        rows = [arena_row("Claude Opus 5.5", "Anthropic", "20.14%±2.09%", score_column=3)]
        records = collect_rows(_TablePage(rows), cfg, _page_cfg("agent"))
        assert records[0]["score"] == "20.14"
        assert records[0]["domain"] == "agent"


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
    def test_elo_score_becomes_domain_dimension(self):
        fetcher = make_fetcher()
        raw = [
            {
                "model": " Claude Opus 5.5 (Max) ",
                "vendor": "Anthropic",
                "score": "1541",
                "domain": "chat",
                "score_type": "absolute",
                "score_raw": "1541±15",
            },
            {"model": "", "vendor": "?", "score": "-"},  # 脏行丢弃
        ]
        records, truncated = fetcher.normalize(raw)
        assert truncated is False
        assert len(records) == 1
        record = records[0]
        assert record.model_id == "claude-opus-5.5"  # 推理档位括号 (max) 剥离，分隔符归一
        assert record.provider == "anthropic"  # vendor 映射为 provider，统一小写
        assert record.domain == "chat"
        # Elo 分只进维度分，不写主榜分（跨源量纲不可比）
        assert record.benchmark_score is None
        assert record.scores == {"chat": 1541.0}
        entry = record.data["sources"]["lmarena_chat"]
        assert entry["benchmark_score"] is None
        assert entry["record"]["score_raw"] == "1541±15"

    def test_percent_score_becomes_agent_dimension(self):
        fetcher = make_fetcher()
        raw = [
            {
                "model": "GPT-6 Astra",
                "vendor": "OpenAI",
                "score": "20.14",
                "domain": "agent",
                "score_type": "percent",
                "score_raw": "20.14%±2.09%",
            }
        ]
        records, _ = fetcher.normalize(raw)
        record = records[0]
        assert record.benchmark_score is None
        assert record.scores == {"agent": 20.14}
        assert record.data["sources"]["lmarena_agent"]["domain"] == "agent"

    def test_provider_fallback_to_site_key(self):
        fetcher = make_fetcher()
        raw = [
            {
                "model": "Qwen3-Max",
                "vendor": "",
                "score": "1200",
                "domain": "code",
                "score_type": "absolute",
            }
        ]
        records, _ = fetcher.normalize(raw)
        assert len(records) == 1
        assert records[0].provider == "lmarena"  # vendor 缺失回落站点 key
        assert records[0].scores == {"code": 1200.0}
