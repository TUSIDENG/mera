"""数据库引擎与会话工厂（懒加载，M01 不允许构造 app 时连库）。"""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings


@lru_cache
def get_engine(database_url: str) -> Engine:
    """按连接串缓存引擎。"""
    connect_args = {"check_same_thread": False} if database_url.startswith("sqlite") else {}
    return create_engine(database_url, pool_pre_ping=True, future=True, connect_args=connect_args)


def get_session_factory(settings: Settings | None = None) -> sessionmaker[Session]:
    resolved = settings or get_settings()
    return sessionmaker(bind=get_engine(resolved.database_url), expire_on_commit=False)


def get_db_session(settings: Settings | None = None) -> Iterator[Session]:
    """FastAPI 会话依赖；M03 将在此事务中注入 SET LOCAL RLS 变量。"""
    factory = get_session_factory(settings)
    with factory() as session:
        yield session
