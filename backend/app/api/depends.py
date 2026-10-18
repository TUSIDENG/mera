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
from app.core.exceptions import AuthError, ForbiddenError
from app.core.security import Identity, JwksCache, decode_token
from app.db.rls import set_rls_context
from app.db.session import get_session_factory
from app.repositories.repository import Repository
from app.services.enqueue import FetchTaskEnqueuer


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
        issuer=(settings.casdoor_issuer or settings.casdoor_endpoint).rstrip("/"),
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


# --- M04 依赖 ---

ADMIN_ROLE = "mera-admin"


def get_repository(
    session: Annotated[Session, Depends(get_db_session)],
) -> Repository:
    """业务路由仓储：绑定已注入 RLS 上下文的会话。"""
    return Repository(session)


def get_plain_session(request: Request) -> Iterator[Session]:
    """无 RLS 的事务会话：仅供 /internal 内网路由（fetch_tasks 等表无 RLS）。"""
    settings: Settings = request.app.state.settings
    factory = get_session_factory(settings)
    with factory() as session, session.begin():
        yield session


def get_internal_repository(
    session: Annotated[Session, Depends(get_plain_session)],
) -> Repository:
    return Repository(session)


def require_admin(
    identity: Annotated[Identity, Depends(get_current_identity)],
) -> Identity:
    """管理端角色校验：mera-admin（Casdoor 组织级角色，禁止全局 admin）。"""
    if ADMIN_ROLE not in identity.roles:
        raise ForbiddenError("需要管理员角色 mera-admin")
    return identity


def get_enqueuer(request: Request) -> FetchTaskEnqueuer:
    """进程级共享的入队器（懒加载 Celery，缓存于 app.state）。"""
    enqueuer = getattr(request.app.state, "fetch_enqueuer", None)
    if enqueuer is None:
        enqueuer = FetchTaskEnqueuer(request.app.state.settings)
        request.app.state.fetch_enqueuer = enqueuer
    return enqueuer
