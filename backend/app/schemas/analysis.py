"""M09/M04 分析接口请求与响应模型。"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class AnalysisRunRequest(BaseModel):
    """评分运行参数：权重由引擎校验和为 1，用法假设用于月成本估算。"""

    model_config = ConfigDict(allow_inf_nan=False)

    benchmark_weight: float = 0.6
    price_weight: float = 0.4
    tokens_per_month: int = Field(default=1_000_000, ge=1)
    input_ratio: float = Field(default=0.7, ge=0.0, le=1.0)


class RankedModelOut(BaseModel):
    """单个模型排名结果，字段与 M09 RankedModel 对齐。"""

    model_config = ConfigDict(from_attributes=True)

    model_id: str
    provider: str
    display_name: str | None = None
    benchmark_score: float
    benchmark_norm: float
    price_norm: float
    monthly_cost: float | None = None
    composite_score: float
    rank: int


class AnalysisRunResponse(BaseModel):
    """分析结果：items 按 rank 升序。"""

    items: list[RankedModelOut]
    total: int
