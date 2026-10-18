"""业务路由聚合（实现指南 M01：业务路由统一在 api/v1 汇总，挂 /api/v1 前缀）。

M04：models / fetch-tasks / evaluations / subscription-plans / analysis / admin；
/internal 内网路由不挂本前缀，由 main.py 单独挂载。
"""
from fastapi import APIRouter

from app.api.v1 import admin, analysis, evaluations, fetch_tasks, models, plans

api_router = APIRouter()
api_router.include_router(models.router)
api_router.include_router(fetch_tasks.router)
api_router.include_router(evaluations.router)
api_router.include_router(plans.router)
api_router.include_router(analysis.router)
api_router.include_router(admin.router)
