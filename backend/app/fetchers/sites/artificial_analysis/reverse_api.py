"""Artificial Analysis 接口逆向方案：HMAC-MD5 签名的前端结构化接口。

build_request/parse_response 为纯函数；密钥经 env: 引用注入，缺失时
is_available()=False，由编排层记录 skipped（不发请求、不视为失败）。
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

import requests

from app.core.exceptions import SecretError
from app.fetchers.base import BaseFetcher, RequestSpec, request_json
from app.fetchers.signing import read_secret, sign_hmac_md5


def build_request(cfg: dict, *, secret: str, timestamp: int, page: int = 1) -> RequestSpec:
    """构造签名请求（纯函数）：sign = HMAC_MD5(sorted(kv) + timestamp)，密钥不出现在参数中。"""
    api_cfg = cfg["reverse_api"]
    sign_cfg = api_cfg["sign"]
    params: dict[str, Any] = {"page": page, "size": api_cfg.get("page_size", 50)}
    params[sign_cfg["sign_param"]] = sign_hmac_md5(params, secret, timestamp)
    params[sign_cfg["timestamp_param"]] = timestamp
    referer = (cfg.get("playwright") or {}).get("url", "")
    return RequestSpec(
        method="GET",
        url=api_cfg["endpoint"],
        params=params,
        headers={"Referer": referer, "Accept": "application/json"},
    )


def parse_response(payload: Any) -> tuple[list[dict], bool, bool]:
    """解析响应（纯函数），返回 (records, has_more, truncated)。"""
    if not isinstance(payload, dict):
        return [], False, False
    data = payload.get("data")
    if not isinstance(data, dict):
        return [], False, False
    records = data.get("list")
    if not isinstance(records, list):
        records = []
    has_more = bool(data.get("has_more", False))
    truncated = bool(data.get("truncated", False))
    return [item for item in records if isinstance(item, dict)], has_more, truncated


class Fetcher(BaseFetcher):
    strategy = "reverse_api"

    def __init__(
        self,
        site_config: dict,
        *,
        session: requests.Session | None = None,
        sleeper: Callable[[float], None] | None = None,
        now: Callable[[], float] | None = None,
    ) -> None:
        super().__init__(site_config)
        self.session = session or requests.Session()
        self._sleep = sleeper or time.sleep
        self._now = now or time.time
        self._min_interval = 60.0 / float(site_config.get("rate_limit_per_min", 60))
        self._secret_ref = self.cfg["reverse_api"]["sign"]["secret_ref"]
        try:
            self._secret: str | None = read_secret(self._secret_ref)
        except SecretError:
            self._secret = None
            self.unavailable_reason = f"缺少授权密钥（{self._secret_ref}）"

    def is_available(self) -> bool:
        return self._secret is not None

    def fetch(self) -> list[dict]:
        if self._secret is None:
            raise SecretError(f"缺少授权密钥（{self._secret_ref}）")
        records: list[dict] = []
        page = 1
        max_pages = int(self.cfg["reverse_api"].get("max_pages", 5))
        while True:
            spec = build_request(
                self.cfg, secret=self._secret, timestamp=int(self._now()), page=page
            )
            payload = request_json(self.session, spec)
            batch, has_more, server_truncated = parse_response(payload)
            records.extend(batch)
            self._sleep(self._min_interval)
            if server_truncated:
                self.truncated = True  # 服务端截断：保留已得数据，判 partial_succeeded
                break
            if not has_more:
                break
            page += 1
            if page > max_pages:
                self.truncated = True  # 达到翻页上限：保留已得数据，判 partial_succeeded
                break
        return records
