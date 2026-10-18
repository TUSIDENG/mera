"""M06.2 浏览器登录态与指纹浏览器 profile 管理。

三类资产分层（实现指南 M06.2 第 6 节）：

1. 密钥（api_key/oauth token）：`env:` 引用 + 环境变量注入（signing.read_secret）。
2. 浏览器登录态（storage_state.json）与 Camoufox profile 目录：命名卷
   `profiles://` 根下按站点目录存放，worker 容器只读挂载；
   由管理员一次性运行 scripts/site_login.py 写入，不做自动续期/密码登录。
3. AdsPower/BitBrowser profile：只持有 profile_id 引用，profile 文件不落地本系统。

安全约定：返回值与异常消息只包含路径引用与状态描述，绝不包含 cookie/token 值。
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any

from app.core.exceptions import ConfigError

PROFILES_SCHEME = "profiles://"
# 容器内固定根；本机运行登录脚本时用 PROFILES_DIR 环境变量覆盖
DEFAULT_PROFILES_DIR = "/var/mera/profiles"
DEFAULT_SESSION_TTL_DAYS = 30

_PROFILES_DIR_ENV = "PROFILES_DIR"


def profiles_dir() -> Path:
    """profiles 根目录：PROFILES_DIR 环境变量优先，默认 /var/mera/profiles。"""
    return Path(os.environ.get(_PROFILES_DIR_ENV, DEFAULT_PROFILES_DIR))


def resolve_profile_ref(ref: str, *, base_dir: str | Path | None = None) -> Path:
    """解析 profiles:// 引用为绝对路径；拒绝空段、绝对路径与 .. 越界。"""
    if not isinstance(ref, str) or not ref.startswith(PROFILES_SCHEME):
        raise ConfigError("非法 profiles:// 引用（必须以 profiles:// 开头）")
    rel = ref[len(PROFILES_SCHEME) :]
    parts = PurePosixPath(rel).parts
    if not rel or rel.startswith("/") or any(part in ("", ".", "..") for part in parts):
        raise ConfigError("非法 profiles:// 引用（含空段/绝对路径/越界）")
    root = Path(base_dir) if base_dir is not None else profiles_dir()
    return root.joinpath(*parts)


@dataclass(frozen=True)
class BrowserSessionSpec:
    """browser_session 登录态声明：storage_state 为 profiles:// 引用。"""

    storage_state: str
    session_ttl_days: int = DEFAULT_SESSION_TTL_DAYS


def parse_browser_session(cfg: dict[str, Any], *, site_key: str) -> BrowserSessionSpec | None:
    """解析 config.yaml 的 browser_session 块；未配置返回 None，结构非法抛 ConfigError。"""
    raw = cfg.get("browser_session")
    if raw is None:
        return None
    if not isinstance(raw, dict) or not isinstance(raw.get("storage_state"), str):
        raise ConfigError(
            f"站点 {site_key} browser_session.storage_state 必须是 profiles:// 引用字符串"
        )
    ttl = raw.get("session_ttl_days", DEFAULT_SESSION_TTL_DAYS)
    if isinstance(ttl, bool) or not isinstance(ttl, int) or ttl <= 0:
        raise ConfigError(f"站点 {site_key} session_ttl_days 必须是正整数")
    return BrowserSessionSpec(
        storage_state=raw["storage_state"], session_ttl_days=ttl
    )


def browser_session_available(
    spec: BrowserSessionSpec,
    *,
    base_dir: str | Path | None = None,
    now: float | None = None,
) -> tuple[bool, str | None]:
    """登录态可用性判定：文件存在且 mtime 未超 TTL。原因串不含任何 cookie 值。"""
    try:
        path = resolve_profile_ref(spec.storage_state, base_dir=base_dir)
    except ConfigError:
        return False, "浏览器会话引用非法"
    if not path.is_file():
        return False, "浏览器会话缺失（运行 scripts/site_login.py 刷新）"
    current = time.time() if now is None else now
    if current - path.stat().st_mtime > spec.session_ttl_days * 86400:
        return False, f"浏览器会话已过期（TTL {spec.session_ttl_days} 天）"
    return True, None


def new_context_kwargs(cfg: dict[str, Any], *, site_key: str) -> dict[str, Any]:
    """生成 browser.new_context(**kwargs) 参数：配置了登录态时注入 storage_state 路径。"""
    spec = parse_browser_session(cfg, site_key=site_key)
    if spec is None:
        return {}
    return {"storage_state": str(resolve_profile_ref(spec.storage_state))}
