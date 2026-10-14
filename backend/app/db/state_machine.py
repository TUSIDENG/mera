"""fetch_tasks 状态机：纯函数，不访问数据库。"""

from __future__ import annotations

from app.core.exceptions import InvalidTransition
from app.db.enums import FetchTaskStatus as Status

ALLOWED_TRANSITIONS: dict[str, frozenset[str]] = {
    Status.PENDING: frozenset({Status.RUNNING}),
    Status.RUNNING: frozenset(
        {
            Status.PENDING,
            Status.SUCCEEDED,
            Status.PARTIAL_SUCCEEDED,
            Status.FAILED_EXHAUSTED,
            Status.CAPTCHA_PENDING,
        }
    ),
    Status.CAPTCHA_PENDING: frozenset({Status.RUNNING}),
    Status.SUCCEEDED: frozenset(),
    Status.PARTIAL_SUCCEEDED: frozenset(),
    Status.FAILED_EXHAUSTED: frozenset(),
}


def ensure_transition(current: str, target: str) -> None:
    if target not in ALLOWED_TRANSITIONS.get(current, frozenset()):
        raise InvalidTransition(f"非法任务状态迁移: {current} -> {target}")


def decide_run_result(
    *,
    hit_count: int,
    truncated: bool,
    attempt_count: int,
    max_attempts: int,
    min_hits: int = 1,
) -> Status:
    """判断一轮采集结束后的成功、部分成功或失败终态。"""
    if hit_count < 0 or attempt_count < 0 or max_attempts <= 0 or min_hits <= 0:
        raise ValueError("状态机参数必须为正数，hit_count/attempt_count 不能为负")
    if hit_count == 0 and attempt_count >= max_attempts:
        return Status.FAILED_EXHAUSTED
    if hit_count >= 1 and (truncated or attempt_count >= max_attempts):
        return Status.PARTIAL_SUCCEEDED
    if hit_count >= min_hits:
        return Status.SUCCEEDED
    return Status.PENDING


def ensure_terminal_rules(current: str, target: str, *, hit_count: int, attempt_count: int) -> None:
    if current != Status.RUNNING:
        return
    if target == Status.FAILED_EXHAUSTED and hit_count != 0:
        raise InvalidTransition("hit_count 大于 0 时不能标记为 failed_exhausted")
    if target == Status.SUCCEEDED and hit_count < 1:
        raise InvalidTransition("hit_count 为 0 时不能标记为 succeeded")
    if target == Status.PARTIAL_SUCCEEDED and hit_count < 1:
        raise InvalidTransition("hit_count 为 0 时不能标记为 partial_succeeded")
    if target == Status.PARTIAL_SUCCEEDED and attempt_count < 1:
        raise InvalidTransition("partial_succeeded 至少要完成一次尝试")
