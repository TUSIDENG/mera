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
import time
import urllib.request
from contextlib import ExitStack
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


_VENDOR_MAX_LEN = 40  # model_snapshots.provider 为 varchar(50)，留余量


def _clean_vendor(vendor: str, model: str) -> str:
    """清洗厂商名。

    模型列有时把模型名与厂商挤在同一个文本节点里（无换行/分隔符），会解析出
    "gemini 3.1 flash image (nano-banana-2, web search)google" 这类脏值，
    直接写库会撑爆 provider varchar(50)。去掉重复的模型名后仍异常的一律丢弃，
    交给 normalize 的 provider_fallback 兜底。
    """
    value = (vendor or "").strip()
    name = (model or "").strip()
    if value and name and name.lower() in value.lower():
        start = value.lower().index(name.lower())
        value = (value[:start] + value[start + len(name):]).strip()
    if not value or len(value) > _VENDOR_MAX_LEN:
        return ""
    return value


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
    return name, _clean_vendor(vendor, name), license_text


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


# Cloudflare 安全验证页特征：标题随区域语言变化，DOM 标记更可靠
_BLOCK_TITLES = (
    "just a moment",
    "attention required",
    "checking your browser",
    "verifying you are human",
    "security verification",
    "sicherheitsüberprüfung",
    "しばらくお待ちください",
    "稍等",
    "un momento",  # 西班牙语挑战页标题（Un momento…）
    "un instant",  # 法语挑战页标题（Un instant…）
)
_BLOCK_DOM_SELECTOR = (
    "#challenge-form, #cf-challenge-running, #cf-please-wait, #challenge-body-text, "
    "iframe[src*='challenges.cloudflare.com'], .cf-turnstile, "
    "script[src*='/cdn-cgi/challenge-platform/']"
)
# 挑战页的 JS 运行时对象：DOM 改版时仍然存在，作为第三条判据
_BLOCK_JS_PROBE = (
    "() => !!(window._cf_chl_opt || window.turnstile || "
    "window.__CF$cv$params)"
)
_BLOCK_MSG = "Cloudflare 安全验证未通过（出口 IP 被挑战），请更换代理/出口 IP 后重试"


def _rotate_proxy_endpoint(pw_cfg: dict) -> None:
    """请求本地中继换一个出口 IP（中继控制接口，不走代理自身）。

    被 Cloudflare 挑战时旧 IP 在 endpoint 有效期内不会变，只能主动轮换；
    控制接口不可达时静默跳过，让重试沿用原 IP。
    """
    url = str(pw_cfg.get("relay_rotate_url") or "")
    if not url:
        return
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        opener.open(url, timeout=120).read()
    except Exception:  # noqa: BLE001 - 轮换失败不影响主流程
        pass


def _page_diag(page: Any) -> str:
    """失败时抓标题与正文片段，便于区分挑战页/错误页/空白页。"""
    try:
        title = (page.title() or "").strip()
    except Exception:  # noqa: BLE001 - 诊断信息取不到就留空
        title = ""
    try:
        body = (page.inner_text("body") or "").strip().replace("\n", " ")
    except Exception:  # noqa: BLE001
        body = ""
    return f"title={title!r} body={body[:80]!r}"


def _wait_rows(page: Any, pw_cfg: dict) -> str | None:
    """轮询等待榜单行出现，同时识别 CF 挑战页。

    返回 None 表示榜单已渲染；否则返回失败原因（挑战页提示或未渲染诊断）。
    CF 的 JS 校验要 5–20 秒才放行，goto 后立刻判定会把本来能过的 IP 换掉。
    """
    rows_sel = str(pw_cfg.get("rows_selector") or "")
    resolve_ms = int(pw_cfg.get("block_resolve_ms", 20000))
    waited = 0
    blocked: str | None = None
    while waited <= resolve_ms:
        try:
            if rows_sel and page.query_selector(rows_sel) is not None:
                return None
        except Exception:  # noqa: BLE001 - 页面导航中查询失败，继续轮询
            pass
        blocked = _blocked_reason(page)
        try:
            page.wait_for_timeout(1000)
        except Exception:  # noqa: BLE001 - 页面已关闭，交给上层重试
            break
        waited += 1000
    return blocked or f"榜单未渲染（{_page_diag(page)}）"


def _blocked_reason(page: Any) -> str | None:
    try:
        if page.query_selector(_BLOCK_DOM_SELECTOR) is not None:
            return _BLOCK_MSG
    except Exception:  # noqa: BLE001 - 探测失败不影响后续判断
        pass
    try:
        title = (page.title() or "").lower()
    except Exception:  # noqa: BLE001 - 取标题失败不影响后续判断
        return None
    if any(marker in title for marker in _BLOCK_TITLES):
        return _BLOCK_MSG
    try:
        if page.evaluate(_BLOCK_JS_PROBE):
            return _BLOCK_MSG
    except Exception:  # noqa: BLE001 - JS 探测失败（页面导航中）按未识别处理
        pass
    return None


def _start_browser(stack: ExitStack, cfg: dict, pw_cfg: dict, goto_timeout: int) -> Any:
    """启动指纹浏览器实例、完成根域预热，返回采集用的 page。

    每次换出口 IP 都要重新调用：Camoufox 启动时会经代理查询出口 IP，
    据此生成新指纹并绑定时区/语言/地理位置；不重启会出现「新 IP + 旧地区指纹」
    这种自相矛盾的特征，反而更容易被风控挑出来。
    """
    from camoufox.sync_api import Camoufox  # 延迟导入：camoufox 为可选依赖

    fp = pw_cfg.get("fingerprint_browser") or {}
    browser = stack.enter_context(
        Camoufox(headless=True, geoip=bool(fp.get("geoip", False)), **proxy_kwargs(cfg))
    )
    page = browser.new_page()
    # Cloudflare 对深链直接访问更严格：先访问根域拿到 __cf_bm cookie 再进排行榜。
    # 预热失败不致命，交由正式 goto 暴露真实错误
    warmup_url = str(pw_cfg.get("warmup_url") or "")
    if warmup_url:
        try:
            page.goto(warmup_url, wait_until="domcontentloaded", timeout=goto_timeout)
            page.wait_for_timeout(int(pw_cfg.get("warmup_wait_ms", 3000)))
        except Exception:  # noqa: BLE001 - 预热是可选的
            pass
    return page


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
        pw_cfg = self.cfg["playwright"]
        pages_cfg = select_pages(pw_cfg.get("pages") or [], self.domain)
        if not pages_cfg:
            scope = f"领域 {self.domain}" if self.domain else "站点"
            raise ConfigError(f"LMArena {scope} 未配置采集页面（playwright.pages）")
        goto_timeout = int(pw_cfg.get("goto_timeout_ms", 60000))
        attempts = max(1, int(pw_cfg.get("page_attempts", 2)))
        records: list[dict] = []
        failures: list[str] = []
        stack = ExitStack()
        try:
            page = _start_browser(stack, self.cfg, pw_cfg, goto_timeout)
            for page_cfg in pages_cfg:
                label = str(page_cfg.get("sub") or page_cfg.get("domain") or page_cfg["url"])
                last_exc: Exception | None = None
                for attempt in range(1, attempts + 1):
                    try:
                        # LMArena 有长连接，networkidle 永不满足；DOM ready 后等榜单行出现即可
                        page.goto(
                            page_cfg["url"],
                            wait_until="domcontentloaded",
                            timeout=goto_timeout,
                        )
                        # CF 挑战页要跑几秒 JS 才放行，过早判定会把本来能过的 IP 换掉：
                        # 轮询等待「榜单行出现」，超时才区分挑战页/空白页
                        reason = _wait_rows(page, pw_cfg)
                        if reason:
                            raise FetchFailed(reason)
                        records.extend(collect_rows(page, pw_cfg, page_cfg))
                        last_exc = None
                        break
                    except Exception as exc:  # noqa: BLE001 - 挑战/超时/空白页都换 IP 重试
                        last_exc = exc
                        # 末次仍失败则计入失败页，交给编排层记 warnings/error_message
                        if attempt >= attempts:
                            break
                        # 换出口 IP 必须连带换浏览器：新实例启动时按新 IP 重新推导
                        # 指纹与时区/语言/地理位置（中继在 endpoint 有效期内锁同一 IP）
                        stack.close()
                        stack = ExitStack()
                        _rotate_proxy_endpoint(pw_cfg)
                        time.sleep(2 * attempt)
                        page = _start_browser(stack, self.cfg, pw_cfg, goto_timeout)
                if last_exc is not None:
                    failures.append(f"{label}: {str(last_exc)[:120] or type(last_exc).__name__}")
            # 非致命问题（部分子分类失败）留给编排层写入任务日志/error_message
            self.warnings = list(failures)
            if not records and failures:
                raise FetchFailed("LMArena 页面访问失败: " + "; ".join(failures))
            return records
        except Exception as exc:
            if isinstance(exc, (ConfigError, FetchFailed)):
                raise
            raise FetchFailed(f"LMArena 页面访问失败: {type(exc).__name__}") from exc
        finally:
            stack.close()
