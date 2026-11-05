"""M04 模型榜单路由：当前榜单、单模型快照与采集历史。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.depends import get_repository
from app.repositories.repository import Repository
from app.schemas.common import Page, PageParams
from app.schemas.snapshots import FetchRecordOut, SnapshotOut

router = APIRouter(tags=["models"])


@router.get("/models", response_model=Page[SnapshotOut])
def list_models(
    repo: Annotated[Repository, Depends(get_repository)],
    page_params: Annotated[PageParams, Depends()],
) -> Page[SnapshotOut]:
    """模型榜单：一个模型一行（多来源已在 data.sources 内合并），按主榜分降序。"""
    items, total = repo.list_snapshots(limit=page_params.limit, offset=page_params.offset)
    return Page(
        items=[SnapshotOut.model_validate(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )


@router.get("/models/{model_id}/snapshots", response_model=list[SnapshotOut])
def list_model_snapshots(
    model_id: str,
    repo: Annotated[Repository, Depends(get_repository)],
) -> list[SnapshotOut]:
    """单模型当前快照（一个模型一行，列表长度为 0 或 1，保留列表形态兼容旧调用）。"""
    items = repo.snapshots_by_model(model_id)
    return [SnapshotOut.model_validate(item) for item in items]


@router.get("/models/{model_id}/fetch-records", response_model=Page[FetchRecordOut])
def list_model_fetch_records(
    model_id: str,
    repo: Annotated[Repository, Depends(get_repository)],
    page_params: Annotated[PageParams, Depends()],
) -> Page[FetchRecordOut]:
    """单模型采集历史（按时间倒序）：哪次任务、从哪个平台、采了什么。"""
    items, total = repo.list_fetch_records_by_model(
        model_id, limit=page_params.limit, offset=page_params.offset
    )
    return Page(
        items=[FetchRecordOut.model_validate(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )
