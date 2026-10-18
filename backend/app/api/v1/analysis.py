"""M04 分析路由：评分触发（M09 完成前返回 501 占位）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.depends import get_current_identity
from app.core.exceptions import AppError
from app.core.security import Identity

router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.post("/run")
def run_analysis(
    identity: Annotated[Identity, Depends(get_current_identity)],
) -> None:
    """触发评分；M09 分析引擎就绪前返回 501。identity 仅用于鉴权。"""
    _ = identity
    raise AppError(
        "分析引擎尚未就绪（M09）", code="not_implemented", status_code=501
    )
