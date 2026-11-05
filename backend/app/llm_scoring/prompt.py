"""LLM 打分提示词：基于多平台采集数据为各能力维度与主综合分打分。"""

from __future__ import annotations

import json
from typing import Any

# 打分维度（确实无法从采集数据得出的维度输出 null，列表显示 -）
DIMENSIONS = ("intelligence", "coding", "agentic", "long_context", "image", "video")

_RUBRIC = """你是大模型评测专家。根据给出的多平台采集数据，为模型的各能力维度打分（0-100）：
- intelligence: 综合智能（推理、知识、数学等）
- coding: 代码生成与软件工程能力
- agentic: 工具调用与智能体任务能力
- long_context: 长上下文理解与长文档处理能力（可依据采集到的上下文窗口与相关评测）
- image: 图像生成能力
- video: 视频生成能力
并给出 overall 主综合分（0-100）。

规则：
1. 只能基于提供的采集数据推断，结合采集到的原始维度分；确实无法从数据得出的维度输出 null。
2. overall 必须尽量给出：任一维度有原始分或数据可推断时综合评定；完全无可用数据时才输出 null。
3. 分数为 0-100 的数值，保留两位小数。
4. rationale 用中文简要说明打分依据（引用关键采集数据）。"""


def build_prompt(
    model_id: str,
    provider: str,
    sources: dict[str, Any],
    raw_scores: dict[str, Any],
    *,
    max_chars: int,
) -> str:
    """组装打分提示词；采集数据 JSON 超长时截断。

    一个模型可能同时来自多个榜单（sources 内各条目自带 domain），
    提示词按来源列出，避免把不同榜单口径混为单一领域。
    """
    payload = json.dumps(sources, ensure_ascii=False, default=str)
    if len(payload) > max_chars:
        payload = payload[:max_chars] + "...(truncated)"
    origins = ", ".join(
        f"{key}({entry.get('domain', '-')})"
        for key, entry in sources.items()
        if isinstance(entry, dict)
    )
    return (
        f"{_RUBRIC}\n\n"
        f"模型: {model_id}\n"
        f"厂商: {provider}\n"
        f"数据来源(平台/榜单域): {origins or '-'}\n"
        f"采集到的原始维度分: {json.dumps(raw_scores, ensure_ascii=False, default=str)}\n"
        f"各平台采集数据:\n{payload}"
    )
