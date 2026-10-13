"""MERA 后端入口（M01）：app factory + 中间件 + 统一异常处理。

- 中间件注册顺序（实现指南 M01）：CORS → 认证（M03 预留）→ RLS 会话（M02 预留）；
- 本模块不建立任何 DB/Redis 连接——引擎由 M02 懒加载提供；
- uvicorn 入口：uvicorn app.main:app（Dockerfile CMD / start-backend.sh）。
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.api.health import router as health_router
from app.api.v1 import api_router
from app.core.config import Settings, get_settings
from app.core.exceptions import AppError
from app.core.logging import configure_logging, get_logger


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or get_settings()
    configure_logging(settings)
    logger = get_logger(__name__)

    app = FastAPI(title=settings.app_name, debug=settings.debug)
    app.state.settings = settings

    # 1) CORS（认证 / RLS 会话中间件在 M02/M03 完成后按顺序在其后注册）
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # 2) 统一异常处理（实现指南 3.1）
    @app.exception_handler(AppError)
    async def _handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"code": exc.code, "message": exc.message},
        )

    @app.exception_handler(Exception)
    async def _handle_unexpected(request: Request, exc: Exception) -> JSONResponse:
        # 堆栈只进日志，响应体不含任何内部细节（M01 验收项）
        logger.exception(
            "unhandled error on %s %s", request.method, request.url.path
        )
        return JSONResponse(
            status_code=500,
            content={"code": "internal_error", "message": "internal server error"},
        )

    # 3) 路由：/healthz 在根路径；业务路由统一挂 settings.api_prefix
    app.include_router(health_router)
    app.include_router(api_router, prefix=settings.api_prefix)
    return app


app = create_app()
