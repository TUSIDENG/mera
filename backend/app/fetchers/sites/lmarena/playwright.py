"""LMArena 榜单 Playwright 方案：Camoufox 指纹浏览器解析公开榜单页。

LMArena 为 Cloudflare 强风控公开页，属指南 M06.2 指定的指纹浏览器场景；
本站点不提供无指纹降级（普通 Chromium 基本无法通过风控）。

页面结构（arena.ai，Next.js SSR）：所有领域榜单均为 <table class="table-fixed">，
榜单行一次性离屏渲染（无需分页/View all），故 query_selector_all 可拿到全量模型。
各领域/子分类的列数不同（agent 13 列、image 5 列等），因此按表头名定位
Rank/Model/Score/Votes/Cost/Price/Context，并把整行列文本原样保留在 columns 里，
方便后续分析（部分模型有价格、部分为 N/A）。

一个站点覆盖五个领域共 14 个子分类：fetch() 按任务领域过滤页面后逐页采集，
记录带 domain（领域）与 sub（子分类）。
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
# 表头名 -> 关键字（小写，包含匹配；rank 用精确匹配避免命中 rank spread）
_FIELD_HEADERS: dict[str, tuple[str, ...]] = {
    "rank": ("rank",),
    "rank_spread": ("rank spread",),
    "model": ("model",),
    "score": ("score", "improvement", "rating"),
    "votes": ("votes",),
    "cost": ("cost",),
    "price": ("price",),
    "context": ("context",),
}


def _extract_number(text: str) -> str:
    match = _NUMBER_RE.search(text or "")
    return match.group(0).replace(",", "") if match else ""


def _to_int(text: str) -> int | None:
    digits = re.sub(r"[^\d]", "", text or "")
    return int(digits) if digits else None


def _parse_price(text: str) -> tuple[float | None, float | None]:
    """价格列形如 "$2 / $10"（每百万 token 输入/输出），N/A 返回 (None, None)。"""
    values = [float(v.replace(",", "")) for v in re.findall(r"\$\s*(\d[\d,]*(?:\.\d+)?)", text or "")]
    if not values:
        return None, None
    return values[0], values[1] if len(values) > 1 else None


def _parse_context(text: str) -> int | None:
    """上下文列形如 "1M" / "262.1K" / "N/A"，统一换算成 token 数。"""
    match = re.search(r"(\d+(?:\.\d+)?)\s*([KMB])?", (text or "").strip(), re.IGNORECASE)
    if not match:
        return None
    scale = {"": 1, "K": 1_000, "M": 1_000_000, "B": 1_000_000_000}
    return int(float(match.group(1)) * scale[(match.group(2) or "").upper()])


def _header_index(headers: list[str]) -> dict[str, int | None]:
    """按表头名定位各标准字段所在列（1-based 列号转为 0-based 下标）。"""
    normalized = [h.strip().lower() for h in headers]
    index: dict[str, int | None] = {}
    for field_name, keywords in _FIELD_HEADERS.items():
        found: int | None = None
        for i, label in enumerate(normalized):
            if field_name == "rank":
                matched = label == "rank"
            else:
                matched = any(keyword in label for keyword in keywords)
            if matched:
                found = i
                break
        index[field_name] = found
    return index


def _cell_text(cells: list[Any], index: int | None) -> str:
    if index is None or index >= len(cells):
        return ""
    return (cells[index].inner_text() or "").strip()


def _model_info(cell: Any) -> tuple[str, str, str]:
    """模型单元格：首行模型名 + 次行「厂商 · 许可证」，如 OpenAI · Proprietary。"""
    if cell is None:
        return "", "", ""
    span = cell.query_selector("span[title]")
    name = ""
    if span is not None:
        name = (span.get_attribute("title") or span.inner_text() or "").strip()
    lines = [line.strip() for line in (cell.inner_text() or "").splitlines() if line.strip()]
    if not name:
        name = lines[0] if lines else ""
    vendor = ""
    license_text = ""
    for line in lines:
        if line == name:
            continue
        if "·" in line:
            vendor, _, license_text = (part.strip() for part in line.partition("·"))
            break
    if not vendor and len(lines) > 1:
        vendor = lines[-1]  # 无分隔符时次行即厂商
    return name, vendor, license_text


def parse_leaderboard(
    rows: list[Any], headers: list[str], domain: str = "", sub: str = ""
) -> list[dict]:
    """榜单行解析纯函数（row 为 <tr> 元素，可注入假元素单测）。

    表头驱动列映射，兼容各领域不同列数；整行文本另存 columns 以便留存全部字段。
    """
    index = _header_index(headers)
    records: list[dict] = []
    seen: set[str] = set()
    for row in rows:
        cells = row.query_selector_all("td")
        if not cells:
            continue
        model_cell = cells[index["model"]] if index["model"] is not None else None
        if model_cell is None:
            model_cell = next(
                (cell for cell in cells if cell.query_selector("span[title]") is not None), None
            )
        model, vendor, license_text = _model_info(model_cell)
        if not model or model in seen:
            continue
        seen.add(model)
        score_text = _cell_text(cells, index["score"])
        price_text = _cell_text(cells, index["price"])
        price_input, price_output = _parse_price(price_text)
        columns: dict[str, str] = {}
        for i, header in enumerate(headers):
            if header and i < len(cells):
                columns[header] = _cell_text(cells, i)
        records.append(
            {
                "model": model,
                "vendor": vendor,
                "license": license_text,
                "score": _extract_number(score_text),
                "score_raw": score_text,
                "domain": domain,
                "sub": sub,
                "rank": _to_int(_cell_text(cells, index["rank"])),
                "rank_spread": _cell_text(cells, index["rank_spread"]),
                "votes": _to_int(_cell_text(cells, index["votes"])),
                "cost_per_task_p50": _cell_text(cells, index["cost"]) or None,
                "price_input": price_input,
                "price_output": price_output,
                "context_window": _parse_context(_cell_text(cells, index["context"])),
                "columns": columns,
            }
        )
    return records


def collect_rows(page: Any, pw_cfg: dict, page_cfg: dict) -> list[dict]:
    """单页采集：等榜单行出现并稳定后，一次取全量行（榜单为离屏全量渲染）。"""
    row_sel = pw_cfg["rows_selector"]
    page.wait_for_selector(row_sel, timeout=int(pw_cfg.get("ready_timeout_ms", 45000)))
    settle_ms = int(pw_cfg.get("settle_ms", 0))
    if settle_ms:
        page.wait_for_timeout(settle_ms)
    headers: list[str] = []
    header_sel = pw_cfg.get("header_selector")
    if header_sel:
        headers = [(el.inner_text() or "").strip() for el in page.query_selector_all(header_sel)]
    rows = page.query_selector_all(row_sel)
    return parse_leaderboard(
        rows, headers, str(page_cfg.get("domain", "")), str(page_cfg.get("sub", ""))
    )


def select_pages(pages: list[dict], domain: str | None) -> list[dict]:
    """按任务领域过滤页面；domain 为空表示采集全部子分类。"""
    if not domain:
        return list(pages)
    return [page for page in pages if page.get("domain") == domain]


# Cloudflare 安全验证页特征（中/英/日）；命中说明出口 IP 被挑战，需更换代理
_BLOCK_TITLES = ("just a moment", "attention required", "しばらくお待ちください", "security verification")


def _blocked_reason(page: Any) -> str | None:
    try:
        title = (page.title() or "").lower()
    except Exception:  # noqa: BLE001 - 取标题失败不影响后续解析
        return None
    if any(marker in title for marker in _BLOCK_TITLES):
        return "Cloudflare 安全验证未通过（出口 IP 被挑战），请更换代理/出口 IP 后重试"
    return None


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
        pages_cfg = select_pages(pw_cfg.get("pages") or [], self.domain)
        if not pages_cfg:
            scope = f"领域 {self.domain}" if self.domain else "站点"
            raise ConfigError(f"LMArena {scope} 未配置采集页面（playwright.pages）")
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
                    label = str(page_cfg.get("sub") or page_cfg.get("domain") or page_cfg["url"])
                    try:
                        # LMArena 有长连接，networkidle 永不满足；DOM ready 后等榜单行出现即可
                        page.goto(
                            page_cfg["url"],
                            wait_until="domcontentloaded",
                            timeout=goto_timeout,
                        )
                        blocked = _blocked_reason(page)
                        if blocked:
                            raise FetchFailed(blocked)
                        records.extend(collect_rows(page, pw_cfg, page_cfg))
                    except Exception as exc:  # noqa: BLE001 - 单页失败不丢弃其它子分类数据
                        failures.append(f"{label}: {str(exc)[:120] or type(exc).__name__}")
                if not records and failures:
                    raise FetchFailed("LMArena 页面访问失败: " + "; ".join(failures))
                return records
        except Exception as exc:
            if isinstance(exc, (ConfigError, FetchFailed)):
                raise
            raise FetchFailed(f"LMArena 页面访问失败: {type(exc).__name__}") from exc
