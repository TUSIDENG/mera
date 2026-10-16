"""M03 认证与授权核心：OIDC JWT 验签、身份提取、JWKS 缓存与 RLS 变量构造。

边界（实现指南 M03）：不做用户管理（Casdoor 负责）、不做菜单权限存储（Casdoor RBAC）。
- decode_token 纯函数化：jwks 与 now 全部注入，便于单测覆盖各非法分支；
- alg 白名单（仅 RS256）防算法混淆攻击；
- 过期/生效时间用注入的 now 判断，不依赖系统时钟；
- build_rls_vars 产出转义后的 SQL 字面量，供必须内联 SQL 的场景使用；
  常规路径走 app.db.rls.set_rls_context（bind 参数，天然防注入）。
"""

from __future__ import annotations

import json
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, cast

import httpx
import jwt
from cryptography.hazmat.primitives.asymmetric.rsa import RSAPublicKey

from app.core.exceptions import AuthError

# alg 白名单：Casdoor OIDC 使用 RS256；拒绝 none / HS* 等算法防混淆
ALLOWED_ALGORITHMS: tuple[str, ...] = ("RS256",)

DEFAULT_JWKS_TTL_SECONDS = 3600


@dataclass(frozen=True)
class Identity:
    """从 OIDC token 提取的调用方身份。"""

    user_id: str
    org_id: str
    roles: tuple[str, ...] = field(default_factory=tuple)


class JwksCache:
    """JWKS 拉取与 TTL 缓存；时钟与拉取函数均可注入，便于单测。"""

    def __init__(
        self,
        jwks_url: str,
        *,
        ttl_seconds: int = DEFAULT_JWKS_TTL_SECONDS,
        clock: Callable[[], float] = time.time,
        fetcher: Callable[[str], dict[str, Any]] | None = None,
    ) -> None:
        self._jwks_url = jwks_url
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._fetcher = fetcher or self._default_fetcher
        self._jwks: dict[str, Any] | None = None
        self._expires_at = 0.0

    @staticmethod
    def _default_fetcher(url: str) -> dict[str, Any]:
        response = httpx.get(url, timeout=10.0)
        response.raise_for_status()
        payload = response.json()
        if not isinstance(payload, dict) or "keys" not in payload:
            raise AuthError("JWKS 响应格式非法")
        return payload

    def get_jwks(self) -> dict[str, Any]:
        """命中缓存直接返回；过期或首次调用时重新拉取。"""
        now = self._clock()
        if self._jwks is None or now >= self._expires_at:
            try:
                self._jwks = self._fetcher(self._jwks_url)
            except AuthError:
                raise
            except Exception as exc:
                raise AuthError("无法获取 JWKS，token 无法验签") from exc
            self._expires_at = now + self._ttl_seconds
        return self._jwks


def _to_timestamp(now: float | datetime) -> float:
    if isinstance(now, datetime):
        return now.timestamp()
    return float(now)


def _find_jwk(jwks: dict[str, Any], kid: str | None) -> dict[str, Any]:
    keys = jwks.get("keys")
    if not isinstance(keys, list):
        raise AuthError("JWKS 缺少 keys")
    for jwk in keys:
        if isinstance(jwk, dict) and jwk.get("kid") == kid:
            return jwk
    raise AuthError("JWKS 中找不到匹配的签名密钥")


def _normalize_roles(raw: Any) -> tuple[str, ...]:
    """Casdoor roles 可能是字符串列表或对象列表（取 name 字段）。"""
    if not isinstance(raw, list):
        return ()
    roles: list[str] = []
    for item in raw:
        if isinstance(item, str):
            roles.append(item)
        elif isinstance(item, dict) and isinstance(item.get("name"), str):
            roles.append(item["name"])
    return tuple(roles)


def decode_token(
    token: str,
    jwks: dict[str, Any],
    now: float | datetime,
    *,
    audience: str | None = None,
    issuer: str | None = None,
) -> Identity:
    """验签并提取身份；任何非法分支统一抛 AuthError（401）。

    Casdoor claim 约定：sub=用户 ID，owner=组织名，roles=角色集合。
    """
    try:
        header = jwt.get_unverified_header(token)
    except jwt.DecodeError as exc:
        raise AuthError("Token 结构非法") from exc

    alg = header.get("alg")
    if alg not in ALLOWED_ALGORITHMS:
        raise AuthError("Token 签名算法不在白名单")

    jwk = _find_jwk(jwks, header.get("kid"))
    try:
        key = cast(RSAPublicKey, jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk)))
    except Exception as exc:
        raise AuthError("JWKS 签名密钥非法") from exc

    try:
        claims = jwt.decode(
            token,
            key=key,
            algorithms=list(ALLOWED_ALGORITHMS),
            audience=audience,
            issuer=issuer,
            options={
                "verify_exp": False,  # 过期用注入的 now 手动判断
                "verify_nbf": False,
                "verify_aud": audience is not None,
                "verify_iss": issuer is not None,
                "require": [],
            },
        )
    except jwt.InvalidTokenError as exc:
        raise AuthError("Token 验签失败") from exc

    now_ts = _to_timestamp(now)
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)):
        raise AuthError("Token 缺少过期时间")
    if now_ts >= float(exp):
        raise AuthError("Token 已过期")
    nbf = claims.get("nbf")
    if isinstance(nbf, (int, float)) and now_ts < float(nbf):
        raise AuthError("Token 尚未生效")

    sub = claims.get("sub")
    if not sub:
        raise AuthError("Token 缺少用户标识 sub")

    org = claims.get("owner") or claims.get("org")
    if not org:
        raise AuthError("Token 缺少组织信息")

    return Identity(user_id=str(sub), org_id=str(org), roles=_normalize_roles(claims.get("roles")))


def _quote_guc_literal(value: str) -> str:
    """把 GUC 值转义为 SQL 字符串字面量（单引号双写、反斜杠双写）。"""
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def build_rls_vars(identity: Identity) -> dict[str, str]:
    """产出转义后的 RLS GUC 字面量，供必须内联 SQL 的场景（如脚本/worker）使用。

    常规 Web 请求路径请使用 app.db.rls.set_rls_context（bind 参数，无需转义）。
    """
    return {
        "app.current_user_id": _quote_guc_literal(identity.user_id),
        "app.current_org_id": _quote_guc_literal(identity.org_id),
    }
