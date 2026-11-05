"""M08 单元测试夹具：eager Celery + 假仓储/会话/站点（无 broker/DB/网络）。"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Self

import pytest

from app.db.enums import FetchTaskStatus
from app.db.models import FetchTask
from app.db.state_machine import ensure_transition
from app.fetchers.base import BaseFetcher
from app.fetchers.config_loader import SiteConfig
from app.repositories.dto import SnapshotRecord
from app.worker import celery_app

NOW = datetime(2026, 1, 1, tzinfo=UTC)


def make_task_row(**overrides: Any) -> FetchTask:
    """构造 fetch_tasks 行（不落库，字段与 ORM 对齐）。"""
    values: dict[str, Any] = {
        "id": uuid.uuid4(),
        "task_type": "model_metrics",
        "source_key": "openrouter",
        "domain": "general",
        "triggered_by": "user-1",
        "status": FetchTaskStatus.PENDING.value,
        "attempt_count": 0,
        "hit_count": 0,
        "auto_start": True,
        "fetch_strategy": None,
        "error_message": None,
        "data": {},
        "created_at": NOW,
        "updated_at": NOW,
    }
    values.update(overrides)
    return FetchTask(**values)


def make_snapshot_record(model_id: str = "openai/gpt-4o") -> SnapshotRecord:
    return SnapshotRecord(
        model_id=model_id,
        provider="openai",
        domain="general",
        benchmark_score=Decimal("95.5"),
    )


class FakeFetcher(BaseFetcher):
    """固定产出记录的方案替身；error 注入时 fetch 抛该异常。"""

    def __init__(
        self,
        *,
        records: list[Any] | None = None,
        error: Exception | None = None,
        site_key: str = "openrouter",
    ) -> None:
        super().__init__({"key": site_key, "data_type": "model_metrics"})
        self._records = records if records is not None else [make_snapshot_record()]
        self._error = error
        self.fetch_calls = 0

    def fetch(self) -> list[Any]:
        self.fetch_calls += 1
        if self._error is not None:
            raise self._error
        return self._records

    def normalize(self, raw: Any, *, data_type: str | None = None) -> tuple[list[Any], bool]:
        return list(raw), False


class FakeRepo:
    """仓储替身：内存维护任务字段，复用真实状态机校验迁移合法性。"""

    def __init__(self, task: FetchTask | None) -> None:
        self.task = task
        self.transitions: list[str] = []
        self.error_message: str | None = None
        self.upserts: list[tuple[str, int]] = []

    def get_task(self, task_id: uuid.UUID) -> FetchTask | None:
        return self.task

    def _set_status(self, target: str) -> FetchTask:
        assert self.task is not None
        ensure_transition(self.task.status, target)
        self.task.status = target
        self.transitions.append(target)
        return self.task

    def mark_running(self, task_id: uuid.UUID) -> FetchTask:
        return self._set_status(FetchTaskStatus.RUNNING.value)

    def bump_attempt(self, task_id: uuid.UUID) -> FetchTask:
        assert self.task is not None
        self.task.attempt_count += 1
        return self.task

    def mark_retry_pending(
        self, task_id: uuid.UUID, *, error_message: str | None = None
    ) -> FetchTask:
        task = self._set_status(FetchTaskStatus.PENDING.value)
        task.error_message = error_message
        return task

    def mark_succeeded(
        self, task_id: uuid.UUID, *, strategy: str, hit_count: int, min_hits: int = 1
    ) -> FetchTask:
        task = self._set_status(FetchTaskStatus.SUCCEEDED.value)
        task.fetch_strategy = strategy
        task.hit_count = hit_count
        return task

    def mark_partial_succeeded(
        self, task_id: uuid.UUID, *, strategy: str, hit_count: int
    ) -> FetchTask:
        task = self._set_status(FetchTaskStatus.PARTIAL_SUCCEEDED.value)
        task.fetch_strategy = strategy
        task.hit_count = hit_count
        return task

    def mark_failed_exhausted(
        self, task_id: uuid.UUID, *, error_message: str | None = None
    ) -> FetchTask:
        task = self._set_status(FetchTaskStatus.FAILED_EXHAUSTED.value)
        task.hit_count = 0
        task.error_message = error_message
        self.error_message = error_message
        return task

    def mark_captcha_pending(self, task_id: uuid.UUID) -> FetchTask:
        return self._set_status(FetchTaskStatus.CAPTCHA_PENDING.value)

    def upsert_snapshots(self, records: Any) -> int:
        self.upserts.append(("snapshots", len(records)))
        return len(records)

    def upsert_costs(self, records: Any) -> int:
        self.upserts.append(("costs", len(records)))
        return len(records)

    def upsert_subscription_plans(self, records: Any) -> int:
        self.upserts.append(("plans", len(records)))
        return len(records)


class FakeSession:
    """会话替身：记录 commit/rollback/close，不持有任何真实连接。"""

    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def __enter__(self) -> Self:
        return self

    def __exit__(self, *exc: object) -> bool:
        self.closed = True
        return False

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class TaskEnv:
    """一次 eager 执行的装配产物：仓储/会话/站点加载记录，供逐项断言。"""

    def __init__(self, repo: FakeRepo, session: FakeSession) -> None:
        self.repo = repo
        self.session = session
        self.loaded_sites: list[str] = []


def make_site(
    fetchers: list[tuple[str, BaseFetcher]],
    *,
    strategies: list[str] | None = None,
    skipped: list[tuple[str, str]] | None = None,
) -> SiteConfig:
    """构造最小 SiteConfig，只携带编排层消费的字段。"""
    return SiteConfig(
        key="openrouter",
        path=Path("sites/openrouter"),
        cfg={},
        data_type="model_metrics",
        data_types=("model_metrics",),
        domain="general",
        strategies=strategies if strategies is not None else [name for name, _ in fetchers],
        fetchers=fetchers,
        skipped=skipped or [],
    )


WireFunc = Callable[[FetchTask | None, SiteConfig], TaskEnv]


@pytest.fixture
def wire_task(monkeypatch: pytest.MonkeyPatch) -> Iterator[WireFunc]:
    """装配 eager 执行环境：注入假仓储/会话/站点加载，返回 wire(task, site)。"""
    celery_app.conf.update(task_always_eager=True)

    def _wire(task: FetchTask | None, site: SiteConfig) -> TaskEnv:
        env = TaskEnv(FakeRepo(task), FakeSession())
        monkeypatch.setattr("app.tasks.fetch.Repository", lambda session: env.repo)
        monkeypatch.setattr(
            "app.tasks.fetch.get_session_factory", lambda settings: lambda: env.session
        )

        def fake_load_site(sites_dir: Any, key: str) -> SiteConfig:
            env.loaded_sites.append(key)
            return site

        monkeypatch.setattr("app.tasks.fetch.load_site", fake_load_site)
        return env

    yield _wire
    celery_app.conf.update(task_always_eager=False)
