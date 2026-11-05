"""M04 采集任务路由：手动触发采集与任务查询。"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.depends import get_current_identity, get_enqueuer, get_repository
from app.core.exceptions import AppError, ConfigError
from app.core.security import Identity
from app.fetchers.config_loader import SITES_DIR, site_data_types
from app.repositories.dto import CreateTaskParams
from app.repositories.repository import Repository
from app.schemas.common import Page, PageParams
from app.schemas.snapshots import FetchRecordOut
from app.schemas.tasks import FetchTaskCreate, FetchTaskOut
from app.services.enqueue import FetchTaskEnqueuer

router = APIRouter(prefix="/fetch-tasks", tags=["fetch-tasks"])


@router.post("", response_model=FetchTaskOut, status_code=202)
def create_fetch_task(
    body: FetchTaskCreate,
    identity: Annotated[Identity, Depends(get_current_identity)],
    repo: Annotated[Repository, Depends(get_repository)],
    enqueuer: Annotated[FetchTaskEnqueuer, Depends(get_enqueuer)],
) -> FetchTaskOut:
    """手动触发采集；相同业务键存在进行中任务时复用（M02 语义），返回 202。

    task_type 必须在站点 config.yaml 声明的 data_types 内（如 openrouter 支持
    model_metrics/api_price），防止「成本任务跑出榜单数据」这类语义错配。
    """
    try:
        allowed_types = site_data_types(SITES_DIR, body.source_key)
    except ConfigError as exc:
        raise AppError(str(exc), code="unknown_source", status_code=422) from exc
    if body.task_type not in allowed_types:
        raise AppError(
            f"站点 {body.source_key} 不支持任务类型 {body.task_type}，"
            f"可选: {', '.join(allowed_types)}",
            code="invalid_task_type",
            status_code=422,
        )
    task = repo.create_task(
        CreateTaskParams(
            task_type=body.task_type,
            source_key=body.source_key,
            domain=body.domain,
            triggered_by=identity.user_id,
            auto_start=True,
            data={"fetch_strategy": body.fetch_strategy} if body.fetch_strategy else {},
        )
    )
    enqueuer.enqueue(task.id, strategy=body.fetch_strategy)
    return FetchTaskOut.model_validate(task)


@router.get("", response_model=Page[FetchTaskOut])
def list_fetch_tasks(
    repo: Annotated[Repository, Depends(get_repository)],
    page_params: Annotated[PageParams, Depends()],
    status: Annotated[str | None, Query(max_length=30)] = None,
) -> Page[FetchTaskOut]:
    items, total = repo.list_tasks(
        status=status, limit=page_params.limit, offset=page_params.offset
    )
    return Page(
        items=[FetchTaskOut.model_validate(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )


@router.get("/{task_id}/records", response_model=Page[FetchRecordOut])
def list_task_records(
    task_id: uuid.UUID,
    repo: Annotated[Repository, Depends(get_repository)],
    page_params: Annotated[PageParams, Depends()],
) -> Page[FetchRecordOut]:
    """任务维度采集留痕（按时间倒序）：该次任务采到的记录明细。"""
    items, total = repo.list_fetch_records_by_task(
        task_id, limit=page_params.limit, offset=page_params.offset
    )
    return Page(
        items=[FetchRecordOut.model_validate(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )
