"""M03 FastAPI 依赖：Bearer Token 解析为 Identity，并注入 RLS 会话。

- get_current_identity：JWKS 验签（app/core/security.py），非法 token 一律 AuthError(401)；
- get_db_session：在事务内 SET LOCAL RLS 变量后返回会话，组织隔离由数据库强制；
- open_rls_session：与 get_db_session 同逻辑的可直接调用版本，供集成测试/worker 复用。
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Annotated

from fastapi import Depends, Request
from sqlalchemy.orm import Session

from app.core.config import Settings
from app.core.exceptions import AuthError
from app.core.security import Identity, JwksCache, decode_token
from app.db.rls import set_rls_context
from app.db.session import get_session_factory


def get_current_identity(request: Request) -> Identity:
    """校验 Authorization: Bearer <token> 并返回身份。"""
    settings: Settings = request.app.state.settings
    if not settings.casdoor_endpoint or not settings.casdoor_client_id:
        raise AuthError("服务端未配置 Casdoor 认证")

    scheme, _, token = request.headers.get("Authorization", "").partition(" ")
    token = token.strip()
    if scheme.lower() != "bearer" or not token:
        raise AuthError("缺少 Bearer Token")

    cache: JwksCache | None = getattr(request.app.state, "jwks_cache", None)
    if cache is None:
        raise AuthError("JWKS 缓存未初始化")

    return decode_token(
        token,
        cache.get_jwks(),
        time.time(),
        audience=settings.casdoor_client_id,
        issuer=settings.casdoor_endpoint.rstrip("/"),
    )


@contextmanager
def open_rls_session(settings: Settings, identity: Identity) -> Iterator[Session]:
    """开启事务、注入 RLS 变量并产出会话；正常退出提交，异常回滚。"""
    factory = get_session_factory(settings)
    with factory() as session, session.begin():
        set_rls_context(session, user_id=identity.user_id, org_id=identity.org_id)
        yield session


def get_db_session(
    request: Request,
    identity: Annotated[Identity, Depends(get_current_identity)],
) -> Iterator[Session]:
    """M03 RLS 会话依赖：SET LOCAL rls 变量后返回会话。"""
    settings: Settings = request.app.state.settings
    with open_rls_session(settings, identity) as session:
        yield session
