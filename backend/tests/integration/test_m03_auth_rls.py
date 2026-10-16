"""M03 PostgreSQL 集成测试：open_rls_session（get_db_session 同逻辑）的组织隔离与写保护。"""

from __future__ import annotations

import pytest
from sqlalchemy import delete, select
from sqlalchemy.exc import ProgrammingError
from sqlalchemy.orm import Session, sessionmaker

from app.api.depends import open_rls_session
from app.core.config import Settings
from app.core.security import Identity
from app.db.models import UserEvaluation

pytestmark = pytest.mark.integration


@pytest.fixture()
def seeded_orgs(session_factory: sessionmaker[Session]) -> None:
    """以超级用户直连写入两个组织的评测记录（绕过 RLS，模拟历史数据）。"""
    with session_factory() as session, session.begin():
        session.execute(delete(UserEvaluation))
        session.add_all(
            [
                UserEvaluation(
                    org_id="org-a", user_id="user-a", domain="coding", snapshot_used_ids=[]
                ),
                UserEvaluation(
                    org_id="org-b", user_id="user-b", domain="coding", snapshot_used_ids=[]
                ),
            ]
        )


def test_rls_session_only_sees_own_org(
    migrated_settings: Settings,
    seeded_orgs: None,
) -> None:
    identity_a = Identity(user_id="user-a", org_id="org-a", roles=("user",))
    with open_rls_session(migrated_settings, identity_a) as session:
        rows_a = session.scalars(select(UserEvaluation)).all()
    assert {row.user_id for row in rows_a} == {"user-a"}

    identity_b = Identity(user_id="user-b", org_id="org-b", roles=("user",))
    with open_rls_session(migrated_settings, identity_b) as session:
        rows_b = session.scalars(select(UserEvaluation)).all()
    assert {row.user_id for row in rows_b} == {"user-b"}


def test_rls_session_insert_within_own_org(
    migrated_settings: Settings,
    seeded_orgs: None,
) -> None:
    identity = Identity(user_id="user-a2", org_id="org-a")
    with open_rls_session(migrated_settings, identity) as session:
        session.add(
            UserEvaluation(org_id="org-a", user_id="user-a2", domain="coding", snapshot_used_ids=[])
        )

    with open_rls_session(migrated_settings, identity) as session:
        rows = session.scalars(select(UserEvaluation)).all()
    assert {row.user_id for row in rows} == {"user-a", "user-a2"}


def test_rls_session_cross_org_insert_rejected(
    migrated_settings: Settings,
    seeded_orgs: None,
) -> None:
    identity = Identity(user_id="mallory", org_id="org-a")

    with (
        pytest.raises(ProgrammingError),
        open_rls_session(migrated_settings, identity) as session,
    ):
        session.add(
            UserEvaluation(
                org_id="org-b", user_id="mallory", domain="coding", snapshot_used_ids=[]
            )
        )
