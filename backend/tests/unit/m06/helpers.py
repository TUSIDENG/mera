"""M06 单元测试辅助：真实站点配置加载 + 假 DOM page（无网络/无浏览器）。"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

import yaml

from app.fetchers.config_loader import SITES_DIR, load_site


def site_config(key: str) -> dict:
    return yaml.safe_load((SITES_DIR / key / "config.yaml").read_text(encoding="utf-8"))


def make_fetcher(key: str, strategy: str, **patches):
    """经 config_loader 实例化真实站点方案，并注入 sleeper/now 等测试替身。"""
    site = load_site(SITES_DIR, key)
    fetcher = dict(site.fetchers)[strategy]
    for name, value in patches.items():
        setattr(fetcher, name, value)
    return fetcher


class FakeElement:
    """模拟 DOM 元素：inner_text + query_selector + get_attribute 协议。"""

    def __init__(
        self,
        text: str | None = None,
        children: dict[str, FakeElement] | None = None,
        attrs: dict[str, str] | None = None,
        children_all: dict[str, list[FakeElement]] | None = None,
    ) -> None:
        self._text = text
        self._children = children or {}
        self._attrs = attrs or {}
        self._children_all = children_all or {}

    def inner_text(self) -> str | None:
        return self._text

    def text_content(self) -> str | None:
        return self._text

    def query_selector(self, selector: str) -> FakeElement | None:
        return self._children.get(selector)

    def query_selector_all(self, selector: str) -> list[FakeElement]:
        return list(self._children_all.get(selector, []))

    def get_attribute(self, name: str) -> str | None:
        return self._attrs.get(name)


class FakeLocator:
    def __init__(self, on_click: Callable[[], None]) -> None:
        self._on_click = on_click

    def click(self) -> None:
        self._on_click()


class FakePage:
    """模拟多页表格：pages 为每页行元素列表；末页无 next 元素。"""

    def __init__(self, pages: list[list[FakeElement]], next_selector: str = "button.next-page"):
        self._pages = pages
        self._next_selector = next_selector
        self._index = 0
        self.clicks = 0
        self.waits: list[int] = []

    def query_selector_all(self, selector: str) -> list[FakeElement]:
        return self._pages[self._index]

    def query_selector(self, selector: str) -> Any:
        if selector == self._next_selector and self._index < len(self._pages) - 1:
            return FakeElement("next")
        return None

    def locator(self, selector: str) -> FakeLocator:
        return FakeLocator(self._advance)

    def _advance(self) -> None:
        self.clicks += 1
        self._index += 1

    def wait_for_timeout(self, ms: int) -> None:
        self.waits.append(ms)


def table_row(cells: dict[str, str]) -> FakeElement:
    """按 选择器->文本 构造一行，如 {"td:nth-child(1)": "GPT-4o"}。"""
    return FakeElement(children={sel: FakeElement(text) for sel, text in cells.items()})
