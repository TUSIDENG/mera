"""M02 fetch_tasks 仓储生命周期测试。"""

from __future__ import annotations

import pytest
from sqlalchemy.orm import Session

from app.core.exceptions import InvalidTransition
from app.db.enums import FetchTaskStatus
from app.repositories import CreateTaskParams, Repository


def create_running_task(repo: Repository) -> object:
    task = repo.create_task(
        CreateTaskParams(
            task_type="model_metrics",
            source_key="openrouter",
            triggered_by="user-1",
            domain="coding",
        )
    )
    repo.session.commit()
    return repo.mark_running(task.id)


def test_create_task_defaults_to_pending(db_session: Session) -> None:
    repo = Repository(db_session)
    task = repo.create_task(
        CreateTaskParams(
            task_type="model_metrics",
            source_key="openrouter",
            triggered_by="user-1",
            domain="coding",
        )
    )
    db_session.commit()

    stored = repo.get_task(task.id)
    assert stored is not None
    assert stored.status == FetchTaskStatus.PENDING.value
    assert stored.attempt_count == 0
    assert stored.hit_count == 0


def test_create_task_reuses_existing_in_progress_task(db_session: Session) -> None:
    repo = Repository(db_session)
    params = CreateTaskParams(
        task_type="model_metrics",
        source_key="openrouter",
        triggered_by="user-1",
        domain="coding",
    )
    first = repo.create_task(params)
    second = repo.create_task(params)
    db_session.commit()

    assert first.id == second.id


def test_new_task_allowed_after_terminal_state(db_session: Session) -> None:
    repo = Repository(db_session)
    params = CreateTaskParams(
        task_type="infrastructure_cost",
        source_key="aws",
        triggered_by="user-1",
    )
    first = repo.create_task(params)
    db_session.commit()
    repo.mark_running(first.id)
    repo.bump_attempt(first.id)
    repo.bump_attempt(first.id)
    repo.bump_attempt(first.id)
    repo.mark_failed_exhausted(first.id, error_message="no data")

    second = repo.create_task(params)
    db_session.commit()
    assert second.id != first.id
    assert second.status == FetchTaskStatus.PENDING.value


def test_running_to_succeeded_with_hits(db_session: Session) -> None:
    repo = Repository(db_session)
    task = create_running_task(repo)

    result = repo.mark_succeeded(
        task.id,
        strategy="openrouter/api",
        hit_count=3,
    )
    db_session.commit()

    assert result.status == FetchTaskStatus.SUCCEEDED.value
    assert result.fetch_strategy == "openrouter/api"
    assert result.hit_count == 3


def test_running_to_partial_when_hits_exist_at_attempt_limit(db_session: Session) -> None:
    repo = Repository(db_session)
    task = create_running_task(repo)
    repo.bump_attempt(task.id)
    repo.bump_attempt(task.id)
    repo.bump_attempt(task.id)

    result = repo.mark_partial_succeeded(
        task.id,
        strategy="openrouter/playwright",
        hit_count=2,
    )
    db_session.commit()

    assert result.status == FetchTaskStatus.PARTIAL_SUCCEEDED.value
    assert result.hit_count == 2


def test_running_to_failed_exhausted_only_with_zero_hits(db_session: Session) -> None:
    repo = Repository(db_session)
    task = create_running_task(repo)
    task.hit_count = 2
    db_session.flush()

    with pytest.raises(InvalidTransition):
        repo.mark_failed_exhausted(task.id)

    task.hit_count = 0
    db_session.flush()
    result = repo.mark_failed_exhausted(task.id, error_message="all strategies failed")
    db_session.commit()

    assert result.status == FetchTaskStatus.FAILED_EXHAUSTED.value
    assert result.hit_count == 0
    assert result.error_message == "all strategies failed"


def test_succeeded_requires_configured_min_hits(db_session: Session) -> None:
    repo = Repository(db_session)
    task = create_running_task(repo)

    with pytest.raises(InvalidTransition):
        repo.mark_succeeded(
            task.id,
            strategy="source/api",
            hit_count=1,
            min_hits=2,
        )


def test_captcha_pending_short_circuit_and_resume(db_session: Session) -> None:
    repo = Repository(db_session)
    task = create_running_task(repo)

    pending = repo.mark_captcha_pending(task.id)
    assert pending.status == FetchTaskStatus.CAPTCHA_PENDING.value

    running = repo.mark_running(task.id)
    assert running.status == FetchTaskStatus.RUNNING.value
    assert running.attempt_count == 0


def test_terminal_status_cannot_transition(db_session: Session) -> None:
    repo = Repository(db_session)
    task = create_running_task(repo)
    succeeded = repo.mark_succeeded(
        task.id,
        strategy="source/api",
        hit_count=1,
    )

    with pytest.raises(InvalidTransition):
        repo.mark_running(succeeded.id)
    with pytest.raises(InvalidTransition):
        repo.mark_captcha_pending(succeeded.id)


def test_retry_pending_keeps_task_active(db_session: Session) -> None:
    repo = Repository(db_session)
    task = create_running_task(repo)
    repo.bump_attempt(task.id)

    retry = repo.mark_retry_pending(task.id, error_message="temporary failure")
    db_session.commit()

    assert retry.status == FetchTaskStatus.PENDING.value
    assert retry.attempt_count == 1
    assert retry.error_message == "temporary failure"


def test_get_missing_task_raises(db_session: Session) -> None:
    repo = Repository(db_session)
    import uuid

    with pytest.raises(ValueError):
        repo.mark_running(uuid.uuid4())
