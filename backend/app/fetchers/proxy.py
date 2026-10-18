"""M06 采集代理配置：浏览器/指纹抓取走代理 IP，规避按 IP 的出口风控（如 Cloudflare 封机房段）。

解析顺序（前者优先）：
1. 站点 config.yaml `playwright.proxy`（支持 `env:VAR` 引用；引用未设置时回落下一级）；
2. 环境变量 `MERA_FETCH_PROXY`；
3. 默认 `http://127.0.0.1:6789`（本机代理客户端）。

显式禁用：值设为空字符串或 `none`。裸地址自动补 `http://` 前缀。
容器内访问宿主机代理：compose 注入 `MERA_FETCH_PROXY=http://host.docker.internal:6789`。
"""

from __future__ import annotations

import os
from typing import Any

from app.core.exceptions import SecretError
from app.fetchers.signing import read_secret

DEFAULT_PROXY = "http://127.0.0.1:6789"
PROXY_ENV = "MERA_FETCH_PROXY"


def resolve_proxy_server(cfg: dict[str, Any]) -> str | None:
    """解析代理服务器地址；返回 None 表示明确禁用代理。"""
    pw_cfg = cfg.get("playwright") or {}
    raw = pw_cfg.get("proxy")
    if isinstance(raw, str):
        if raw.startswith("env:"):
            try:
                return _normalize(read_secret(raw))
            except SecretError:
                pass  # 引用未设置：回落环境变量/默认
        else:
            return _normalize(raw)
    return _normalize(os.environ.get(PROXY_ENV, DEFAULT_PROXY))


def proxy_kwargs(cfg: dict[str, Any]) -> dict[str, Any]:
    """生成 launch/Camoufox 关键字参数：{"proxy": {"server": ...}} 或 {}。"""
    server = resolve_proxy_server(cfg)
    return {"proxy": {"server": server}} if server else {}


def _normalize(value: str) -> str | None:
    text = value.strip()
    if not text or text.lower() == "none":
        return None
    if "://" not in text:
        text = f"http://{text}"
    return text
