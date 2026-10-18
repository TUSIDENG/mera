"""M04 采集任务路由：手动触发采集与任务查询。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.depends import get_current_identity, get_enqueuer, get_repository
from app.core.security import Identity
from app.repositories.dto import CreateTaskParams
from app.repositories.repository import Repository
from app.schemas.common import Page, PageParams
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
    """手动触发采集；相同业务键存在进行中任务时复用（M02 语义），返回 202。"""
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
