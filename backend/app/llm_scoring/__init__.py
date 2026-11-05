"""LLM 离线打分：采集成功后由大模型基于采集数据为各维度与主综合分打分。"""

from app.llm_scoring.graph import ScoreResult, score_snapshot

__all__ = ["ScoreResult", "score_snapshot"]
