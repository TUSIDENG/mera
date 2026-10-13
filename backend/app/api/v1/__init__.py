"""业务路由聚合（实现指南 M01：业务路由统一在 api/v1 汇总，挂 /api/v1 前缀）。

M04 起在此追加：
    from app.api.v1 import models, tasks, evaluations, analysis
    api_router.include_router(models.router)
"""
from fastapi import APIRouter

api_router = APIRouter()
