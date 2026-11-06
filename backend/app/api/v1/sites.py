"""M04 站点列表：返回各站点支持的数据域，前端据此联动任务类型选项。

公开信息（无敏感配置），仅做元数据枚举，不实例化采集方案。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.depends import get_current_identity
from app.core.security import Identity
from app.fetchers.config_loader import SITES_DIR, list_sites
from app.schemas.sites import SiteOut

router = APIRouter(prefix="/sites", tags=["sites"])


@router.get("", response_model=list[SiteOut])
def list_collection_sites(
    identity: Annotated[Identity, Depends(get_current_identity)],
) -> list[SiteOut]:
    """返回已配置站点及各自支持的任务类型（data_types）。"""
    _ = identity
    return [
        SiteOut(
            key=site.key,
            label=site.label,
            domain=site.domain,
            data_type=site.data_type,
            data_types=list(site.data_types),
            description=site.description,
            homepage=site.homepage,
        )
        for site in list_sites(SITES_DIR)
    ]
