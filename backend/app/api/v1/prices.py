"""M04 API 按量价格路由：活跃价格查询（成本页展示）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.depends import get_repository
from app.repositories.repository import Repository
from app.schemas.catalogs import PriceOut
from app.schemas.common import Page, PageParams

router = APIRouter(prefix="/api-prices", tags=["api-prices"])


@router.get("", response_model=Page[PriceOut])
def list_api_prices(
    repo: Annotated[Repository, Depends(get_repository)],
    page_params: Annotated[PageParams, Depends()],
    provider: Annotated[str | None, Query(max_length=50)] = None,
) -> Page[PriceOut]:
    """按 provider 过滤活跃 API 价格（成本页展示用）。"""
    items, total = repo.list_prices(
        provider=provider,
        active_only=True,
        limit=page_params.limit,
        offset=page_params.offset,
    )
    return Page(
        items=[PriceOut.model_validate(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )
