"""LMArena 榜单 Playwright 方案：Camoufox 指纹浏览器解析公开榜单页。

LMArena 为 Cloudflare 强风控公开页，属指南 M06.2 指定的指纹浏览器场景；
本站点不提供无指纹降级（普通 Chromium 基本无法通过风控）。
parse_dom/collect_rows 可注入假 page 单测；fetch() 只做浏览器编排。
"""

from __future__ import annotations

import importlib.util
from typing import Any

from app.core.exceptions import ConfigError, FetchFailed
from app.fetchers.base import BaseFetcher
from app.fetchers.proxy import proxy_kwargs


def parse_leaderboard(rows: list[Any]) -> list[dict]:
    """榜单行解析纯函数（row 为含 span[title] 的容器元素，可注入假元素单测）。

    行结构（arena.ai 新站，非 table）：排名数字 + 厂商 svg<title> + 模型名 span[title] + 百分数。
    模型名优先取 title 属性（inner_text 可能被 truncate 截断）。
    """
    records = []
    seen: set[str] = set()  # 页面含隐藏副本 DOM，按模型名去重（保留首条带排名的）
    for row in rows:
        title_el = row.query_selector("span[title]")
        model = ""
        if title_el is not None:
            model = title_el.get_attribute("title") or title_el.inner_text() or ""
        model = model.strip()
        if not model or model in seen:
            continue
        seen.add(model)
        vendor_el = row.query_selector("svg title")
        # svg <title> 不是 HTMLElement，inner_text 会抛错，须用 text_content
        vendor = (vendor_el.text_content() or "") if vendor_el is not None else ""
        tokens = (row.inner_text() or "").split()
        rank = next((t for t in tokens if t.strip().isdigit()), "")
        score = next((t for t in reversed(tokens) if t.strip().endswith("%")), "")
        records.append(
            {
                "rank": rank,
                "model": model.strip(),
                "vendor": vendor.strip(),
                "score": score.rstrip("%"),
            }
        )
    return records


def collect_rows(page: Any, pw_cfg: dict) -> list[dict]:
    """单页采集：等榜单行出现后，仅解析首个 section（主榜单）内的行（无翻页）。

    页面含多个 figure 区块（主榜单 + 次要榜单/隐藏副本），行结构相同会误匹配，
    须以 section_selector 首个命中元素为解析范围。
    """
    section_sel = str(pw_cfg.get("section_selector") or "").strip()
    row_sel = pw_cfg["rows_selector"]
    ready_sel = f"{section_sel} {row_sel}".strip()
    page.wait_for_selector(ready_sel, timeout=int(pw_cfg.get("ready_timeout_ms", 30000)))
    scope: Any = page
    if section_sel:
        sections = page.query_selector_all(section_sel)
        if sections:
            scope = sections[0]
    return parse_leaderboard(scope.query_selector_all(row_sel))


class Fetcher(BaseFetcher):
    strategy = "playwright"

    def is_available(self) -> bool:
        fp = (self.cfg.get("playwright") or {}).get("fingerprint_browser") or {}
        if not fp.get("enabled"):
            self.unavailable_reason = "本站点必须启用指纹浏览器（fingerprint_browser.enabled）"
            return False
        if fp.get("provider") != "camoufox":
            self.unavailable_reason = f"未知指纹浏览器提供方: {fp.get('provider')!r}"
            return False
        if importlib.util.find_spec("camoufox") is None:
            self.unavailable_reason = "未安装 camoufox（指纹浏览器）"
            return False
        return True

    def fetch(self) -> list[dict]:
        from camoufox.sync_api import Camoufox  # 延迟导入：camoufox 为可选依赖

        pw_cfg = self.cfg["playwright"]
        fp = pw_cfg.get("fingerprint_browser") or {}
        goto_timeout = int(pw_cfg.get("goto_timeout_ms", 60000))
        try:
            with Camoufox(
                headless=True,
                geoip=bool(fp.get("geoip", False)),
                **proxy_kwargs(self.cfg),
            ) as browser:
                page = browser.new_page()
                # LMArena 有长连接，networkidle 永不满足；DOM ready 后等榜单行出现即可
                page.goto(pw_cfg["url"], wait_until="domcontentloaded", timeout=goto_timeout)
                return collect_rows(page, pw_cfg)
        except Exception as exc:
            if isinstance(exc, (ConfigError, FetchFailed)):
                raise
            raise FetchFailed(f"LMArena 页面访问失败: {type(exc).__name__}") from exc
