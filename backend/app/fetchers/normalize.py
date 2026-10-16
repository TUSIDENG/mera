"""M05 通用标准化：站点原始记录 -> 仓储 DTO（纯函数，脏值返回 None 不抛异常）。

config.yaml 中的 normalize 块：

```yaml
normalize:
  defaults: {provider: openrouter}   # 标准字段缺省值（原始记录缺失时填充）
  fields:                            # 标准字段名 <- 原始字段路径（支持 a.b 嵌套）；
    model_id: id                     # 未列出的标准字段按同名恒等映射；
    input_price: pricing.prompt      # 非 DTO 核心列的映射字段写入 data JSONB
```
"""

from __future__ import annotations

import re
from decimal import Decimal, InvalidOperation
from typing import Any

from app.core.exceptions import ConfigError
from app.repositories.dto import CostRecord, SnapshotRecord, SubscriptionPlanRecord

DATA_TYPES = {"model_metrics", "infrastructure_cost", "subscription_plan"}

_NUMBER_RE = re.compile(r"-?\d+(?:,\d{3})*(?:\.\d+)?")
_WS_RE = re.compile(r"\s+")

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
}


def parse_score(value: Any) -> Decimal | None:
    """解析榜单分数（如 "89.5 分"），脏值/负值返回 None。"""
    return _parse_non_negative_number(value)


def parse_price(value: Any) -> Decimal | None:
    """解析价格（如 "$3.00"、"¥1,234.5"），脏值/负值返回 None。"""
    return _parse_non_negative_number(value)


def canonical_model_name(value: Any) -> str | None:
    """模型名规范化：去首尾空白、压缩内部空白、统一小写；空值返回 None。"""
    if not isinstance(value, str):
        return None
    name = _WS_RE.sub(" ", value.strip()).lower()
    return name or None


def normalize_records(raw: Any, cfg: dict) -> tuple[list[Any], bool]:
    """把站点原始记录标准化为仓储 DTO 列表。

    raw 可以是记录列表，或 {"records": [...], "truncated": bool}（翻页被截断）。
    返回 (records, truncated)；无法构造合法 DTO 的记录被丢弃，不抛异常。
    """
    truncated = False
    items = raw
    if isinstance(raw, dict):
        items = raw.get("records") or []
        truncated = bool(raw.get("truncated", False))
    if not isinstance(items, list):
        return [], truncated

    data_type = cfg.get("data_type")
    if data_type not in DATA_TYPES:
        raise ConfigError(f"站点 {cfg.get('key', '?')} 数据类型非法: {data_type!r}")

    normalize_cfg = cfg.get("normalize") or {}
    fields: dict[str, str] = dict(normalize_cfg.get("fields") or {})
    defaults: dict[str, Any] = dict(normalize_cfg.get("defaults") or {})

    records = []
    for item in items:
        if not isinstance(item, dict):
            continue
        record = _normalize_item(item, data_type, fields, defaults, cfg)
        if record is not None:
            records.append(record)
    return records, truncated


def _normalize_item(
    item: dict,
    data_type: str,
    fields: dict[str, str],
    defaults: dict[str, Any],
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
        return _build_snapshot(values, data, cfg)
    if data_type == "infrastructure_cost":
        return _build_cost(values, data, cfg)
    return _build_plan(values, data, cfg)


def _build_snapshot(values: dict, data: dict, cfg: dict) -> SnapshotRecord | None:
    model_id = canonical_model_name(values.get("model_id"))
    # 单来源站点 provider 缺失时回落站点 key（如 aider_leaderboard）
    provider = _clean_str(values.get("provider")) or _clean_str(cfg.get("key"))
    if not model_id or not provider:
        return None
    score = parse_score(values.get("score"))
    raw_score = values.get("score")
    if raw_score is not None and score is None:
        data.setdefault("score_raw", raw_score)
    return SnapshotRecord(
        model_id=model_id,
        provider=provider,
        domain=str(cfg.get("domain") or "general"),
        benchmark_score=score if score is not None else Decimal(0),
        data=data,
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
