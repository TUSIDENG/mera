"""公共测试基建（M01）。

单测禁止网络/数据库（实现指南 3.4）；环境变量必须在导入 app 前注入，
否则 app.main 的模块级 `app = create_app()` 会因缺必填配置而失败。
"""
import os

os.environ.setdefault(
    "DATABASE_URL", "postgresql+psycopg://mera:mera@localhost:5432/mera"
)
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")

import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app


@pytest.fixture
def settings() -> Settings:
    """显式构造 Settings（不读 .env 文件），env 覆盖经 monkeypatch 注入。"""
    return Settings(_env_file=None)


@pytest.fixture
def client(settings) -> TestClient:
    """按 Settings 注入构造的 app 实例（app factory 支持多实例）。"""
    return TestClient(create_app(settings))
