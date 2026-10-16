"""OpenRouter 官方 Models API 方案（公开 JSON，无需登录）。

build_request/parse_response 为纯函数，可脱离网络单测；fetch() 只做编排。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import requests

from app.core.exceptions import SecretError
from app.fetchers.base import BaseFetcher, RequestSpec, request_json
from app.fetchers.signing import read_secret

_USER_AGENT = "MERA-Fetcher/1.0 (+https://github.com/mera-project; model-eval)"


def build_request(cfg: dict, *, api_key: str | None = None) -> RequestSpec:
    """构造 Models API 请求（纯函数）。api_key 可选，只进 Authorization 头。"""
    api_cfg = cfg["api"]
    headers = {"User-Agent": _USER_AGENT, "Accept": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    return RequestSpec(method="GET", url=api_cfg["url"], headers=headers)


def parse_response(payload: Any, *, records_path: str = "data") -> list[dict]:
    """从响应 JSON 提取记录列表（纯函数）。"""
    if not isinstance(payload, dict):
        return []
    records = payload.get(records_path)
    if not isinstance(records, list):
        return []
    return [item for item in records if isinstance(item, dict)]


class Fetcher(BaseFetcher):
    strategy = "api"

    def __init__(
        self,
        site_config: dict,
        *,
        session: requests.Session | None = None,
        sleeper: Callable[[float], None] | None = None,
    ) -> None:
        super().__init__(site_config)
        self.session = session or requests.Session()
        self._sleep = sleeper or time.sleep
        self._min_interval = 60.0 / float(site_config.get("rate_limit_per_min", 60))
        # 可选密钥：缺失不降级可用性（公开接口），仅不带授权头
        self._api_key: str | None = None
        key_ref = self.cfg["api"].get("api_key_ref")
        if key_ref:
            try:
                self._api_key = read_secret(key_ref)
            except SecretError:
                self._api_key = None

    def fetch(self) -> list[dict]:
        spec = build_request(self.cfg, api_key=self._api_key)
        payload = request_json(self.session, spec)
        self._sleep(self._min_interval)
        return parse_response(
            payload, records_path=self.cfg["api"].get("records_path", "data")
        )
