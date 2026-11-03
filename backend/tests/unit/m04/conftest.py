"""M04 单测公共夹具：TestClient + dependency_overrides（无 DB、无 Casdoor、无 broker）。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient

from app.api.depends import (
    get_current_identity,
    get_enqueuer,
    get_internal_repository,
    get_repository,
)
from app.core.config import Settings
from app.core.security import Identity
from app.db.enums import FetchTaskStatus
from app.db.models import (
    FetchTask,
    InfrastructureCost,
    ModelSnapshot,
    SubscriptionPlan,
    UserEvaluation,
)
from app.main import create_app
from app.services.enqueue import queue_for_strategy

NOW = datetime(2026, 1, 1, tzinfo=UTC)
INTERNAL_TOKEN = "internal-secret"

USER_IDENTITY = Identity(user_id="user-1", org_id="main", roles=("mera-user",))
ADMIN_IDENTITY = Identity(user_id="admin-1", org_id="main", roles=("mera-admin",))


def make_snapshot(**overrides: Any) -> ModelSnapshot:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "model_id": "gpt-4o",
        "provider": "openai",
        "domain": "coding",
        "benchmark_score": Decimal("95.50"),
        "data": {},
        "updated_at": NOW,
    }
    values.update(overrides)
    return ModelSnapshot(**values)


def make_task(**overrides: Any) -> FetchTask:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "task_type": "model_metrics",
        "source_key": "openrouter",
        "domain": "coding",
        "triggered_by": "user-1",
        "status": FetchTaskStatus.PENDING.value,
        "attempt_count": 0,
        "hit_count": 0,
        "auto_start": True,
        "fetch_strategy": "api",
        "error_message": None,
        "data": {},
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return FetchTask(**values)


def make_plan(**overrides: Any) -> SubscriptionPlan:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "provider": "openai",
        "plan_key": "pro",
        "plan_name": "Pro",
        "monthly_price": Decimal("20.00"),
        "currency": "USD",
        "billing_cycle": "monthly",
        "is_active": True,
        "source": "manual",
        "data": {},
        "updated_at": NOW,
    }
    values.update(overrides)
    return SubscriptionPlan(**values)


def make_cost(**overrides: Any) -> InfrastructureCost:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "cost_type": "gpu_rental",
        "name": "A100 80G",
        "region": "default",
        "unit": "hour",
        "unit_price": Decimal("2.5000"),
        "source": "manual",
        "is_active": True,
        "data": {},
        "updated_at": NOW,
    }
    values.update(overrides)
    return InfrastructureCost(**values)


def make_evaluation(**overrides: Any) -> UserEvaluation:
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "org_id": "main",
        "user_id": "user-1",
        "domain": "coding",
        "status": "completed",
        "fetch_task_id": None,
        "snapshot_used_ids": [],
        "data": {},
        "created_at": NOW,
    }
    values.update(overrides)
    return UserEvaluation(**values)


class FakeRepo:
    """记录调用的仓储替身；返回值可通过属性覆盖。"""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.task: FetchTask | None = make_task()
        self.snapshots: list[ModelSnapshot] = [make_snapshot()]
        self.plans: list[SubscriptionPlan] = [make_plan()]
        self.costs: list[InfrastructureCost] = [make_cost()]
        self.evaluations: list[UserEvaluation] = [make_evaluation()]
        self.created_task_params: Any = None
        self.created_evaluation_kwargs: dict[str, Any] = {}

    def _log(self, method: str, **kwargs: Any) -> None:
        self.calls.append((method, kwargs))

    def list_snapshots(self, domain: str, *, limit: int, offset: int):
        self._log("list_snapshots", domain=domain, limit=limit, offset=offset)
        return self.snapshots, len(self.snapshots)

    def snapshots_by_model(self, model_id: str):
        self._log("snapshots_by_model", model_id=model_id)
        return self.snapshots

    def latest_snapshots(self, domain: str):
        self._log("latest_snapshots", domain=domain)
        return self.snapshots

    def list_tasks(self, *, status: str | None, limit: int, offset: int):
        self._log("list_tasks", status=status, limit=limit, offset=offset)
        items = [self.task] if self.task is not None else []
        return items, len(items)

    def create_task(self, params: Any):
        self._log("create_task", params=params)
        self.created_task_params = params
        return make_task(
            task_type=params.task_type,
            source_key=params.source_key,
            domain=params.domain,
            triggered_by=params.triggered_by,
            auto_start=params.auto_start,
            data=params.data,
        )

    def get_task(self, task_id: uuid.UUID):
        self._log("get_task", task_id=task_id)
        return self.task

    def list_plans(self, *, provider: str | None, active_only: bool, limit: int, offset: int):
        self._log(
            "list_plans", provider=provider, active_only=active_only, limit=limit, offset=offset
        )
        return self.plans, len(self.plans)

    def get_plan(self, provider: str, plan_key: str, billing_cycle: str):
        self._log("get_plan", provider=provider, plan_key=plan_key, billing_cycle=billing_cycle)
        return self.plans[0] if self.plans else None

    def upsert_subscription_plans(self, records: Any):
        self._log("upsert_subscription_plans", records=list(records))
        return len(records)

    def list_costs(self, *, cost_type: str | None, limit: int, offset: int):
        self._log("list_costs", cost_type=cost_type, limit=limit, offset=offset)
        return self.costs, len(self.costs)

    def get_cost(self, cost_type: str, name: str, region: str):
        self._log("get_cost", cost_type=cost_type, name=name, region=region)
        return self.costs[0] if self.costs else None

    def upsert_costs(self, records: Any):
        self._log("upsert_costs", records=list(records))
        return len(records)

    def create_evaluation(self, **kwargs: Any):
        self._log("create_evaluation", **kwargs)
        self.created_evaluation_kwargs = kwargs
        return make_evaluation(**kwargs)

    def list_evaluations(self, *, user_id: str, limit: int, offset: int):
        self._log("list_evaluations", user_id=user_id, limit=limit, offset=offset)
        return self.evaluations, len(self.evaluations)

    def mark_succeeded(self, task_id: uuid.UUID, *, strategy: str, hit_count: int, min_hits: int = 1):
        self._log(
            "mark_succeeded", task_id=task_id, strategy=strategy, hit_count=hit_count, min_hits=min_hits
        )
        assert self.task is not None
        self.task.status = FetchTaskStatus.SUCCEEDED.value
        self.task.fetch_strategy = strategy
        self.task.hit_count = hit_count
        return self.task

    def mark_partial_succeeded(self, task_id: uuid.UUID, *, strategy: str, hit_count: int):
        self._log("mark_partial_succeeded", task_id=task_id, strategy=strategy, hit_count=hit_count)
        assert self.task is not None
        self.task.status = FetchTaskStatus.PARTIAL_SUCCEEDED.value
        self.task.fetch_strategy = strategy
        self.task.hit_count = hit_count
        return self.task

    def mark_failed_exhausted(self, task_id: uuid.UUID, *, error_message: str | None = None):
        self._log("mark_failed_exhausted", task_id=task_id, error_message=error_message)
        assert self.task is not None
        self.task.status = FetchTaskStatus.FAILED_EXHAUSTED.value
        self.task.hit_count = 0
        return self.task

    def mark_captcha_pending(self, task_id: uuid.UUID):
        self._log("mark_captcha_pending", task_id=task_id)
        assert self.task is not None
        self.task.status = FetchTaskStatus.CAPTCHA_PENDING.value
        return self.task


class FakeEnqueuer:
    def __init__(self) -> None:
        self.enqueued: list[tuple[uuid.UUID, str | None]] = []

    def enqueue(self, task_id: uuid.UUID, *, strategy: str | None = None) -> str:
        self.enqueued.append((task_id, strategy))
        return queue_for_strategy(strategy)


def make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": "sqlite://",
        "redis_url": "redis://localhost:6379/0",
        "internal_api_token": INTERNAL_TOKEN,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def build_client(
    *,
    identity: Identity | None = USER_IDENTITY,
    repo: FakeRepo | None = None,
    enqueuer: FakeEnqueuer | None = None,
) -> tuple[TestClient, FakeRepo, FakeEnqueuer]:
    """组装测试客户端；identity=None 时不覆盖认证依赖（Casdoor 未配置 → 401）。"""
    repo = repo or FakeRepo()
    enqueuer = enqueuer or FakeEnqueuer()
    app = create_app(make_settings())
    app.dependency_overrides[get_internal_repository] = lambda: repo
    app.dependency_overrides[get_enqueuer] = lambda: enqueuer
    if identity is not None:
        app.dependency_overrides[get_current_identity] = lambda: identity
        # 覆盖 get_repository 会旁路 get_db_session→get_current_identity 认证链，
        # 因此匿名客户端（identity=None）不覆盖，以验证未带 token 返回 401
        app.dependency_overrides[get_repository] = lambda: repo
    return TestClient(app), repo, enqueuer


@pytest.fixture()
def user_client() -> tuple[TestClient, FakeRepo, FakeEnqueuer]:
    return build_client(identity=USER_IDENTITY)


@pytest.fixture()
def admin_client() -> tuple[TestClient, FakeRepo, FakeEnqueuer]:
    return build_client(identity=ADMIN_IDENTITY)


@pytest.fixture()
def anon_client() -> tuple[TestClient, FakeRepo, FakeEnqueuer]:
    return build_client(identity=None)
