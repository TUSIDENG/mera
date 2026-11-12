"""M05 BaseFetcher 抽象与方案共用工具。

fetch() 本体只做"构造 -> 请求 -> 解析 -> 异常分类"编排；
请求构造（build_request）与解析（parse_response/parse_dom）必须是可脱离网络单测的纯函数。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Protocol

import requests

from app.core.exceptions import CaptchaRequired, FetchFailed


@dataclass(frozen=True)
class RequestSpec:
    """一次 HTTP 请求的完整描述（纯数据，便于断言且不含密钥明文）。"""

    method: str
    url: str
    params: dict[str, Any] = field(default_factory=dict)
    headers: dict[str, str] = field(default_factory=dict)
    json_body: Any = None


class Sleeper(Protocol):
    def __call__(self, seconds: float) -> None: ...


class BaseFetcher(ABC):
    """站点方案基类：strategy 标识方案名，一个站点目录内每种方案一个 Fetcher 类。"""

    strategy: str = ""

    def __init__(self, site_config: dict) -> None:
        self.cfg = site_config
        self.site_key = str(site_config.get("key", ""))
        # 翻页被限频/中断时置 True，编排层据此判 partial_succeeded
        self.truncated = False
        # 非致命问题（部分子页面失败等），编排层写入任务日志/error_message 供排查
        self.warnings: list[str] = []
        # is_available() 为 False 时的可读原因（不得包含密钥值）
        self.unavailable_reason: str | None = None
        # 任务指定的领域（None/空表示全量）；多领域站点据此过滤要采集的子页面
        self.domain: str | None = None

    def is_available(self) -> bool:
        """前置检查：依赖、密钥、会话/浏览器 profile 是否就绪。默认就绪。"""
        return True

    def require_browser_session(self) -> bool:
        """auth_required=browser_session 的方案在 is_available() 中调用：

        校验 browser_session 配置与登录态（存在且未过 TTL），
        不可用时写入 unavailable_reason（不含 cookie 值）并返回 False。
        """
        from app.core.exceptions import ConfigError
        from app.fetchers.profiles import browser_session_available, parse_browser_session

        try:
            spec = parse_browser_session(self.cfg, site_key=self.site_key)
        except ConfigError as exc:
            self.unavailable_reason = str(exc)
            return False
        if spec is None:
            self.unavailable_reason = "browser_session 未配置 storage_state"
            return False
        ok, reason = browser_session_available(spec)
        if not ok:
            self.unavailable_reason = reason
        return ok

    @abstractmethod
    def fetch(self) -> Any:
        """采集本站，返回标准化前的原始记录；失败抛 FetchFailed/CaptchaRequired。"""

    def normalize(self, raw: Any, *, data_type: str | None = None) -> tuple[list[Any], bool]:
        """默认回退到通用 normalize；站点可覆盖。返回 (records, truncated)。

        data_type 为任务级数据类型（缺省取站点配置 data_type），决定产出 DTO 类型。
        """
        from app.fetchers.normalize import normalize_records

        records, truncated = normalize_records(raw, self.cfg, data_type=data_type)
        return records, (truncated or self.truncated)


def is_strategy_available(fetcher: BaseFetcher) -> bool:
    """编排层前置检查：is_available 自身抛异常也视为不可用（跳过不失败）。"""
    try:
        return bool(fetcher.is_available())
    except Exception:  # noqa: BLE001 - 可用性检查不得中断编排
        return False


def request_json(session: requests.Session, spec: RequestSpec, *, timeout: float = 30) -> Any:
    """执行 HTTP 请求并统一异常分类（M06 各方案共用）：

    网络错误/HTTP 4xx/坏 JSON -> FetchFailed；响应体 code=CAPTCHA_REQUIRED -> CaptchaRequired。
    异常消息不携带响应体，避免回显签名/密钥等敏感内容。
    """
    try:
        resp = session.request(
            spec.method,
            spec.url,
            params=spec.params or None,
            headers=spec.headers or None,
            json=spec.json_body,
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise FetchFailed(f"请求失败: {exc.__class__.__name__}") from exc
    if resp.status_code >= 400:
        raise FetchFailed(f"HTTP {resp.status_code}")
    try:
        payload = resp.json()
    except ValueError as exc:
        raise FetchFailed("响应不是合法 JSON") from exc
    if isinstance(payload, dict) and payload.get("code") == "CAPTCHA_REQUIRED":
        raise CaptchaRequired("目标站点要求验证码")
    return payload


def parse_dom_rows(rows: list[Any], fields: dict[str, str]) -> list[dict[str, Any]]:
    """DOM 行解析纯函数：rows 为元素对象（query_selector/inner_text 协议），fields 为 字段名->选择器。"""
    results: list[dict[str, Any]] = []
    for row in rows:
        item: dict[str, Any] = {}
        for name, selector in fields.items():
            element = row.query_selector(selector)
            text = element.inner_text() if element is not None else None
            item[name] = text.strip() if isinstance(text, str) else None
        results.append(item)
    return results


def collect_paginated_rows(
    page: Any,
    pw_cfg: dict,
    *,
    click_delay_ms: int = 1500,
) -> list[dict[str, Any]]:
    """翻页采集循环（page 对象协议注入，可用假 page 单测）：

    反复 query_selector_all(rows_selector) 并解析，直到没有 next_selector 或下一页元素不存在。
    """
    rows_selector = pw_cfg["rows_selector"]
    fields = pw_cfg["fields"]
    next_selector = pw_cfg.get("next_selector")

    results: list[dict[str, Any]] = []
    while True:
        results.extend(parse_dom_rows(page.query_selector_all(rows_selector), fields))
        if not next_selector or page.query_selector(next_selector) is None:
            break
        page.locator(next_selector).click()
        page.wait_for_timeout(click_delay_ms)
    return results
