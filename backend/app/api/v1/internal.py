"""M04 内网路由：RPA 回调（/internal 前缀，不挂 /api/v1，共享密钥鉴权）。

回调契约见《数据获取实现指南》第 5 节：终态分流复用 fetch_tasks 状态机。
"""

from __future__ import annotations

import hmac
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request

from app.api.depends import get_internal_repository
from app.core.exceptions import AuthError, NotFoundError
from app.db.enums import FetchTaskStatus
from app.repositories.repository import Repository
from app.schemas.tasks import FetchCallbackIn, FetchTaskOut

router = APIRouter(prefix="/internal", tags=["internal"])


def verify_internal_token(request: Request) -> None:
    """X-Internal-Token 共享密钥校验；未配置或不匹配一律 401。"""
    settings = request.app.state.settings
    expected = settings.internal_api_token
    provided = request.headers.get("X-Internal-Token", "")
    if not expected or not provided or not hmac.compare_digest(provided, expected):
        raise AuthError("内网接口鉴权失败")


@router.post("/fetch/callback/{fetch_task_id}", response_model=FetchTaskOut)
def fetch_callback(
    fetch_task_id: uuid.UUID,
    body: FetchCallbackIn,
    request: Request,
    repo: Annotated[Repository, Depends(get_internal_repository)],
    _: Annotated[None, Depends(verify_internal_token)],
) -> FetchTaskOut:
    """RPA 回调终态分流；任务不存在 404，非法迁移由状态机抛 409。"""
    task = repo.get_task(fetch_task_id)
    if task is None:
        raise NotFoundError(f"采集任务不存在: {fetch_task_id}")

    settings = request.app.state.settings
    if body.result == FetchTaskStatus.SUCCEEDED.value:
        task = repo.mark_succeeded(
            fetch_task_id,
            strategy=body.strategy or task.fetch_strategy or "rpa",
            hit_count=body.hit_count,
            min_hits=settings.min_fetch_hits,
        )
    elif body.result == FetchTaskStatus.PARTIAL_SUCCEEDED.value:
        task = repo.mark_partial_succeeded(
            fetch_task_id,
            strategy=body.strategy or task.fetch_strategy or "rpa",
            hit_count=body.hit_count,
        )
    elif body.result == FetchTaskStatus.FAILED_EXHAUSTED.value:
        task = repo.mark_failed_exhausted(
            fetch_task_id, error_message=body.error_message
        )
    else:
        task = repo.mark_captcha_pending(fetch_task_id)
    return FetchTaskOut.model_validate(task)
