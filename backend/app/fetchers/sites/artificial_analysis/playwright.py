"""Artificial Analysis Playwright 兜底方案：渲染榜单页解析表格。

解析逻辑（parse_dom/翻页循环）与浏览器启动解耦，可注入假 page 单测；
指纹浏览器按 config 的 fingerprint_browser.provider 接入：
adspower/bitbrowser 经 Local API + CDP，camoufox 进程内；仅用于公开榜单页。
"""

from __future__ import annotations

import importlib.util
from typing import Any

import requests

from app.core.exceptions import FetchFailed
from app.fetchers.base import BaseFetcher, collect_paginated_rows, parse_dom_rows
from app.fetchers.profiles import new_context_kwargs
from app.fetchers.proxy import proxy_kwargs

_LOCAL_API_PROVIDERS = {"adspower", "bitbrowser"}


def parse_dom(rows: list[Any], fields: dict[str, str]) -> list[dict]:
    """DOM 解析纯函数（字段选择器来自 config.yaml）。"""
    return parse_dom_rows(rows, fields)


def collect_rows(page: Any, pw_cfg: dict) -> list[dict]:
    """翻页采集循环（page 对象协议注入）。"""
    return collect_paginated_rows(page, pw_cfg)


def start_fp_browser(fp: dict, *, session: requests.Session | None = None) -> str:
    """经商用指纹浏览器 Local API 启动 profile，返回 CDP ws 端点（响应体不回显进异常）。"""
    http = session or requests.Session()
    try:
        resp = http.get(
            f"{fp['local_api']}/api/v1/browser/start",
            params={"user_id": fp["profile_id"], "open_tabs": 1},
            timeout=float(fp.get("startup_wait_sec", 30)),
        )
    except requests.RequestException as exc:
        raise FetchFailed(f"指纹浏览器 Local API 不可达: {exc.__class__.__name__}") from exc
    try:
        payload = resp.json()
    except ValueError as exc:
        raise FetchFailed("指纹浏览器 Local API 返回非 JSON") from exc
    if not isinstance(payload, dict) or payload.get("code") != 0:
        raise FetchFailed("指纹浏览器 profile 启动失败")
    try:
        return str(payload["data"]["ws"]["selenium"])
    except (KeyError, TypeError) as exc:
        raise FetchFailed("指纹浏览器未返回 CDP 端点") from exc


class Fetcher(BaseFetcher):
    strategy = "playwright"

    def is_available(self) -> bool:
        if importlib.util.find_spec("playwright") is None:
            self.unavailable_reason = "未安装 playwright"
            return False
        if self.cfg.get("auth_required") == "browser_session" and not self.require_browser_session():
            return False
        fp = (self.cfg.get("playwright") or {}).get("fingerprint_browser") or {}
        if fp.get("enabled"):
            provider = fp.get("provider")
            if provider in _LOCAL_API_PROVIDERS:
                if not fp.get("local_api") or not fp.get("profile_id"):
                    self.unavailable_reason = f"指纹浏览器 {provider} 未配置 local_api/profile_id"
                    return False
            elif provider == "camoufox":
                if importlib.util.find_spec("camoufox") is None:
                    self.unavailable_reason = "未安装 camoufox"
                    return False
            else:
                self.unavailable_reason = f"未知指纹浏览器 provider: {provider}"
                return False
        return True

    def fetch(self) -> list[dict]:
        from playwright.sync_api import sync_playwright  # 延迟导入：playwright 为可选依赖

        pw_cfg = self.cfg["playwright"]
        fp = pw_cfg.get("fingerprint_browser") or {}
        with sync_playwright() as p:
            if fp.get("enabled") and fp.get("provider") in _LOCAL_API_PROVIDERS:
                ws_endpoint = start_fp_browser(fp)
                browser = p.chromium.connect_over_cdp(ws_endpoint)
                context = browser.contexts[0]
                page = context.new_page()
            elif fp.get("enabled") and fp.get("provider") == "camoufox":
                from camoufox.sync_api import Camoufox  # 延迟导入：camoufox 为可选依赖

                # Camoufox 的 __enter__ 返回 Browser 或 BrowserContext，两者均可 new_page()；
                # 不复用 page 变量名，避免与上方分支推断出的 Page 类型冲突
                with Camoufox(
                    headless=bool(fp.get("headless", True)), **proxy_kwargs(self.cfg)
                ) as fox_browser:
                    page = fox_browser.new_page()
                    page.goto(pw_cfg["url"], wait_until="networkidle")
                    return collect_rows(page, pw_cfg)
            else:
                browser = p.chromium.launch(headless=True, **proxy_kwargs(self.cfg))
                context = browser.new_context(
                    **new_context_kwargs(self.cfg, site_key=self.site_key)
                )
                page = context.new_page()
            page.goto(pw_cfg["url"], wait_until="networkidle")
            rows = collect_rows(page, pw_cfg)
            browser.close()
            return rows
