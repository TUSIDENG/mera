"""M01 验收测试（实现指南 M01 卡片）：Settings / create_app / healthz / 异常映射 / 日志。"""
import io
import logging

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.core.config import Settings, get_settings
from app.core.exceptions import AppError, AuthError, InvalidWeights
from app.core.logging import JsonFormatter, get_logger
from app.main import create_app

# ---------------- Settings（配置装载） ----------------

def test_settings_load_from_env(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://u:p@h:5432/db")
    monkeypatch.setenv("REDIS_URL", "redis://h:6379/0")
    monkeypatch.setenv("CASDOOR_ENDPOINT", "http://casdoor:8000")
    monkeypatch.setenv("CORS_ORIGINS", '["http://a.example", "http://b.example"]')

    s = Settings(_env_file=None)

    assert s.database_url == "postgresql+psycopg://u:p@h:5432/db"
    assert s.cors_origins == ["http://a.example", "http://b.example"]
    assert s.casdoor_endpoint == "http://casdoor:8000"
    # celery_broker_url 未配置时回落 redis_url
    assert s.broker_url == "redis://h:6379/0"
    assert s.result_backend == "redis://h:6379/0"


def test_settings_celery_urls_explicit(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    monkeypatch.setenv("REDIS_URL", "redis://h:6379/0")
    monkeypatch.setenv("CELERY_BROKER_URL", "redis://h:6379/2")
    monkeypatch.setenv("CELERY_RESULT_BACKEND", "redis://h:6379/3")

    s = Settings(_env_file=None)

    assert s.broker_url == "redis://h:6379/2"
    assert s.result_backend == "redis://h:6379/3"


def test_settings_missing_required_raises(monkeypatch):
    """验收：缺必填项（DATABASE_URL/REDIS_URL）启动即报错。"""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("REDIS_URL", raising=False)
    with pytest.raises(ValidationError):
        Settings(_env_file=None)


def test_cors_origins_comma_separated(monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@h/db")
    monkeypatch.setenv("REDIS_URL", "redis://h:6379/0")
    monkeypatch.setenv("CORS_ORIGINS", "http://x.example, http://y.example")

    assert Settings(_env_file=None).cors_origins == [
        "http://x.example",
        "http://y.example",
    ]


def test_get_settings_cached(monkeypatch):
    get_settings.cache_clear()
    try:
        s1 = get_settings()
        monkeypatch.setenv("DATABASE_URL", "postgresql://changed/db")
        assert get_settings() is s1  # lru_cache：进程内单例
    finally:
        get_settings.cache_clear()


# ---------------- create_app / healthz ----------------

def test_create_app_without_db_connection(settings):
    """验收：create_app 不连 DB/Redis 即可构造（引擎由 M02 懒加载）。"""
    app = create_app(settings)
    assert app.state.settings is settings


def test_healthz_ok(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    body = r.json()
    assert body["status"] == "ok"
    assert body["app_env"] == "local"


def test_api_router_empty_until_m04():
    """业务路由统一挂 /api/v1；M04 之前聚合 router 保持为空。"""
    from app.api.v1 import api_router

    assert api_router.routes == []


def test_healthz_at_root_not_under_api_prefix(client):
    """healthz 挂根路径供 compose 探测；业务前缀下不应有同路径。"""
    assert client.get("/healthz").status_code == 200
    assert client.get("/api/v1/healthz").status_code == 404


# ---------------- 统一异常处理 ----------------

def test_app_error_mapped_to_code_and_status(client):
    @client.app.get("/boom-weights")
    def boom_weights():
        raise InvalidWeights("权重和必须为 1")

    r = client.get("/boom-weights")
    assert r.status_code == 422
    assert r.json() == {"code": "invalid_weights", "message": "权重和必须为 1"}


def test_auth_error_maps_401(client):
    @client.app.get("/boom-auth")
    def boom_auth():
        raise AuthError("token 无效")

    r = client.get("/boom-auth")
    assert r.status_code == 401
    assert r.json()["code"] == "auth_error"


def test_app_error_instance_level_override(client):
    @client.app.get("/boom-override")
    def boom_override():
        raise AppError("custom", code="custom_code", status_code=418)

    r = client.get("/boom-override")
    assert r.status_code == 418
    assert r.json()["code"] == "custom_code"


def test_unhandled_exception_returns_generic_500(settings):
    """验收：未知异常返回 500，响应不含堆栈与内部细节。"""
    app = create_app(settings)

    @app.get("/boom-crash")
    def boom_crash():
        raise RuntimeError("SECRET-INTERNAL-DETAILS")

    client = TestClient(app, raise_server_exceptions=False)
    r = client.get("/boom-crash")
    assert r.status_code == 500
    assert r.json() == {"code": "internal_error", "message": "internal server error"}
    assert "SECRET-INTERNAL-DETAILS" not in r.text
    assert "RuntimeError" not in r.text


# ---------------- 日志 ----------------

def test_get_logger_and_json_format(settings):
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())

    logger = get_logger("m01.test")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        logger.info("hello %s", "world", extra={"task_id": "t-1"})
    finally:
        logger.removeHandler(handler)

    out = stream.getvalue()
    assert '"message": "hello world"' in out
    assert '"task_id": "t-1"' in out
    assert '"level": "INFO"' in out


def test_json_formatter_includes_exception():
    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(JsonFormatter())

    logger = get_logger("m01.test.exc")
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        try:
            raise ValueError("boom")
        except ValueError:
            logger.exception("failed")
    finally:
        logger.removeHandler(handler)

    out = stream.getvalue()
    assert "ValueError: boom" in out
    assert '"message": "failed"' in out
