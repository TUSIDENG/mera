"""M01 应用配置：全部来自环境变量（与 docker-compose / .env 对齐）。

约定（实现指南 3.2）：模块内禁止直接读 os.environ，统一注入 Settings。
"""

import json
from functools import lru_cache
from typing import Annotated

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- 应用 ---
    app_name: str = "MERA API"
    app_env: str = "local"  # local / dev / prod
    debug: bool = False
    api_prefix: str = "/api/v1"
    # NoDecode：关闭 pydantic-settings 的 JSON 预解码，原始字符串交给下方校验器
    # 同时兼容 JSON 数组（CORS_ORIGINS='["http://a"]'）与逗号分隔（CORS_ORIGINS=http://a,http://b）
    cors_origins: Annotated[list[str], NoDecode] = ["http://localhost:3000"]

    # --- 数据与基础设施（M01 仅持有不连接；M02/M08 懒加载使用） ---
    database_url: str = Field(..., description="postgresql+psycopg://user:pass@host:5432/mera")
    redis_url: str = Field(..., description="redis://host:6379/0")
    celery_broker_url: str | None = None
    celery_result_backend: str | None = None

    # --- 采集熔断（M05 使用，M02 状态机测试共享默认值） ---
    min_fetch_hits: int = 1
    max_fetch_attempts: int = 3

    # --- 认证（M03） ---
    casdoor_endpoint: str | None = None
    casdoor_client_id: str | None = None
    casdoor_client_secret: str | None = None
    # token 的 iss 与容器内 endpoint 不一致时显式指定（如本地 localhost vs 容器名 casdoor）
    casdoor_issuer: str | None = None
    jwks_cache_ttl_seconds: int = 3600

    # --- 内网接口（M04：RPA 回调等 /internal 路由共享密钥） ---
    internal_api_token: str | None = None

    # --- 通知（M10 使用，预留；SMTP 未配置则仅走 WebSocket） ---
    smtp_host: str | None = None
    smtp_port: int = 465
    smtp_user: str | None = None
    smtp_password: str | None = None
    smtp_from: str | None = None

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_cors_origins(cls, v):
        if isinstance(v, str):
            v = v.strip()
            if v.startswith("["):
                return json.loads(v)
            return [s.strip() for s in v.split(",") if s.strip()]
        return v

    @property
    def broker_url(self) -> str:
        """Celery broker：未单独配置时回落 redis_url。"""
        return self.celery_broker_url or self.redis_url

    @property
    def result_backend(self) -> str:
        """Celery result backend：未单独配置时回落 redis_url。"""
        return self.celery_result_backend or self.redis_url


@lru_cache
def get_settings() -> Settings:
    """进程级单例入口；测试应直接构造 Settings 并注入 create_app。"""
    return Settings()  # type: ignore[call-arg]
