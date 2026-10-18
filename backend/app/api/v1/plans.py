"""M04 订阅套餐路由：活跃套餐查询。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.depends import get_repository
from app.repositories.repository import Repository
from app.schemas.catalogs import PlanOut
from app.schemas.common import Page, PageParams

router = APIRouter(prefix="/subscription-plans", tags=["subscription-plans"])


@router.get("", response_model=Page[PlanOut])
def list_subscription_plans(
    repo: Annotated[Repository, Depends(get_repository)],
    page_params: Annotated[PageParams, Depends()],
    provider: Annotated[str | None, Query(max_length=50)] = None,
) -> Page[PlanOut]:
    """按 provider 过滤活跃套餐。"""
    items, total = repo.list_plans(
        provider=provider,
        active_only=True,
        limit=page_params.limit,
        offset=page_params.offset,
    )
    return Page(
        items=[PlanOut.model_validate(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )
