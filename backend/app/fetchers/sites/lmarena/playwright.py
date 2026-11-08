"""LMArena 榜单 Playwright 方案：Camoufox 指纹浏览器解析公开榜单页。

LMArena 为 Cloudflare 强风控公开页，属指南 M06.2 指定的指纹浏览器场景；
本站点不提供无指纹降级（普通 Chromium 基本无法通过风控）。
parse_leaderboard/collect_rows 可注入假元素单测；fetch() 只做浏览器编排。

页面结构（arena.ai，Next.js SSR）：所有领域榜单均为 <table class="table-fixed">，
模型名在 td 内的 span[title]，厂商在 svg <title>，分数量级与所在列因领域而异，
由 config.playwright.pages 的 domain / score_column / score_type 控制。
单站点覆盖五个领域：fetch() 依次访问每个领域页面，记录带各自 domain。
"""

from __future__ import annotations

import importlib.util
import re
from typing import Any

from app.core.exceptions import ConfigError, FetchFailed
from app.fetchers.base import BaseFetcher
from app.fetchers.proxy import proxy_kwargs

# 取文本中第一个数字（支持百分号、正负误差、千分位），如 "1541±15" -> "1541"
_NUMBER_RE = re.compile(r"-?\d[\d,]*\.?\d*")


def _extract_number(text: str) -> str:
    match = _NUMBER_RE.search(text or "")
    return match.group(0).replace(",", "") if match else ""


def parse_leaderboard(
    rows: list[Any], score_column: int, score_type: str = "absolute", domain: str = ""
) -> list[dict]:
    """榜单行解析纯函数（row 为 <tr> 元素，可注入假元素单测）。

    - 模型名取 span[title] 的 title 属性（inner_text 可能被截断）
    - 厂商取 svg <title> 的 text_content
    - 分数从第 score_column 个 td 提取首个数字
    - domain 标识该页所属领域，供标准化时写成维度分
    """
    records = []
    seen: set[str] = set()
    for row in rows:
        title_el = row.query_selector("td span[title]")
        model = ""
        if title_el is not None:
            model = title_el.get_attribute("title") or title_el.inner_text() or ""
        model = model.strip()
        if not model or model in seen:
            continue
        seen.add(model)
        vendor_el = row.query_selector("svg title")
        vendor = (vendor_el.text_content() or "") if vendor_el is not None else ""
        cells = row.query_selector_all("td")
        score_text = ""
        if 1 <= score_column <= len(cells):
            score_text = cells[score_column - 1].inner_text() or ""
        score = _extract_number(score_text)
        records.append(
            {
                "model": model,
                "vendor": vendor.strip(),
                "score": score,
                "domain": domain,
                "score_type": score_type,
                "score_raw": score_text.strip(),
            }
        )
    return records


def collect_rows(page: Any, pw_cfg: dict, page_cfg: dict) -> list[dict]:
    """单页采集：等榜单行出现后解析（无翻页）。"""
    row_sel = pw_cfg["rows_selector"]
    page.wait_for_selector(row_sel, timeout=int(pw_cfg.get("ready_timeout_ms", 30000)))
    rows = page.query_selector_all(row_sel)
    return parse_leaderboard(
        rows,
        int(page_cfg.get("score_column", 4)),
        str(page_cfg.get("score_type", "absolute")),
        str(page_cfg.get("domain", "")),
    )


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
        pages_cfg = pw_cfg.get("pages") or []
        if not pages_cfg:
            raise ConfigError("LMArena 未配置采集页面（playwright.pages）")
        fp = pw_cfg.get("fingerprint_browser") or {}
        goto_timeout = int(pw_cfg.get("goto_timeout_ms", 60000))
        try:
            with Camoufox(
                headless=True,
                geoip=bool(fp.get("geoip", False)),
                **proxy_kwargs(self.cfg),
            ) as browser:
                page = browser.new_page()
                records: list[dict] = []
                failures: list[str] = []
                for page_cfg in pages_cfg:
                    domain = str(page_cfg.get("domain", ""))
                    try:
                        # LMArena 有长连接，networkidle 永不满足；DOM ready 后等榜单行出现即可
                        page.goto(
                            page_cfg["url"],
                            wait_until="domcontentloaded",
                            timeout=goto_timeout,
                        )
                        records.extend(collect_rows(page, pw_cfg, page_cfg))
                    except Exception as exc:  # noqa: BLE001 - 单领域失败不丢弃其它领域数据
                        failures.append(f"{domain or page_cfg['url']}: {type(exc).__name__}")
                if not records and failures:
                    raise FetchFailed("LMArena 页面访问失败: " + "; ".join(failures))
                return records
        except Exception as exc:
            if isinstance(exc, (ConfigError, FetchFailed)):
                raise
            raise FetchFailed(f"LMArena 页面访问失败: {type(exc).__name__}") from exc
