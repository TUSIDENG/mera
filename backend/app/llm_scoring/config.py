"""打分模型注册表：provider -> 默认模型 / key 配置 / chat 模型工厂。

deepseek/chatgpt/openrouter 均为 OpenAI 兼容端点（langchain-openai + base_url），
gemini 走 langchain-google-genai；key 一律从 Settings（环境变量）注入，禁止写入仓库。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ScorerSpec:
    provider: str
    default_model: str
    # Settings 上的 API key 属性名
    api_key_attr: str
    # OpenAI 兼容端点；None 表示官方默认端点
    base_url: str | None = None
    family: str = "openai"  # openai / gemini
    # with_structured_output 的 method；None 用 langchain 默认（json_schema）。
    # deepseek 端点不支持 response_format=json_schema，需退化为 function_calling。
    structured_output_method: str | None = None


SCORER_REGISTRY: dict[str, ScorerSpec] = {
    "deepseek": ScorerSpec(
        provider="deepseek",
        default_model="deepseek-chat",
        api_key_attr="deepseek_api_key",
        base_url="https://api.deepseek.com/v1",
        structured_output_method="function_calling",
    ),
    "chatgpt": ScorerSpec(
        provider="chatgpt",
        default_model="gpt-4o-mini",
        api_key_attr="chatgpt_api_key",
    ),
    "openrouter": ScorerSpec(
        provider="openrouter",
        default_model="openai/gpt-4o-mini",
        api_key_attr="openrouter_api_key",
        base_url="https://openrouter.ai/api/v1",
    ),
    "gemini": ScorerSpec(
        provider="gemini",
        default_model="gemini-2.0-flash",
        api_key_attr="gemini_api_key",
        family="gemini",
    ),
}


def build_chat_model(
    spec: ScorerSpec, *, model: str, api_key: str, timeout: int
) -> Any:
    """按注册表构造 chat 模型；延迟导入以便未安装对应 SDK 时不影响其他 provider。"""
    if spec.family == "gemini":
        from langchain_google_genai import ChatGoogleGenerativeAI

        return ChatGoogleGenerativeAI(
            model=model, google_api_key=api_key, timeout=timeout
        )
    from langchain_openai import ChatOpenAI

    kwargs: dict[str, Any] = {"model": model, "api_key": api_key, "timeout": timeout}
    if spec.base_url:
        kwargs["base_url"] = spec.base_url
    return ChatOpenAI(**kwargs)
