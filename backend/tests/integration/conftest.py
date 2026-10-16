"""集成测试公共夹具：真实 PostgreSQL 连接串与已迁移配置。

优先使用 TEST_DATABASE_URL 指向的外部库；否则通过 testcontainers 启动 postgres:18-alpine。
迁移（alembic upgrade head）幂等，session 级共享执行一次。
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings


@pytest.fixture(scope="session")
def postgres_url() -> Iterator[str]:
    external_url = os.getenv("TEST_DATABASE_URL")
    if external_url:
        yield external_url
        return

    testcontainers = pytest.importorskip("testcontainers.postgresql")
    with testcontainers.PostgresContainer("postgres:18-alpine") as postgres:
        yield postgres.get_connection_url(driver="psycopg")


@pytest.fixture(scope="session")
def migrated_settings(postgres_url: str) -> Settings:
    settings = Settings(
        _env_file=None,
        database_url=postgres_url,
        redis_url="redis://localhost:6379/0",
    )
    from alembic import command
    from alembic.config import Config

    config = Config("alembic.ini")
    config.set_main_option("script_location", "app/db/alembic")
    config.set_main_option("sqlalchemy.url", settings.database_url)
    command.upgrade(config, "head")
    return settings


@pytest.fixture()
def session_factory(migrated_settings: Settings) -> sessionmaker[Session]:
    engine = create_engine(migrated_settings.database_url, future=True)
    return sessionmaker(bind=engine, expire_on_commit=False)
