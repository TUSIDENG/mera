"""M05 签名与密钥工具（纯函数）。

安全约定：异常消息中一律不得包含密钥值本身；密钥引用（如 env:XXX）不是敏感信息。
"""

from __future__ import annotations

import hashlib
import hmac
import os
from collections.abc import Mapping
from typing import Any

from app.core.exceptions import SecretError

_ENV_PREFIX = "env:"


def sign_hmac_md5(params: Mapping[str, Any], secret: str, timestamp: int | str) -> str:
    """还原常见站点签名：sign = HMAC_MD5(sorted(kv) + timestamp)。

    timestamp 显式传参以保证可测试性；参数顺序无关（按键排序）。
    """
    if not secret:
        raise SecretError("签名密钥为空或未配置")
    raw = "&".join(f"{key}={params[key]}" for key in sorted(params)) + str(timestamp)
    return hmac.new(secret.encode(), raw.encode(), hashlib.md5).hexdigest()


def read_secret(ref: str) -> str:
    """按引用读取密钥，当前仅支持 env: 前缀（环境变量注入，禁止写死/入库）。"""
    if not isinstance(ref, str) or not ref.startswith(_ENV_PREFIX):
        raise SecretError("不支持的密钥引用格式，仅支持 env: 前缀")
    name = ref[len(_ENV_PREFIX):]
    if not name:
        raise SecretError("密钥引用缺少环境变量名")
    value = os.environ.get(name)
    if not value:
        raise SecretError(f"密钥环境变量未设置或为空: {name}")
    return value
