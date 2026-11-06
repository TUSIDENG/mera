"""Aider 榜单 Playwright 方案：解析公开榜单页表格（无需登录、无指纹浏览器）。

parse_dom/collect_rows 可注入假 page 单测；fetch() 只做浏览器编排。
"""

from __future__ import annotations

import importlib.util
from typing import Any

from app.fetchers.base import BaseFetcher, collect_paginated_rows, parse_dom_rows
from app.fetchers.proxy import proxy_kwargs

# 榜单表格无厂商列，按模型名前缀归并到与 openrouter 一致的厂商名；
# 前缀按“更具体优先”排列（如 qwq 先于 qwen、chatgpt 先于 gpt）
_VENDOR_PREFIXES: tuple[tuple[str, str], ...] = (
    ("chatgpt", "openai"),
    ("claude", "anthropic"),
    ("codestral", "mistralai"),
    ("command", "cohere"),
    ("deepseek", "deepseek"),
    ("gemini", "google"),
    ("gemma", "google"),
    ("gpt", "openai"),
    ("grok", "x-ai"),
    ("kimi", "moonshotai"),
    ("llama", "meta"),
    ("o1", "openai"),
    ("o3", "openai"),
    ("o4", "openai"),
    ("openhands", "all-hands"),
    ("optimus", "openrouter"),
    ("qwq", "qwen"),
    ("qwen", "qwen"),
    ("quasar", "openrouter"),
    ("yi", "01-ai"),
)

UNKNOWN_PROVIDER = "unknown"


def guess_provider(model: Any) -> str:
    """由模型名推断厂商；无法识别时返回 unknown（不回落成站点 key，避免伪造厂商）。"""
    name = str(model or "").strip().lower()
    for prefix, vendor in _VENDOR_PREFIXES:
        if name.startswith(prefix):
            return vendor
    return UNKNOWN_PROVIDER


def _with_provider(items: list[dict]) -> list[dict]:
    """补齐厂商字段（供 normalize.fields.provider 读取）。"""
    for item in items:
        item["provider"] = guess_provider(item.get("model"))
    return items


def parse_dom(rows: list[Any], fields: dict[str, str]) -> list[dict]:
    """DOM 解析纯函数（字段选择器来自 config.yaml）。"""
    return _with_provider(parse_dom_rows(rows, fields))


def collect_rows(page: Any, pw_cfg: dict) -> list[dict]:
    """翻页采集循环（本站点为单页榜单，next_selector 为空时采一页即止）。"""
    return _with_provider(collect_paginated_rows(page, pw_cfg))


class Fetcher(BaseFetcher):
    strategy = "playwright"

    def is_available(self) -> bool:
        if importlib.util.find_spec("playwright") is None:
            self.unavailable_reason = "未安装 playwright"
            return False
        return True

    def fetch(self) -> list[dict]:
        from playwright.sync_api import sync_playwright  # 延迟导入：playwright 为可选依赖

        pw_cfg = self.cfg["playwright"]
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, **proxy_kwargs(self.cfg))
            try:
                context = browser.new_context(
                    user_agent="MERA-Fetcher/1.0 (+https://github.com/mera-project)",
                    locale="en-US",
                    viewport={"width": 1366, "height": 900},
                )
                page = context.new_page()
                page.goto(pw_cfg["url"], wait_until="networkidle")
                return collect_rows(page, pw_cfg)
            finally:
                browser.close()
