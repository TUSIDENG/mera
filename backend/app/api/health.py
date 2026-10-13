"""M01 健康检查：根路径（不经 /api/v1 前缀），供 compose 健康检查与负载均衡探测。"""
from fastapi import APIRouter, Request

router = APIRouter(tags=["health"])


@router.get("/healthz")
def healthz(request: Request) -> dict:
    settings = request.app.state.settings
    return {"status": "ok", "app_env": settings.app_env}
