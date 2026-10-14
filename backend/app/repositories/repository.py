"""M02 数据访问仓储。"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import and_, asc, func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.exceptions import InvalidTransition
from app.db.enums import FetchTaskStatus
from app.db.models import (
    FetchTask,
    InfrastructureCost,
    ModelSnapshot,
    SubscriptionPlan,
)
from app.db.state_machine import ensure_terminal_rules, ensure_transition
from app.repositories.dto import (
    CostRecord,
    CreateTaskParams,
    SnapshotRecord,
    SubscriptionPlanRecord,
)


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
        values = [record.__dict__.copy() for record in records]
        stmt = pg_insert(ModelSnapshot).values(values)
        stmt = stmt.on_conflict_do_update(
            constraint="uq_model_snapshot",
            set_={
                "provider": stmt.excluded.provider,
                "benchmark_score": stmt.excluded.benchmark_score,
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
                existing.data = record.data

    def upsert_costs(self, records: Sequence[CostRecord]) -> int:
        if not records:
            return 0
        if self.session.bind is not None and self.session.bind.dialect.name == "postgresql":
            self._upsert_costs_pg(records)
        else:
            self._upsert_costs_generic(records)
        return len(records)

    def _upsert_costs_pg(self, records: Sequence[CostRecord]) -> None:
        values = [record.__dict__.copy() for record in records]
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
        values = [record.__dict__.copy() for record in records]
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
