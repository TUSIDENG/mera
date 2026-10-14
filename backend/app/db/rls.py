"""PostgreSQL RLS 会话辅助。"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

_ALLOWED_ROLES = frozenset({"authenticated_users"})


def set_rls_context(
    session: Session,
    *,
    user_id: str,
    org_id: str,
    role: str = "authenticated_users",
) -> None:
    """在当前事务中切换受限角色并设置 RLS GUC。

    必须在开启事务后、业务 SQL 前调用；调用方负责提交或回滚。
    """
    if role not in _ALLOWED_ROLES:
        raise ValueError(f"不支持的数据库角色: {role}")

    session.execute(text(f"SET LOCAL ROLE {role}"))
    session.execute(
        text("SELECT set_config('app.current_user_id', :user_id, true)"),
        {"user_id": user_id},
    )
    session.execute(
        text("SELECT set_config('app.current_org_id', :org_id, true)"),
        {"org_id": org_id},
    )
