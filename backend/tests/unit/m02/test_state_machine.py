"""M02 fetch_tasks 状态机纯函数测试。"""

from __future__ import annotations

import pytest

from app.core.exceptions import InvalidTransition
from app.db.enums import FetchTaskStatus as S
from app.db.state_machine import decide_run_result, ensure_terminal_rules, ensure_transition


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (S.PENDING, S.RUNNING),
        (S.RUNNING, S.PENDING),
        (S.RUNNING, S.SUCCEEDED),
        (S.RUNNING, S.PARTIAL_SUCCEEDED),
        (S.RUNNING, S.FAILED_EXHAUSTED),
        (S.RUNNING, S.CAPTCHA_PENDING),
        (S.CAPTCHA_PENDING, S.RUNNING),
    ],
)
def test_allowed_transitions(current: S, target: S) -> None:
    ensure_transition(current.value, target.value)


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (S.SUCCEEDED, S.RUNNING),
        (S.PARTIAL_SUCCEEDED, S.RUNNING),
        (S.FAILED_EXHAUSTED, S.PENDING),
        (S.PENDING, S.SUCCEEDED),
        (S.CAPTCHA_PENDING, S.SUCCEEDED),
    ],
)
def test_rejects_illegal_transitions(current: S, target: S) -> None:
    with pytest.raises(InvalidTransition):
        ensure_transition(current.value, target.value)


def test_decide_succeeded_with_enough_hits_before_attempt_limit() -> None:
    result = decide_run_result(
        hit_count=5,
        truncated=False,
        attempt_count=1,
        max_attempts=3,
    )
    assert result == S.SUCCEEDED


def test_decide_partial_when_attempt_limit_reached_with_hits() -> None:
    result = decide_run_result(
        hit_count=2,
        truncated=False,
        attempt_count=3,
        max_attempts=3,
    )
    assert result == S.PARTIAL_SUCCEEDED


def test_decide_partial_when_truncated_with_hits() -> None:
    result = decide_run_result(
        hit_count=1,
        truncated=True,
        attempt_count=1,
        max_attempts=3,
    )
    assert result == S.PARTIAL_SUCCEEDED


def test_decide_failed_only_when_limit_reached_without_hits() -> None:
    exhausted = decide_run_result(
        hit_count=0,
        truncated=False,
        attempt_count=3,
        max_attempts=3,
    )
    retry = decide_run_result(
        hit_count=0,
        truncated=False,
        attempt_count=2,
        max_attempts=3,
    )
    assert exhausted == S.FAILED_EXHAUSTED
    assert retry == S.PENDING


def test_truncated_without_hits_does_not_partial_or_succeed() -> None:
    result = decide_run_result(
        hit_count=0,
        truncated=True,
        attempt_count=2,
        max_attempts=3,
    )
    assert result == S.PENDING


def test_min_hits_threshold_can_make_result_pending() -> None:
    result = decide_run_result(
        hit_count=1,
        truncated=False,
        attempt_count=1,
        max_attempts=3,
        min_hits=2,
    )
    assert result == S.PENDING


def test_terminal_rules_reject_hit_count_mismatch() -> None:
    with pytest.raises(InvalidTransition):
        ensure_terminal_rules(
            S.RUNNING.value,
            S.FAILED_EXHAUSTED.value,
            hit_count=2,
            attempt_count=3,
        )
    with pytest.raises(InvalidTransition):
        ensure_terminal_rules(
            S.RUNNING.value,
            S.SUCCEEDED.value,
            hit_count=0,
            attempt_count=1,
        )
    with pytest.raises(InvalidTransition):
        ensure_terminal_rules(
            S.RUNNING.value,
            S.PARTIAL_SUCCEEDED.value,
            hit_count=0,
            attempt_count=3,
        )


def test_invalid_state_machine_parameters() -> None:
    with pytest.raises(ValueError):
        decide_run_result(
            hit_count=-1,
            truncated=False,
            attempt_count=1,
            max_attempts=3,
        )
