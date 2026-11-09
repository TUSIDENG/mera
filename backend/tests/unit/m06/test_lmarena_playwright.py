"""M06 lmarena Playwright 方案：表头驱动解析、领域过滤、Camoufox 可用性、normalize 端到端。

注意：load_site 会做 is_available 筛查，camoufox 为重依赖不进 dev 环境，
故用例直接实例化 Fetcher 并按需补丁 importlib.util.find_spec。

站点覆盖五个领域共 14 个子分类：任务可指定领域只采该领域页面；
每个领域只用主榜子分类写维度分，其余子分类保留来源明细。
"""

from __future__ import annotations

import importlib.util
from typing import Any

import yaml
from helpers import SITES_DIR, FakeElement

from app.fetchers.sites.lmarena.playwright import (
    Fetcher,
    collect_rows,
    parse_leaderboard,
    select_pages,
)

_CFG = yaml.safe_load((SITES_DIR / "lmarena" / "config.yaml").read_text(encoding="utf-8"))
_PW_CFG = _CFG["playwright"]

# 对话/图像类榜单列（8 列）
_STD_HEADERS = [
    "Rank",
    "Rank Spread",
    "Model",
    "Score",
    "Votes",
    "Cost/Task (P50)",
    "Price $/M",
    "Context",
]


def make_fetcher(**cfg_patches: Any) -> Fetcher:
    """直接实例化（绕过 load_site 的 is_available 筛查）。"""
    return Fetcher({**_CFG, **cfg_patches})


def _page_cfg(domain: str = "chat", sub: str = "text") -> dict:
    return next(
        page for page in _PW_CFG["pages"] if page["domain"] == domain and page["sub"] == sub
    )


def std_row(
    model: str,
    vendor: str,
    score_text: str,
    *,
    license_text: str = "Proprietary",
    rank: str = "1",
    votes: str = "1,234",
    cost: str = "$0.01",
    price: str = "$2 / $10",
    context: str = "1M",
    headers: list[str] | None = None,
) -> FakeElement:
    """构造标准榜单行：模型名 + 次行「厂商 · 许可证」+ 分数/票数/价格/上下文。"""
    labels = headers or _STD_HEADERS
    values = {
        "Rank": rank,
        "Rank Spread": "1 ↔ 1",
        "Model": f"{model}\n{vendor} · {license_text}" if vendor else model,
        "Score": score_text,
        "Net Improvement": score_text,
        "Votes": votes,
        "Cost/Task (P50)": cost,
        "Price $/M": price,
        "Context": context,
    }
    cells = []
    for label in labels:
        text = values.get(label, "")
        if label == "Model":
            cells.append(
                FakeElement(
                    text=text,
                    children={"span[title]": FakeElement(text=model, attrs={"title": model})},
                )
            )
        else:
            cells.append(FakeElement(text=text))
    return FakeElement(text="", children_all={"td": cells})


class TestParseLeaderboard:
    def test_extracts_all_standard_columns(self):
        row = std_row("Claude Opus 5.5 (Max)", "Anthropic", "1541±15")
        records = parse_leaderboard([row], _STD_HEADERS, "chat", "text")
        assert len(records) == 1
        record = records[0]
        assert record["model"] == "Claude Opus 5.5 (Max)"
        assert record["vendor"] == "Anthropic"
        assert record["license"] == "Proprietary"
        assert record["score"] == "1541"
        assert record["score_raw"] == "1541±15"
        assert record["domain"] == "chat"
        assert record["sub"] == "text"
        assert record["rank"] == 1
        assert record["rank_spread"] == "1 ↔ 1"
        assert record["votes"] == 1234
        assert record["cost_per_task_p50"] == "$0.01"
        assert (record["price_input"], record["price_output"]) == (2.0, 10.0)
        assert record["context_window"] == 1_000_000
        # 整行原始列全部保留，便于后续分析
        assert record["columns"]["Votes"] == "1,234"
        assert record["columns"]["Price $/M"] == "$2 / $10"

    def test_percent_score_and_short_headers(self):
        headers = ["Rank", "Model", "Net Improvement", "Votes"]
        row = std_row("Claude Opus 5.5 (Max)", "Anthropic", "20.14%±2.09%", headers=headers)
        records = parse_leaderboard([row], headers, "agent", "capabilities")
        assert records[0]["score"] == "20.14"
        assert records[0]["sub"] == "capabilities"

    def test_missing_price_and_context_are_null(self):
        row = std_row("Some Model", "Krea", "1200±8", price="N/A", context="N/A", cost="")
        record = parse_leaderboard([row], _STD_HEADERS, "image", "text-to-image")[0]
        assert record["price_input"] is None
        assert record["price_output"] is None
        assert record["context_window"] is None
        assert record["cost_per_task_p50"] is None

    def test_model_without_vendor_has_empty_vendor(self):
        row = std_row("veo-3.1-(audio)", "", "1541±15")
        record = parse_leaderboard([row], _STD_HEADERS, "video", "text-to-video")[0]
        assert record["model"] == "veo-3.1-(audio)"
        assert record["vendor"] == ""
        assert record["license"] == ""

    def test_prefers_title_attr_over_truncated_text(self):
        cells = [
            FakeElement(text="1"),
            FakeElement(text="1 ↔ 1"),
            FakeElement(
                text="Gemini 4 Argon (Hig…\nGoogle · Proprietary",
                children={
                    "span[title]": FakeElement(text="", attrs={"title": "Gemini 4 Argon (High)"})
                },
            ),
        ] + [FakeElement(text="") for _ in range(5)]
        row = FakeElement(text="", children_all={"td": cells})
        record = parse_leaderboard([row], _STD_HEADERS, "chat", "text")[0]
        assert record["model"] == "Gemini 4 Argon (High)"

    def test_skips_row_without_cells(self):
        assert parse_leaderboard([FakeElement(text="", children_all={"td": []})], _STD_HEADERS) == []

    def test_dedupes_duplicate_rows(self):
        rows = [
            std_row("Claude Opus 5.5 (Max)", "Anthropic", "1541±15"),
            std_row("Claude Opus 5.5 (Max)", "Anthropic", "1541±15"),
            std_row("GPT-6 Astra (Max)", "OpenAI", "1814+12/-12"),
        ]
        assert len(parse_leaderboard(rows, _STD_HEADERS)) == 2


class _TablePage:
    """单页表格假页面：表头与榜单行分开返回。"""

    def __init__(self, rows: list[FakeElement], headers: list[str]) -> None:
        self._rows = rows
        self._headers = [FakeElement(text=header) for header in headers]
        self.ready_selectors: list[str] = []

    def wait_for_selector(self, selector: str, timeout: int | None = None) -> None:
        self.ready_selectors.append(selector)

    def wait_for_timeout(self, timeout: int) -> None:
        pass

    def query_selector_all(self, selector: str) -> list[FakeElement]:
        if selector == _PW_CFG["header_selector"]:
            return self._headers
        return self._rows


class TestCollectRows:
    def test_parses_all_rows_with_headers(self):
        rows = [
            std_row("Claude Opus 5.5 (Max)", "Anthropic", "1541±15"),
            std_row("GPT-6 Astra (Max)", "OpenAI", "1814+12/-12"),
        ]
        page = _TablePage(rows, _STD_HEADERS)
        records = collect_rows(page, _PW_CFG, _page_cfg("chat", "text"))
        assert [r["model"] for r in records] == ["Claude Opus 5.5 (Max)", "GPT-6 Astra (Max)"]
        assert {r["domain"] for r in records} == {"chat"}
        assert page.ready_selectors == [_PW_CFG["rows_selector"]]


class TestSelectPages:
    def test_all_pages_when_domain_empty(self):
        assert len(select_pages(_PW_CFG["pages"], None)) == 14

    def test_filters_by_domain(self):
        chat_pages = select_pages(_PW_CFG["pages"], "chat")
        assert [page["sub"] for page in chat_pages] == ["text", "search", "vision", "document"]

    def test_unknown_domain_returns_empty(self):
        assert select_pages(_PW_CFG["pages"], "audio") == []


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


def _raw(**overrides: Any) -> dict:
    record = {
        "model": "Claude Opus 5.5 (Max)",
        "vendor": "Anthropic",
        "license": "Proprietary",
        "score": "1541",
        "score_raw": "1541±15",
        "domain": "chat",
        "sub": "text",
        "rank": 1,
        "rank_spread": "1 ↔ 1",
        "votes": 1234,
        "cost_per_task_p50": "$0.01",
        "price_input": 2.0,
        "price_output": 10.0,
        "context_window": 1_000_000,
        "columns": {"Votes": "1,234"},
    }
    record.update(overrides)
    return record


class TestNormalizeEndToEnd:
    def test_primary_sub_writes_domain_dimension(self):
        records, truncated = make_fetcher().normalize([_raw()])
        assert truncated is False
        record = records[0]
        assert record.model_id == "claude-opus-5.5"
        assert record.provider == "anthropic"
        assert record.domain == "chat"
        # Elo 分只进维度分，不写主榜分（跨源量纲不可比）
        assert record.benchmark_score is None
        assert record.scores == {"chat": 1541.0}
        entry = record.data["sources"]["lmarena_text"]
        assert entry["benchmark_score"] is None
        assert entry["sub"] == "text"
        # 非标准字段（价格/票数/上下文）保留在来源原始记录里
        assert entry["record"]["votes"] == 1234
        assert entry["record"]["price_input"] == 2.0
        assert entry["record"]["context_window"] == 1_000_000

    def test_secondary_sub_keeps_no_dimension(self):
        raw = _raw(domain="chat", sub="search", score="1490")
        records, _ = make_fetcher().normalize([raw])
        record = records[0]
        assert record.scores == {}
        assert record.benchmark_score is None
        assert record.data["sources"]["lmarena_search"]["record"]["score"] == "1490"

    def test_agent_primary_sub_maps_percent(self):
        raw = _raw(domain="agent", sub="capabilities", score="20.14")
        record = make_fetcher().normalize([raw])[0][0]
        assert record.scores == {"agent": 20.14}

    def test_missing_vendor_falls_back_to_unknown_not_site(self):
        raw = _raw(model="veo-3.1-(audio)", vendor="", domain="video", sub="text-to-video")
        record = make_fetcher().normalize([raw])[0][0]
        assert record.provider == "unknown"
        assert record.scores == {"video": 1541.0}
