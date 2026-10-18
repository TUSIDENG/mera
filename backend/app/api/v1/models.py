"""M04 模型榜单路由：当前榜单与单模型历史快照。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.depends import get_repository
from app.repositories.repository import Repository
from app.schemas.common import Page, PageParams
from app.schemas.snapshots import SnapshotOut

router = APIRouter(tags=["models"])


@router.get("/models", response_model=Page[SnapshotOut])
def list_models(
    repo: Annotated[Repository, Depends(get_repository)],
    page_params: Annotated[PageParams, Depends()],
    domain: Annotated[str, Query(min_length=1, max_length=50)],
) -> Page[SnapshotOut]:
    """按 domain 返回榜单快照（benchmark_score 降序）。"""
    items, total = repo.list_snapshots(
        domain, limit=page_params.limit, offset=page_params.offset
    )
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
    """单模型全部 domain 的历史快照。"""
    items = repo.snapshots_by_model(model_id)
    return [SnapshotOut.model_validate(item) for item in items]
