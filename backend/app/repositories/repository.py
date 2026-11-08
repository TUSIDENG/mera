"""M02 数据访问仓储。"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ColumnElement, and_, asc, func, select, true
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import InvalidTransition
from app.db.enums import FetchTaskStatus
from app.db.models import (
    FetchRecord,
    FetchTask,
    InfrastructureCost,
    ModelApiPrice,
    ModelSnapshot,
    SubscriptionPlan,
    UserEvaluation,
)
from app.db.state_machine import ensure_terminal_rules, ensure_transition
from app.repositories.dto import (
    ApiPriceRecord,
    CostRecord,
    CreateTaskParams,
    SnapshotRecord,
    SubscriptionPlanRecord,
)


def _business_key(record: Any) -> tuple[Any, ...]:
    """各类记录的业务键（与唯一约束一一对应），用于批量 upsert 前去重。"""
    if isinstance(record, SnapshotRecord):
        # 一个模型一行：域/来源差异在 data.sources 内合并
        return (record.model_id,)
    if isinstance(record, ApiPriceRecord):
        return (record.model_id, record.provider)
    if isinstance(record, CostRecord):
        return (record.cost_type, record.name, record.region)
    if isinstance(record, SubscriptionPlanRecord):
        return (record.provider, record.plan_key, record.billing_cycle)
    raise TypeError(f"未知记录类型: {type(record)!r}")


def _dedupe_for_upsert(records: Sequence[Any]) -> list[Any]:
    """PG 批量 ON CONFLICT 不允许同命令两次影响同一行：同业务键去重，后写覆盖先写。"""
    seen: dict[tuple[Any, ...], Any] = {}
    for record in records:
        seen[_business_key(record)] = record
    return list(seen.values())


# model_snapshots 的 ORM 列（DTO 中 raw_model_id/source_key/domain 仅用于留痕与溯源）
_SNAPSHOT_ORM_FIELDS = (
    "model_id",
    "provider",
    "benchmark_score",
    "scores",
    "score_source",
    "data",
)

# 采集源优先级（数值越小越权威）：主榜分与各维度分统一按此顺序取第一个非空来源。
# openrouter 附带的是 Artificial Analysis 指数（与 AA 站点同源），故排在 AA 之后。
# lmarena_* 多领域 variant 同源同级，前缀匹配到同一优先级。
_SOURCE_PRIORITY = {
    "artificial_analysis": 0,
    "openrouter": 1,
    "lmarena": 2,
    "aider_leaderboard": 3,
}
_DEFAULT_SOURCE_PRIORITY = 9

# 这些 provider 值只是采集站点兜底（或旧版站点默认值），不代表真实厂商：
# 一旦后续采集能推断出真实厂商，应覆盖它们，避免同一模型一直挂在站点名下。
# lmarena_* variant key（vendor 缺失时 cfg.key 回落）也属站点兜底。
_SITE_PROVIDERS = frozenset(
    {"aider", "aider_leaderboard", "lmarena", "artificial_analysis", "openrouter"}
)


def _source_priority(source_key: str) -> int:
    """取来源优先级：精确匹配优先，否则按 lmarena_* 等前缀回落到父级优先级。"""
    if source_key in _SOURCE_PRIORITY:
        return _SOURCE_PRIORITY[source_key]
    for prefix, priority in _SOURCE_PRIORITY.items():
        if source_key.startswith(f"{prefix}_"):
            return priority
    return _DEFAULT_SOURCE_PRIORITY


def _is_site_provider(provider: str | None) -> bool:
    """判断 provider 是否为站点兜底值（含 lmarena_* variant）。"""
    if not provider:
        return False
    if provider in _SITE_PROVIDERS:
        return True
    return any(provider.startswith(f"{p}_") for p in _SITE_PROVIDERS)


def _prefer_provider(existing: str | None, incoming: str | None) -> str | None:
    """合并厂商：真实厂商优先，站点兜底值可被覆盖。"""
    if not incoming:
        return existing
    if not existing or _is_site_provider(existing):
        return incoming
    return existing


def _snapshot_orm_dict(record: SnapshotRecord) -> dict[str, Any]:
    return {k: v for k, v in record.__dict__.items() if k in _SNAPSHOT_ORM_FIELDS}


def _snapshot_payload(record: SnapshotRecord) -> dict[str, Any]:
    """fetch_records.record 落库载荷（Decimal 转 float 以适配 JSONB）。"""
    payload = _snapshot_orm_dict(record)
    # 域不再占列，但留痕载荷保留该字段便于回溯「这条记录来自哪个榜」
    payload["domain"] = record.domain
    if payload["benchmark_score"] is not None:
        payload["benchmark_score"] = float(payload["benchmark_score"])
    return payload


def _merge_source_entry(old: Any, new: Any) -> dict[str, Any]:
    """同源重采合并条目：覆盖原始记录，但维度分中 null 不覆盖旧值（与行级语义一致）。"""
    if not isinstance(old, dict):
        return new
    if not isinstance(new, dict):
        return old
    merged = {**old, **new}
    old_scores = old.get("scores") or {}
    new_scores = new.get("scores") or {}
    if old_scores or new_scores:
        merged["scores"] = {
            **old_scores,
            **{dim: value for dim, value in new_scores.items() if value is not None},
        }
    if merged.get("benchmark_score") is None:
        merged["benchmark_score"] = old.get("benchmark_score")
    return merged


def _merge_data(old: dict[str, Any] | None, new: dict[str, Any] | None) -> dict[str, Any]:
    """data 合并：顶层浅合并，sources 层级按键合并（多来源/多域共存，同源重采覆盖）。"""
    old = old or {}
    new = new or {}
    merged = {**old, **new}
    old_sources = old.get("sources")
    new_sources = new.get("sources")
    if isinstance(old_sources, dict) or isinstance(new_sources, dict):
        old_sources = old_sources if isinstance(old_sources, dict) else {}
        new_sources = new_sources if isinstance(new_sources, dict) else {}
        merged["sources"] = {
            key: _merge_source_entry(old_sources.get(key), value)
            for key, value in {**old_sources, **new_sources}.items()
        }
    return merged


def _aggregate_from_sources(
    data: dict[str, Any] | None,
) -> tuple[Decimal | None, dict[str, float], str | None]:
    """按来源优先级从 data.sources 聚合主榜分与维度分（纯函数）。

    每个维度取优先级最高来源的非空值；主榜分取优先级最高来源的非空分。
    返回 (主榜分, 维度分, 主榜分来源标签)。
    """
    sources = (data or {}).get("sources") or {}
    ordered = sorted(
        sources.items(),
        key=lambda kv: _source_priority(kv[0]),
    )
    dims: dict[str, float] = {}
    benchmark: Decimal | None = None
    label: str | None = None
    for key, entry in ordered:
        if not isinstance(entry, dict):
            continue
        for dim, value in (entry.get("scores") or {}).items():
            if value is not None and dim not in dims:
                dims[dim] = value
        if benchmark is None and entry.get("benchmark_score") is not None:
            benchmark = Decimal(str(entry["benchmark_score"]))
            own = entry.get("score_source")
            label = f"{key}:{own}" if own else key
    return benchmark, dims, label


class Repository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_snapshots(self, records: Sequence[SnapshotRecord]) -> int:
        if not records:
            return 0
        # 一个模型一行：同批次内不同来源的记录按 model_id 合并，各自 sources 条目保留
        for record in records:
            existing = self.session.scalar(
                select(ModelSnapshot).where(ModelSnapshot.model_id == record.model_id)
            )
            if existing is None:
                self.session.add(ModelSnapshot(**_snapshot_orm_dict(record)))
            else:
                existing.provider = _prefer_provider(existing.provider, record.provider)
                existing.data = _merge_data(existing.data, record.data)
        # 合并 sources 后按来源优先级重算主榜分与维度分（LLM 打分的行不覆盖）
        self._recompute_snapshot_scores({record.model_id for record in records})
        return len(records)

    def _recompute_snapshot_scores(self, model_ids: set[str]) -> None:
        """合并后按来源优先级重算展示分：LLM 已打分的行保持 LLM 分不动。

        sources 内无分数信息时（历史行/无分来源）保留原值，避免把已有分数抹掉。
        """
        rows = self.session.scalars(
            select(ModelSnapshot)
            .where(ModelSnapshot.model_id.in_(sorted(model_ids)))
            .execution_options(populate_existing=True)
        ).all()
        for row in rows:
            if (row.score_source or "").startswith("llm:"):
                continue
            benchmark, scores, label = _aggregate_from_sources(row.data)
            if benchmark is not None:
                row.benchmark_score = benchmark
            if scores:
                row.scores = scores
            if label is not None:
                row.score_source = label

    def insert_fetch_records(
        self, task_id: uuid.UUID, records: Sequence[SnapshotRecord]
    ) -> int:
        """采集留痕（append-only）：每条标准化记录一行，与 snapshot upsert 同事务。"""
        rows = [
            FetchRecord(
                task_id=task_id,
                source_key=record.source_key or "",
                model_id=record.model_id,
                raw_model_id=record.raw_model_id,
                record=_snapshot_payload(record),
            )
            for record in records
        ]
        self.session.add_all(rows)
        self.session.flush()
        return len(rows)

    def get_snapshot(self, model_id: str) -> ModelSnapshot | None:
        stmt = select(ModelSnapshot).where(ModelSnapshot.model_id == model_id)
        return self.session.scalar(stmt)

    def apply_llm_score(
        self,
        model_id: str,
        *,
        overall: float | None,
        dims: dict[str, float | None],
        rationale: str,
        scorer: str,
    ) -> None:
        """写入 LLM 打分结果：scores/dims + 主榜分 + score_source=llm:<scorer>，
        打分理由留痕在 data.llm_score；采集到的原始维度分仍保留在 data.sources。"""
        snapshot = self.get_snapshot(model_id)
        if snapshot is None:
            raise ValueError(f"模型快照不存在: {model_id}")
        snapshot.scores = dims
        snapshot.benchmark_score = overall
        snapshot.score_source = f"llm:{scorer}"
        data = dict(snapshot.data or {})
        data["llm_score"] = {
            "overall": overall,
            "dims": dims,
            "rationale": rationale,
            "scorer": scorer,
            "scored_at": datetime.now(UTC).isoformat(),
        }
        snapshot.data = data
        self.session.flush()

    def list_fetch_records_by_model(
        self, model_id: str, *, limit: int, offset: int
    ) -> tuple[list[FetchRecord], int]:
        condition = FetchRecord.model_id == model_id
        total = self.session.scalar(
            select(func.count()).select_from(FetchRecord).where(condition)
        )
        stmt = (
            select(FetchRecord)
            .where(condition)
            .order_by(FetchRecord.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(stmt).all()), int(total or 0)

    def list_fetch_records_by_task(
        self, task_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[FetchRecord], int]:
        condition = FetchRecord.task_id == task_id
        total = self.session.scalar(
            select(func.count()).select_from(FetchRecord).where(condition)
        )
        stmt = (
            select(FetchRecord)
            .where(condition)
            .order_by(FetchRecord.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(stmt).all()), int(total or 0)

    def fetch_record_model_ids_by_task(self, task_id: uuid.UUID) -> list[str]:
        """本次任务采到的去重 model_id，用于触发 LLM 离线打分。"""
        stmt = (
            select(FetchRecord.model_id)
            .where(FetchRecord.task_id == task_id)
            .distinct()
        )
        return [row[0] for row in self.session.execute(stmt)]

    def upsert_prices(self, records: Sequence[ApiPriceRecord]) -> int:
        """API 按量价格 upsert，业务键 (model_id, provider)。"""
        if not records:
            return 0
        if self.session.bind is not None and self.session.bind.dialect.name == "postgresql":
            self._upsert_prices_pg(records)
        else:
            self._upsert_prices_generic(records)
        return len(records)

    def _upsert_prices_pg(self, records: Sequence[ApiPriceRecord]) -> None:
        values = [record.__dict__.copy() for record in _dedupe_for_upsert(records)]
        stmt = pg_insert(ModelApiPrice).values(values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_model_api_price",
            set_={
                "input_price": stmt.excluded.input_price,
                "output_price": stmt.excluded.output_price,
                "currency": stmt.excluded.currency,
                "unit": stmt.excluded.unit,
                "source": stmt.excluded.source,
                "is_active": stmt.excluded.is_active,
                "data": stmt.excluded.data,
                "updated_at": func.now(),
            },
        )
        self.session.execute(stmt)

    def _upsert_prices_generic(self, records: Sequence[ApiPriceRecord]) -> None:
        for record in records:
            existing = self.session.scalar(
                select(ModelApiPrice).where(
                    and_(
                        ModelApiPrice.model_id == record.model_id,
                        ModelApiPrice.provider == record.provider,
                    )
                )
            )
            if existing is None:
                self.session.add(ModelApiPrice(**record.__dict__))
            else:
                existing.input_price = record.input_price
                existing.output_price = record.output_price
                existing.currency = record.currency
                existing.unit = record.unit
                existing.source = record.source
                existing.is_active = record.is_active
                existing.data = record.data

    def latest_prices(self) -> list[ModelApiPrice]:
        """全部活跃 API 价格（分析层按 (model_id, provider) 关联）。"""
        stmt = select(ModelApiPrice).where(ModelApiPrice.is_active.is_(True))
        return list(self.session.scalars(stmt))

    def get_price(self, model_id: str, provider: str) -> ModelApiPrice | None:
        stmt = select(ModelApiPrice).where(
            and_(
                ModelApiPrice.model_id == model_id,
                ModelApiPrice.provider == provider,
            )
        )
        return self.session.scalar(stmt)

    def list_prices(
        self,
        *,
        provider: str | None = None,
        model_id: str | None = None,
        active_only: bool = False,
        limit: int,
        offset: int,
    ) -> tuple[list[ModelApiPrice], int]:
        condition: ColumnElement[bool] = true()
        if provider:
            condition = and_(condition, ModelApiPrice.provider == provider)
        if model_id:
            condition = and_(condition, ModelApiPrice.model_id == model_id)
        if active_only:
            condition = and_(condition, ModelApiPrice.is_active.is_(True))
        total = self.session.scalar(
            select(func.count()).select_from(ModelApiPrice).where(condition)
        )
        stmt = (
            select(ModelApiPrice)
            .where(condition)
            .order_by(asc(ModelApiPrice.provider), asc(ModelApiPrice.model_id))
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(stmt).all()), int(total or 0)

    def upsert_costs(self, records: Sequence[CostRecord]) -> int:
        if not records:
            return 0
        if self.session.bind is not None and self.session.bind.dialect.name == "postgresql":
            self._upsert_costs_pg(records)
        else:
            self._upsert_costs_generic(records)
        return len(records)

    def _upsert_costs_pg(self, records: Sequence[CostRecord]) -> None:
        values = [record.__dict__.copy() for record in _dedupe_for_upsert(records)]
        stmt = pg_insert(InfrastructureCost).values(values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_infra_cost",
            set_={
                "unit": stmt.excluded.unit,
                "unit_price": stmt.excluded.unit_price,
                "source": stmt.excluded.source,
                "is_active": stmt.excluded.is_active,
                "data": stmt.excluded.data,
                "updated_at": func.now(),
            },
        )
        self.session.execute(stmt)

    def _upsert_costs_generic(self, records: Sequence[CostRecord]) -> None:
        for record in records:
            existing = self.session.scalar(
                select(InfrastructureCost).where(
                    and_(
                        InfrastructureCost.cost_type == record.cost_type,
                        InfrastructureCost.name == record.name,
                        InfrastructureCost.region == record.region,
                    )
                )
            )
            if existing is None:
                self.session.add(InfrastructureCost(**record.__dict__))
            else:
                existing.unit = record.unit
                existing.unit_price = record.unit_price
                existing.source = record.source
                existing.is_active = record.is_active
                existing.data = record.data

    def upsert_subscription_plans(self, records: Sequence[SubscriptionPlanRecord]) -> int:
        if not records:
            return 0
        if self.session.bind is not None and self.session.bind.dialect.name == "postgresql":
            self._upsert_plans_pg(records)
        else:
            self._upsert_plans_generic(records)
        return len(records)

    def _upsert_plans_pg(self, records: Sequence[SubscriptionPlanRecord]) -> None:
        values = [record.__dict__.copy() for record in _dedupe_for_upsert(records)]
        stmt = pg_insert(SubscriptionPlan).values(values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_subscription_plan",
            set_={
                "plan_name": stmt.excluded.plan_name,
                "monthly_price": stmt.excluded.monthly_price,
                "currency": stmt.excluded.currency,
                "is_active": stmt.excluded.is_active,
                "source": stmt.excluded.source,
                "data": stmt.excluded.data,
                "updated_at": func.now(),
            },
        )
        self.session.execute(stmt)

    def _upsert_plans_generic(self, records: Sequence[SubscriptionPlanRecord]) -> None:
        for record in records:
            existing = self.session.scalar(
                select(SubscriptionPlan).where(
                    and_(
                        SubscriptionPlan.provider == record.provider,
                        SubscriptionPlan.plan_key == record.plan_key,
                        SubscriptionPlan.billing_cycle == record.billing_cycle,
                    )
                )
            )
            if existing is None:
                self.session.add(SubscriptionPlan(**record.__dict__))
            else:
                existing.plan_name = record.plan_name
                existing.monthly_price = record.monthly_price
                existing.currency = record.currency
                existing.is_active = record.is_active
                existing.source = record.source
                existing.data = record.data

    def create_task(self, params: CreateTaskParams) -> FetchTask:
        """创建任务；存在相同业务键的进行中任务时复用该任务。"""
        domain_condition = (
            FetchTask.domain.is_(None)
            if params.domain is None
            else FetchTask.domain == params.domain
        )
        existing_stmt = select(FetchTask).where(
            and_(
                FetchTask.task_type == params.task_type,
                FetchTask.source_key == params.source_key,
                domain_condition,
                FetchTask.status.in_(
                    [FetchTaskStatus.PENDING.value, FetchTaskStatus.RUNNING.value]
                ),
            )
        )
        existing = self.session.scalar(existing_stmt)
        if existing is not None:
            return existing

        task = FetchTask(
            task_type=params.task_type,
            source_key=params.source_key,
            domain=params.domain,
            triggered_by=params.triggered_by,
            auto_start=params.auto_start,
            data=params.data,
        )
        self.session.add(task)
        try:
            self.session.flush()
        except IntegrityError:
            self.session.rollback()
            existing = self.session.scalar(existing_stmt)
            if existing is None:
                raise
            return existing
        return task

    def get_task(self, task_id: uuid.UUID) -> FetchTask | None:
        return self.session.get(FetchTask, task_id)

    def mark_running(self, task_id: uuid.UUID) -> FetchTask:
        return self._transition(task_id, FetchTaskStatus.RUNNING.value)

    def mark_retry_pending(
        self,
        task_id: uuid.UUID,
        *,
        error_message: str | None = None,
    ) -> FetchTask:
        task = self._transition(task_id, FetchTaskStatus.PENDING.value)
        task.error_message = error_message
        return task

    def bump_attempt(self, task_id: uuid.UUID) -> FetchTask:
        task = self._require_task(task_id)
        task.attempt_count += 1
        self.session.flush()
        return task

    def mark_succeeded(
        self,
        task_id: uuid.UUID,
        *,
        strategy: str,
        hit_count: int,
        min_hits: int = 1,
    ) -> FetchTask:
        task = self._require_task(task_id)
        ensure_terminal_rules(
            task.status,
            FetchTaskStatus.SUCCEEDED.value,
            hit_count=hit_count,
            attempt_count=task.attempt_count,
        )
        if hit_count < min_hits:
            raise InvalidTransition(f"succeeded 要求 hit_count >= {min_hits}")
        return self._set_terminal(
            task,
            FetchTaskStatus.SUCCEEDED.value,
            strategy=strategy,
            hit_count=hit_count,
        )

    def mark_partial_succeeded(
        self,
        task_id: uuid.UUID,
        *,
        strategy: str,
        hit_count: int,
    ) -> FetchTask:
        task = self._require_task(task_id)
        ensure_terminal_rules(
            task.status,
            FetchTaskStatus.PARTIAL_SUCCEEDED.value,
            hit_count=hit_count,
            attempt_count=task.attempt_count,
        )
        return self._set_terminal(
            task,
            FetchTaskStatus.PARTIAL_SUCCEEDED.value,
            strategy=strategy,
            hit_count=hit_count,
        )

    def mark_failed_exhausted(
        self,
        task_id: uuid.UUID,
        *,
        error_message: str | None = None,
    ) -> FetchTask:
        task = self._require_task(task_id)
        ensure_terminal_rules(
            task.status,
            FetchTaskStatus.FAILED_EXHAUSTED.value,
            hit_count=task.hit_count,
            attempt_count=task.attempt_count,
        )
        return self._set_terminal(
            task,
            FetchTaskStatus.FAILED_EXHAUSTED.value,
            strategy=task.fetch_strategy,
            hit_count=0,
            error_message=error_message,
        )

    def mark_captcha_pending(self, task_id: uuid.UUID) -> FetchTask:
        return self._transition(task_id, FetchTaskStatus.CAPTCHA_PENDING.value)

    def latest_snapshots(self) -> list[ModelSnapshot]:
        stmt = select(ModelSnapshot).order_by(
            ModelSnapshot.benchmark_score.desc().nulls_last(), asc(ModelSnapshot.model_id)
        )
        return list(self.session.scalars(stmt).all())

    def cheapest_active_plan(self, provider: str) -> SubscriptionPlan | None:
        stmt = (
            select(SubscriptionPlan)
            .where(
                and_(
                    SubscriptionPlan.provider == provider,
                    SubscriptionPlan.is_active.is_(True),
                )
            )
            .order_by(SubscriptionPlan.monthly_price.asc(), asc(SubscriptionPlan.plan_key))
            .limit(1)
        )
        return self.session.scalar(stmt)

    # --- M04 API 查询扩展 ---

    def list_snapshots(
        self, *, limit: int, offset: int
    ) -> tuple[list[ModelSnapshot], int]:
        total = self.session.scalar(select(func.count()).select_from(ModelSnapshot))
        stmt = (
            select(ModelSnapshot)
            .order_by(
                ModelSnapshot.benchmark_score.desc().nulls_last(),
                asc(ModelSnapshot.model_id),
            )
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(stmt).all()), int(total or 0)

    def snapshots_by_model(self, model_id: str) -> list[ModelSnapshot]:
        stmt = select(ModelSnapshot).where(ModelSnapshot.model_id == model_id)
        return list(self.session.scalars(stmt).all())

    def list_tasks(
        self, *, status: str | None, limit: int, offset: int
    ) -> tuple[list[FetchTask], int]:
        condition = FetchTask.status == status if status else true()
        total = self.session.scalar(
            select(func.count()).select_from(FetchTask).where(condition)
        )
        stmt = (
            select(FetchTask)
            .where(condition)
            .order_by(FetchTask.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(stmt).all()), int(total or 0)

    def list_plans(
        self, *, provider: str | None, active_only: bool, limit: int, offset: int
    ) -> tuple[list[SubscriptionPlan], int]:
        condition: ColumnElement[bool] = true()
        if provider:
            condition = and_(condition, SubscriptionPlan.provider == provider)
        if active_only:
            condition = and_(condition, SubscriptionPlan.is_active.is_(True))
        total = self.session.scalar(
            select(func.count()).select_from(SubscriptionPlan).where(condition)
        )
        stmt = (
            select(SubscriptionPlan)
            .where(condition)
            .order_by(asc(SubscriptionPlan.provider), asc(SubscriptionPlan.plan_key))
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(stmt).all()), int(total or 0)

    def get_plan(
        self, provider: str, plan_key: str, billing_cycle: str
    ) -> SubscriptionPlan | None:
        stmt = select(SubscriptionPlan).where(
            and_(
                SubscriptionPlan.provider == provider,
                SubscriptionPlan.plan_key == plan_key,
                SubscriptionPlan.billing_cycle == billing_cycle,
            )
        )
        return self.session.scalar(stmt)

    def list_costs(
        self, *, cost_type: str | None, limit: int, offset: int
    ) -> tuple[list[InfrastructureCost], int]:
        condition = (
            InfrastructureCost.cost_type == cost_type if cost_type else true()
        )
        total = self.session.scalar(
            select(func.count()).select_from(InfrastructureCost).where(condition)
        )
        stmt = (
            select(InfrastructureCost)
            .where(condition)
            .order_by(asc(InfrastructureCost.cost_type), asc(InfrastructureCost.name))
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(stmt).all()), int(total or 0)

    def get_cost(
        self, cost_type: str, name: str, region: str
    ) -> InfrastructureCost | None:
        stmt = select(InfrastructureCost).where(
            and_(
                InfrastructureCost.cost_type == cost_type,
                InfrastructureCost.name == name,
                InfrastructureCost.region == region,
            )
        )
        return self.session.scalar(stmt)

    def create_evaluation(
        self,
        *,
        org_id: str,
        user_id: str,
        domain: str,
        snapshot_used_ids: list[uuid.UUID],
        data: dict,
        fetch_task_id: uuid.UUID | None = None,
    ) -> UserEvaluation:
        evaluation = UserEvaluation(
            org_id=org_id,
            user_id=user_id,
            domain=domain,
            snapshot_used_ids=snapshot_used_ids,
            data=data,
            fetch_task_id=fetch_task_id,
        )
        self.session.add(evaluation)
        self.session.flush()
        return evaluation

    def list_evaluations(
        self, *, user_id: str, limit: int, offset: int
    ) -> tuple[list[UserEvaluation], int]:
        condition = UserEvaluation.user_id == user_id
        total = self.session.scalar(
            select(func.count()).select_from(UserEvaluation).where(condition)
        )
        stmt = (
            select(UserEvaluation)
            .where(condition)
            .order_by(UserEvaluation.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(stmt).all()), int(total or 0)

    def _transition(self, task_id: uuid.UUID, target: str) -> FetchTask:
        task = self._require_task(task_id)
        ensure_transition(task.status, target)
        task.status = target
        self.session.flush()
        return task

    def _set_terminal(
        self,
        task: FetchTask,
        target: str,
        *,
        strategy: str | None,
        hit_count: int,
        error_message: str | None = None,
    ) -> FetchTask:
        ensure_transition(task.status, target)
        task.status = target
        task.fetch_strategy = strategy
        task.hit_count = hit_count
        task.error_message = error_message
        self.session.flush()
        return task

    def _require_task(self, task_id: uuid.UUID) -> FetchTask:
        task = self.session.get(FetchTask, task_id)
        if task is None:
            raise ValueError(f"采集任务不存在: {task_id}")
        return task
