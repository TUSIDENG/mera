"""M02 数据访问仓储。"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from sqlalchemy import ColumnElement, and_, asc, func, select, true
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import InvalidTransition
from app.db.enums import FetchTaskStatus
from app.db.models import (
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
        return (record.model_id, record.domain)
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


class Repository:
    def __init__(self, session: Session) -> None:
        self.session = session

    def upsert_snapshots(self, records: Sequence[SnapshotRecord]) -> int:
        if not records:
            return 0
        if self.session.bind is not None and self.session.bind.dialect.name == "postgresql":
            self._upsert_snapshots_pg(records)
        else:
            self._upsert_snapshots_generic(records)
        return len(records)

    def _upsert_snapshots_pg(self, records: Sequence[SnapshotRecord]) -> None:
        values = [record.__dict__.copy() for record in _dedupe_for_upsert(records)]
        stmt = pg_insert(ModelSnapshot).values(values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_model_snapshot",
            set_={
                "provider": stmt.excluded.provider,
                "benchmark_score": stmt.excluded.benchmark_score,
                "scores": stmt.excluded.scores,
                "score_source": stmt.excluded.score_source,
                "data": stmt.excluded.data,
                "updated_at": func.now(),
            },
        )
        self.session.execute(stmt)

    def _upsert_snapshots_generic(self, records: Sequence[SnapshotRecord]) -> None:
        for record in records:
            existing = self.session.scalar(
                select(ModelSnapshot).where(
                    and_(
                        ModelSnapshot.model_id == record.model_id,
                        ModelSnapshot.domain == record.domain,
                    )
                )
            )
            if existing is None:
                self.session.add(ModelSnapshot(**record.__dict__))
            else:
                existing.provider = record.provider
                existing.benchmark_score = record.benchmark_score
                existing.scores = record.scores
                existing.score_source = record.score_source
                existing.data = record.data

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

    def latest_snapshots(self, domain: str) -> list[ModelSnapshot]:
        stmt = (
            select(ModelSnapshot)
            .where(ModelSnapshot.domain == domain)
            .order_by(ModelSnapshot.benchmark_score.desc(), asc(ModelSnapshot.model_id))
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
        self, domain: str, *, limit: int, offset: int
    ) -> tuple[list[ModelSnapshot], int]:
        condition = ModelSnapshot.domain == domain
        total = self.session.scalar(
            select(func.count()).select_from(ModelSnapshot).where(condition)
        )
        stmt = (
            select(ModelSnapshot)
            .where(condition)
            .order_by(
                ModelSnapshot.benchmark_score.desc().nulls_last(),
                asc(ModelSnapshot.model_id),
            )
            .limit(limit)
            .offset(offset)
        )
        return list(self.session.scalars(stmt).all()), int(total or 0)

    def snapshots_by_model(self, model_id: str) -> list[ModelSnapshot]:
        stmt = (
            select(ModelSnapshot)
            .where(ModelSnapshot.model_id == model_id)
            .order_by(asc(ModelSnapshot.domain))
        )
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
