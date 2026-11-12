"""LangGraph 离线打分管线：load -> prompt -> parse -> persist。

- load：读取快照当前态（data.sources 各平台采集数据 + 采集维度原始分）
- prompt：组装 rubric 提示词，LLM structured output 产出 ScoreResult
- parse：合法分钳位到 [0,100] 并保留两位小数，维度缺失为 None
- persist：写 scores/benchmark_score/score_source=llm:<scorer> 与 data.llm_score 留痕

兜底：LLM 调用/解析失败向调用方抛错（由任务层重试），全空结果（overall 与全部
维度均 null）不落库，行保持采集回落分。
"""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.graph import END, StateGraph
from pydantic import BaseModel, Field

from app.core.config import Settings
from app.core.logging import get_logger
from app.llm_scoring.config import SCORER_REGISTRY, build_chat_model
from app.llm_scoring.prompt import DIMENSIONS, build_prompt

logger = get_logger(__name__)


class ScoreResult(BaseModel):
    """LLM 打分结构化输出；确实无法得出的维度为 None（列表显示 -）。

    不加 ge/le 硬约束：越界分由 parse 节点钳位到 [0,100]，避免 LLM 输出
    轻微越界时 structured output 直接校验失败。
    """

    overall: float | None = None
    dims: dict[str, float | None] = Field(default_factory=dict)
    rationale: str = ""
    confidence: float | None = None


class ScoringState(TypedDict, total=False):
    model_id: str
    scorer: str
    provider: str
    sources: dict[str, Any]
    raw_scores: dict[str, Any]
    result: ScoreResult | None
    error: str | None


def _clamp(value: float | None) -> float | None:
    if value is None:
        return None
    return round(min(max(float(value), 0.0), 100.0), 2)


def build_scoring_graph(
    repo: Any,
    llm: Any,
    *,
    max_input_chars: int,
    structured_output_kwargs: dict[str, Any] | None = None,
) -> Any:
    """装配四节点打分管线；llm 为 chat 模型（单测可注入假模型）。"""
    output_kwargs = structured_output_kwargs or {}

    def load_node(state: ScoringState) -> dict[str, Any]:
        snapshot = repo.get_snapshot(state["model_id"])
        if snapshot is None:
            return {"error": f"模型快照不存在: {state['model_id']}"}
        return {
            "provider": snapshot.provider,
            "sources": (snapshot.data or {}).get("sources") or {},
            "raw_scores": dict(snapshot.scores or {}),
        }

    def prompt_node(state: ScoringState) -> dict[str, Any]:
        if state.get("error"):
            return {}
        prompt = build_prompt(
            state["model_id"],
            state.get("provider") or "",
            state.get("sources") or {},
            state.get("raw_scores") or {},
            max_chars=max_input_chars,
        )
        result = llm.with_structured_output(ScoreResult, **output_kwargs).invoke(prompt)
        return {"result": result}

    def parse_node(state: ScoringState) -> dict[str, Any]:
        if state.get("error") or state.get("result") is None:
            return {}
        result = state["result"]
        assert result is not None
        dims = {dim: _clamp(result.dims.get(dim)) for dim in DIMENSIONS}
        return {
            "result": ScoreResult(
                overall=_clamp(result.overall),
                dims=dims,
                rationale=result.rationale,
                confidence=result.confidence,
            )
        }

    def persist_node(state: ScoringState) -> dict[str, Any]:
        if state.get("error") or state.get("result") is None:
            return {}
        result = state["result"]
        assert result is not None
        # 全空结果不落库：无法打分时保留采集回落分
        if result.overall is None and all(v is None for v in result.dims.values()):
            logger.info(
                "LLM 无法从采集数据得出任何分数，保持采集回落分",
                extra={"model_id": state["model_id"]},
            )
            return {"result": None}
        repo.apply_llm_score(
            state["model_id"],
            overall=result.overall,
            dims=result.dims,
            rationale=result.rationale,
            scorer=state["scorer"],
        )
        return {}

    graph = StateGraph(ScoringState)
    graph.add_node("load", load_node)
    graph.add_node("prompt", prompt_node)
    graph.add_node("parse", parse_node)
    graph.add_node("persist", persist_node)
    graph.set_entry_point("load")
    graph.add_edge("load", "prompt")
    graph.add_edge("prompt", "parse")
    graph.add_edge("parse", "persist")
    graph.add_edge("persist", END)
    return graph.compile()


def score_snapshot(
    repo: Any,
    settings: Settings,
    *,
    model_id: str,
    llm: Any = None,
) -> bool:
    """对单个快照执行 LLM 打分；成功写库返回 True。

    provider 未注册/未配置 key 或 LLM 给出全空结果时返回 False（仅记日志）；
    LLM 调用/解析异常向上抛（任务层负责重试与兜底）。
    """
    spec = SCORER_REGISTRY.get(settings.llm_scorer_provider)
    if spec is None:
        logger.warning(
            "未知打分模型 provider", extra={"provider": settings.llm_scorer_provider}
        )
        return False
    if llm is None:
        api_key = getattr(settings, spec.api_key_attr, None)
        if not api_key:
            logger.info("打分模型未配置 key，跳过", extra={"provider": spec.provider})
            return False
        model = settings.llm_scorer_model or spec.default_model
        llm = build_chat_model(
            spec,
            model=model,
            api_key=api_key,
            timeout=settings.llm_scorer_timeout_seconds,
        )
    model = settings.llm_scorer_model or spec.default_model
    scorer = f"{spec.provider}/{model}"
    output_kwargs = (
        {"method": spec.structured_output_method}
        if spec.structured_output_method
        else {}
    )
    graph = build_scoring_graph(
        repo,
        llm,
        max_input_chars=settings.llm_scorer_max_input_chars,
        structured_output_kwargs=output_kwargs,
    )
    final: ScoringState = graph.invoke({"model_id": model_id, "scorer": scorer})
    if final.get("error"):
        logger.warning(
            "LLM 打分跳过",
            extra={"model_id": model_id, "error": final["error"]},
        )
        return False
    return final.get("result") is not None
