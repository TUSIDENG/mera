"""M04 分析路由：调用 M09 纯函数引擎产出加权排名。"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.depends import get_current_identity, get_repository
from app.core.security import Identity
from app.repositories.repository import Repository
from app.schemas.analysis import AnalysisRunRequest, AnalysisRunResponse, RankedModelOut
from app.scoring.engine import rank_models
from app.scoring.models import ModelInput, RankInputs, Weights

router = APIRouter(prefix="/analysis", tags=["analysis"])


def _price(value: object) -> Decimal | None:
    """快照 data 中的每 token 单价为字符串；缺省或非法时返回 None，由引擎按缺项处理。"""
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def _display_name(value: object) -> str | None:
    """展示名统一转字符串；缺省返回 None。"""
    return None if value is None else str(value)


@router.post("/run", response_model=AnalysisRunResponse)
def run_analysis(
    payload: AnalysisRunRequest,
    identity: Annotated[Identity, Depends(get_current_identity)],
    repo: Annotated[Repository, Depends(get_repository)],
) -> AnalysisRunResponse:
    """读取 domain 最新快照并返回排名；DB 读取只留在本路由层，引擎零 I/O。"""
    _ = identity
    models = [
        ModelInput(
            model_id=snapshot.model_id,
            provider=snapshot.provider,
            benchmark_score=snapshot.benchmark_score,
            input_price=_price(snapshot.data.get("input_price")),
            output_price=_price(snapshot.data.get("output_price")),
            display_name=_display_name(snapshot.data.get("display_name")),
        )
        for snapshot in repo.latest_snapshots(payload.domain)
    ]
    ranked = rank_models(
        RankInputs(
            models=models,
            tokens_per_month=payload.tokens_per_month,
            input_ratio=payload.input_ratio,
        ),
        Weights(benchmark=payload.benchmark_weight, price=payload.price_weight),
    )
    return AnalysisRunResponse(
        domain=payload.domain,
        items=[RankedModelOut.model_validate(item) for item in ranked],
        total=len(ranked),
    )
