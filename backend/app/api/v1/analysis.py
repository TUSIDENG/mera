"""M04 分析路由：调用 M09 纯函数引擎产出加权排名。

价格从 model_api_prices 表按 (model_id, provider) 关联（与榜单分表后不再读
snapshot.data）；无榜分的模型不参与排名。
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.depends import get_current_identity, get_repository
from app.core.security import Identity
from app.repositories.repository import Repository
from app.schemas.analysis import AnalysisRunRequest, AnalysisRunResponse, RankedModelOut
from app.scoring.engine import rank_models
from app.scoring.models import ModelInput, RankInputs, Weights

router = APIRouter(prefix="/analysis", tags=["analysis"])


def _display_name(value: object) -> str | None:
    """展示名统一转字符串；缺省返回 None。"""
    return None if value is None else str(value)


@router.post("/run", response_model=AnalysisRunResponse)
def run_analysis(
    payload: AnalysisRunRequest,
    identity: Annotated[Identity, Depends(get_current_identity)],
    repo: Annotated[Repository, Depends(get_repository)],
) -> AnalysisRunResponse:
    """读取榜单快照与 API 价格表并返回排名；DB 读取只留在本路由层。"""
    _ = identity
    prices = {
        (price.model_id, price.provider): price for price in repo.latest_prices()
    }
    models = []
    for snapshot in repo.latest_snapshots():
        if snapshot.benchmark_score is None:
            continue  # 无分模型不参与加权排名（区别于 0 分）
        price = prices.get((snapshot.model_id, snapshot.provider))
        models.append(
            ModelInput(
                model_id=snapshot.model_id,
                provider=snapshot.provider,
                benchmark_score=snapshot.benchmark_score,
                input_price=price.input_price if price is not None else None,
                output_price=price.output_price if price is not None else None,
                display_name=_display_name(snapshot.data.get("display_name")),
            )
        )
    ranked = rank_models(
        RankInputs(
            models=models,
            tokens_per_month=payload.tokens_per_month,
            input_ratio=payload.input_ratio,
        ),
        Weights(benchmark=payload.benchmark_weight, price=payload.price_weight),
    )
    return AnalysisRunResponse(
        items=[RankedModelOut.model_validate(item) for item in ranked],
        total=len(ranked),
    )
