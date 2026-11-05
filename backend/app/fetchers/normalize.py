"""M05 通用标准化：站点原始记录 -> 仓储 DTO（纯函数，脏值返回 None 不抛异常）。

config.yaml 中的 normalize 块：

```yaml
normalize:
  defaults: {provider: openrouter}   # 标准字段缺省值（原始记录缺失时填充）
  fields:                            # 标准字段名 <- 原始字段路径（支持 a.b 嵌套）；
    model_id: id                     # 未列出的标准字段按同名恒等映射；
    input_price: pricing.prompt      # 非 DTO 核心列的映射字段写入 data JSONB
  scores:                            # model_metrics 专用：多维评分映射（维度名 <- 路径）
    intelligence: benchmarks.artificial_analysis.intelligence_index
```

主榜分回落顺序：显式 score 字段 -> intelligence -> coding -> agentic；
全部缺失时 benchmark_score=None（与真 0 分区分），score_source 记录取值来源。
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.exceptions import ConfigError
from app.repositories.dto import (
    ApiPriceRecord,
    CostRecord,
    SnapshotRecord,
    SubscriptionPlanRecord,
)

DATA_TYPES = {"model_metrics", "infrastructure_cost", "subscription_plan", "api_price"}

_NUMBER_RE = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")
_WS_RE = re.compile(r"\s+")
# 变体归并规则（canonical_model_name）
# vendor 前缀：anthropic/claude-opus-5；openrouter 的 "~" 前缀别名 id 一并识别（~openai/gpt-x-latest）
_VENDOR_OF_RE = re.compile(r"^~?([a-z0-9_.-]+)/")
_VARIANT_SUFFIX_RE = re.compile(r":[a-z][a-z0-9-]*$")  # 冒号变体后缀（:batch），版本号 :5 不剥
# 推理档位括号：(high)/(max)/(xhigh)/(high with fallback)/(high, default fallback) 等
_EFFORT_PARENS_RE = re.compile(r"\((?:high|medium|low|minimal|max|xhigh)\b[^)]*\)$")
_SEP_RE = re.compile(r"[\s_]+")

# 各数据类型参与映射的标准字段（未在 fields 声明时按同名恒等取值）
_STANDARD_FIELDS: dict[str, tuple[str, ...]] = {
    "model_metrics": ("model_id", "provider", "score"),
    "infrastructure_cost": ("cost_type", "name", "unit", "price", "region", "is_active"),
    "subscription_plan": (
        "provider",
        "plan_key",
        "plan_name",
        "monthly_price",
        "currency",
        "billing_cycle",
        "is_active",
    ),
    "api_price": (
        "model_id",
        "provider",
        "input_price",
        "output_price",
        "currency",
        "unit",
    ),
}

# 主榜分维度回落顺序（显式 score 字段优先，其次按此顺序取第一个非空维度）
_SCORE_FALLBACK_ORDER = ("intelligence", "coding", "agentic")


def parse_score(value: Any) -> Decimal | None:
    """解析榜单分数（如 "89.5 分"），脏值/负值返回 None。"""
    return _parse_non_negative_number(value)


def parse_price(value: Any) -> Decimal | None:
    """解析价格（如 "$3.00"、"¥1,234.5"），脏值/负值返回 None。"""
    return _parse_non_negative_number(value)


def canonical_model_name(value: Any) -> str | None:
    """模型名规范化（变体归并）：去 vendor 前缀、冒号变体后缀（:batch 等）、
    推理档位括号（(high with fallback) 等），空白/下划线归一为连字符，统一小写。

    版本号差异不合并（claude-opus-5 ≠ claude-opus-5.5）；独立 SKU 不剥离
    （gpt-5.1-codex-mini 的 mini 保留，只剥冒号后缀）。空值返回 None。
    """
    if not isinstance(value, str):
        return None
    name = _WS_RE.sub(" ", value.strip()).lower()
    if not name:
        return None
    name = _VENDOR_OF_RE.sub("", name, count=1).lstrip("~")
    while (stripped := _VARIANT_SUFFIX_RE.sub("", name)) != name:
        name = stripped
    name = _EFFORT_PARENS_RE.sub("", name).strip()
    name = _SEP_RE.sub("-", name)
    return name or None


def vendor_prefix(value: Any) -> str | None:
    """从带 vendor 前缀的模型 id（anthropic/claude-opus-5）取厂商名；无前缀返回 None。"""
    if not isinstance(value, str):
        return None
    match = _VENDOR_OF_RE.match(value.strip().lower())
    return match.group(1) if match else None


def normalize_records(
    raw: Any, cfg: dict, *, data_type: str | None = None
) -> tuple[list[Any], bool]:
    """把站点原始记录标准化为仓储 DTO 列表。

    raw 可以是记录列表，或 {"records": [...], "truncated": bool}（翻页被截断）。
    data_type 缺省取 cfg.data_type；调用方可按任务类型覆盖（如 api_price）。
    返回 (records, truncated)；无法构造合法 DTO 的记录被丢弃，不抛异常。
    """
    truncated = False
    items = raw
    if isinstance(raw, dict):
        items = raw.get("records") or []
        truncated = bool(raw.get("truncated", False))
    if not isinstance(items, list):
        return [], truncated

    effective_type = data_type or cfg.get("data_type")
    if effective_type not in DATA_TYPES:
        raise ConfigError(f"站点 {cfg.get('key', '?')} 数据类型非法: {effective_type!r}")

    normalize_cfg = cfg.get("normalize") or {}
    fields: dict[str, str] = dict(normalize_cfg.get("fields") or {})
    defaults: dict[str, Any] = dict(normalize_cfg.get("defaults") or {})
    scores_map: dict[str, str] = dict(normalize_cfg.get("scores") or {})

    records = []
    for item in items:
        if not isinstance(item, dict):
            continue
        record = _normalize_item(item, effective_type, fields, defaults, scores_map, cfg)
        if record is not None:
            records.append(record)
    return records, truncated


def _normalize_item(
    item: dict,
    data_type: str,
    fields: dict[str, str],
    defaults: dict[str, Any],
    scores_map: dict[str, str],
    cfg: dict,
) -> Any | None:
    values: dict[str, Any] = {}
    consumed: set[str] = set()
    for standard in _STANDARD_FIELDS[data_type]:
        path = fields.get(standard, standard)
        consumed.add(path.split(".", 1)[0])
        value = _dig(item, path)
        if value is None:
            value = defaults.get(standard)
        values[standard] = value

    # 映射里的非标准字段（如 input_price）与未消费的原始字段一并进 data JSONB
    data: dict[str, Any] = {}
    for key, path in fields.items():
        consumed.add(path.split(".", 1)[0])
        if key not in values:
            data[key] = _dig(item, path)
    for key, value in item.items():
        if key not in consumed:
            data[key] = value

    if data_type == "model_metrics":
        return _build_snapshot(values, data, cfg, scores_map, item)
    if data_type == "infrastructure_cost":
        return _build_cost(values, data, cfg)
    if data_type == "api_price":
        return _build_price(values, data, cfg)
    return _build_plan(values, data, cfg)


def _build_snapshot(
    values: dict,
    data: dict,
    cfg: dict,
    scores_map: dict[str, str],
    item: dict,
) -> SnapshotRecord | None:
    raw_model_id = _clean_str(values.get("model_id"))
    model_id = canonical_model_name(raw_model_id)
    # 厂商取值：模型 id 的 vendor 前缀（真实研发厂商）-> 记录自带 provider -> 站点 key 兜底；
    # 聚合平台（如 openrouter）不允许兜底成榜单厂商，其 config 不得声明 defaults.provider。
    # 统一小写避免同一厂商多写法（OpenAI/openai）各占一行
    provider = (
        vendor_prefix(raw_model_id)
        or _clean_str(values.get("provider"))
        or _clean_str(cfg.get("key"))
    )
    provider = provider.lower() if provider else None
    if not model_id or not provider:
        return None

    # 多维评分结构化（JSONB 存 float，None 表示该维度缺失）；维度路径原样保留在 data
    scores: dict[str, float | None] = {
        dim: (float(parsed) if (parsed := parse_score(_dig(item, path))) is not None else None)
        for dim, path in scores_map.items()
    }

    score = parse_score(values.get("score"))
    score_source: str | None = None
    raw_score = values.get("score")
    # 采集数据包一层 sources：记录该来源所属榜单域、评测的具体变体与原始记录，
    # 多来源/多域在仓储层按 model_id 合并到同一行
    domain = str(cfg.get("domain") or "general")
    source_entry: dict[str, Any] = {
        "raw_model_id": raw_model_id,
        "domain": domain,
        "record": item,
    }
    if score is not None:
        score_source = "score"
    elif raw_score is not None:
        source_entry["score_raw"] = raw_score
    if score is None:
        for dim in _SCORE_FALLBACK_ORDER:
            dim_score = scores.get(dim)
            if dim_score is not None:
                # scores 存 float（JSONB），主榜分列是 Numeric，经 str 避免浮点尾差
                score = Decimal(str(dim_score))
                score_source = dim
                break
    # 来源条目携带该源自己的分，仓储层按来源优先级跨源聚合（AA > openrouter > lmarena > aider）
    source_entry["benchmark_score"] = float(score) if score is not None else None
    source_entry["scores"] = scores
    source_entry["score_source"] = score_source
    return SnapshotRecord(
        model_id=model_id,
        provider=provider,
        domain=domain,
        benchmark_score=score,
        scores=scores,
        score_source=score_source,
        data={"sources": {str(cfg.get("key") or ""): source_entry}},
        raw_model_id=raw_model_id,
        source_key=str(cfg.get("key") or "") or None,
    )


def _build_cost(values: dict, data: dict, cfg: dict) -> CostRecord | None:
    cost_type = _clean_str(values.get("cost_type"))
    name = _clean_str(values.get("name"))
    price = parse_price(values.get("price"))
    if not cost_type or not name or price is None:
        return None
    return CostRecord(
        cost_type=cost_type,
        name=name,
        unit=_clean_str(values.get("unit")) or "unit",
        unit_price=price,
        region=_clean_str(values.get("region")) or "default",
        source=str(cfg.get("key") or "") or None,
        is_active=_is_active(values.get("is_active")),
        data=data,
    )


def _build_price(values: dict, data: dict, cfg: dict) -> ApiPriceRecord | None:
    model_id = canonical_model_name(values.get("model_id"))
    provider = _clean_str(values.get("provider")) or _clean_str(cfg.get("key"))
    if not model_id or not provider:
        return None
    input_price = parse_price(values.get("input_price"))
    output_price = parse_price(values.get("output_price"))
    if input_price is None and output_price is None:
        return None
    return ApiPriceRecord(
        model_id=model_id,
        provider=provider,
        input_price=input_price,
        output_price=output_price,
        currency=_clean_str(values.get("currency")) or "USD",
        unit=_clean_str(values.get("unit")) or "token",
        source=_clean_str(cfg.get("key")),
        data=data,
    )


def _build_plan(values: dict, data: dict, cfg: dict) -> SubscriptionPlanRecord | None:
    provider = _clean_str(values.get("provider"))
    plan_key = _clean_str(values.get("plan_key"))
    plan_name = _clean_str(values.get("plan_name"))
    price = parse_price(values.get("monthly_price"))
    if not provider or not plan_key or not plan_name or price is None:
        return None
    return SubscriptionPlanRecord(
        provider=provider,
        plan_key=plan_key,
        plan_name=plan_name,
        monthly_price=price,
        currency=_clean_str(values.get("currency")) or "USD",
        billing_cycle=_clean_str(values.get("billing_cycle")) or "monthly",
        is_active=_is_active(values.get("is_active")),
        source="fetch",
        data=data,
    )


def _parse_non_negative_number(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float | Decimal):
        try:
            number = Decimal(str(value))
        except InvalidOperation:
            return None
        return number if number >= 0 else None
    if not isinstance(value, str):
        return None
    text = value.strip()
    if text.startswith("-"):
        return None
    match = _NUMBER_RE.search(text)
    if not match:
        return None
    try:
        number = Decimal(match.group(0).replace(",", ""))
    except InvalidOperation:
        return None
    return number if number >= 0 else None


def _dig(item: dict, path: str) -> Any:
    """按 a.b.c 路径取嵌套值，路径缺失返回 None。"""
    value: Any = item
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _clean_str(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    return value.strip() or None


def _is_active(value: Any) -> bool:
    """缺省视为活跃；仅显式 False/0/"false" 类值才判停采。"""
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip().lower() not in {"false", "0", "no", "inactive"}
    return bool(value)
