"""M02 PostgreSQL 集成测试：真实 JSONB、UUIDv7、约束与组织 RLS。

postgres_url / migrated_settings / session_factory 夹具见 tests/integration/conftest.py。
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

from app.db.enums import FetchTaskStatus
from app.db.models import FetchTask, ModelSnapshot, UserEvaluation
from app.db.rls import set_rls_context
from app.db.uuid7 import uuid7
from app.repositories import CreateTaskParams, Repository

pytestmark = pytest.mark.integration


def test_migration_creates_five_tables(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        names = set(
            session.execute(
                text(
                    """
                    SELECT table_name
                    FROM information_schema.tables
                    WHERE table_schema = 'public'
                    """
                )
            ).scalars()
        )

    assert {
        "model_snapshots",
        "fetch_tasks",
        "user_evaluations",
        "infrastructure_costs",
        "subscription_plans",
    } <= names


def test_uuidv7_jsonb_and_terminal_check_constraint(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        snapshot = ModelSnapshot(
            model_id="openai/gpt-test",
            provider="openai",
            domain="coding",
            benchmark_score=Decimal("91.50"),
            data={"input_price": "3.00"},
        )
        session.add(snapshot)
        session.commit()

        assert snapshot.id.version == 7
        assert snapshot.data["input_price"] == "3.00"

        task = FetchTask(
            task_type="model_metrics",
            source_key="openrouter",
            domain="coding",
            triggered_by="system",
            status=FetchTaskStatus.RUNNING.value,
            attempt_count=3,
        )
        session.add(task)
        session.commit()
        task.status = FetchTaskStatus.FAILED_EXHAUSTED.value
        task.hit_count = 1

        with pytest.raises(IntegrityError):
            session.commit()
        session.rollback()


def test_org_rls_isolates_user_evaluations(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as setup:
        task = FetchTask(
            task_type="model_metrics",
            source_key="openrouter",
            triggered_by="user-a",
        )
        setup.add(task)
        setup.flush()
        eval_a = UserEvaluation(
            org_id="org-a",
            user_id="user-a",
            domain="coding",
            fetch_task_id=task.id,
            snapshot_used_ids=[uuid7()],
            data={"report": "a"},
        )
        eval_b = UserEvaluation(
            org_id="org-b",
            user_id="user-b",
            domain="coding",
            snapshot_used_ids=[],
            data={"report": "b"},
        )
        setup.add_all([eval_a, eval_b])
        setup.commit()
        eval_a_id = eval_a.id

    with session_factory() as session:
        session.begin()
        set_rls_context(session, user_id="user-a", org_id="org-a")
        records = session.query(UserEvaluation).all()

        assert [record.org_id for record in records] == ["org-a"]
        assert records[0].id == eval_a_id

        with pytest.raises(ProgrammingError):
            session.add(
                UserEvaluation(
                    org_id="org-b",
                    user_id="attacker",
                    domain="coding",
                    snapshot_used_ids=[],
                )
            )
            session.commit()
        session.rollback()


def test_repository_runs_on_postgres(session_factory: sessionmaker[Session]) -> None:
    with session_factory() as session:
        repo = Repository(session)
        task = repo.create_task(
            CreateTaskParams(
                task_type="infrastructure_cost",
                source_key="aws",
                triggered_by="system",
                data={"regions": ["us-east-1"]},
            )
        )
        session.commit()

        stored = repo.get_task(task.id)
        assert stored is not None
        assert stored.data["regions"] == ["us-east-1"]
