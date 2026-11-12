"""M05 统一编排：站点内策略链降级、指数退避重试、按 hit_count 终态分流。

终态语义与 M02 状态机一致（复用 decide_run_result）：
hit_count >= min_hits 且未截断 -> succeeded；达到最大尝试次数但 hit_count >= 1
（或翻页截断）-> partial_succeeded（不熔断、不丢弃有效数据）；最终 0 条 -> failed_exhausted。

通知/ auto_start 接续由调用方（M08/M10）按返回结果处理，不在本层。
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any, Protocol

from app.core.exceptions import CaptchaRequired, ConfigError, FetchFailed
from app.db.enums import FetchTaskStatus as Status
from app.db.state_machine import decide_run_result
from app.fetchers.base import BaseFetcher, is_strategy_available
from app.repositories.dto import (
    ApiPriceRecord,
    CostRecord,
    SnapshotRecord,
    SubscriptionPlanRecord,
)


class Clock(Protocol):
    def sleep(self, seconds: float) -> None: ...


class SystemClock:
    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)


class FetchTaskControl(Protocol):
    """run_fetch 依赖的任务句柄协议（由 FakeTask 或 RepoTaskHandle 实现）。"""

    attempt_count: int

    def mark_running(self) -> None: ...
    def bump_attempt(self) -> None: ...
    def mark_retry_pending(self, error_message: str | None = None) -> None: ...
    def mark_succeeded(self, *, strategy: str, hit_count: int) -> None: ...
    def mark_partial_succeeded(
        self, *, strategy: str, hit_count: int, error_message: str | None = None
    ) -> None: ...
    def mark_failed_exhausted(self, error_message: str | None = None) -> None: ...
    def mark_captcha_pending(self) -> None: ...
    def log_skip(self, strategy: str, reason: str) -> None: ...
    def log_failure(self, strategy: str, message: str) -> None: ...
    def log_empty(self, strategy: str) -> None: ...


@dataclass(frozen=True)
class FetchRunResult:
    status: str
    hit_strategy: str | None
    hit_count: int
    truncated: bool
    attempts: int


_UPSERT_METHOD = {
    SnapshotRecord: "upsert_snapshots",
    ApiPriceRecord: "upsert_prices",
    CostRecord: "upsert_costs",
    SubscriptionPlanRecord: "upsert_subscription_plans",
}


def run_fetch(
    task: FetchTaskControl,
    fetchers: Iterable[tuple[str, BaseFetcher]],
    repo: Any,
    clock: Clock | None = None,
    *,
    min_hits: int = 1,
    max_attempts: int = 3,
    backoff_base_seconds: float = 60.0,
) -> FetchRunResult:
    """按声明顺序遍历站点方案，任一方案产出有效数据即止；否则退避重试直至熔断。

    fetchers 为 (方案名, fetcher) 序列；若传入 config_loader.SiteConfig，
    其 skipped 列表（声明但缺文件的方案）会在首轮记录为 skipped。
    """
    clock = clock or SystemClock()
    pairs = list(fetchers)
    site_key = (
        getattr(fetchers, "key", None)
        or (pairs[0][1].site_key if pairs else "")
        or getattr(task, "source_key", "")
    )
    # 任务类型决定标准化产出的 DTO 类型（如 api_price 任务只产出 ApiPriceRecord）
    task_type = getattr(task, "task_type", None)
    pre_skipped = list(getattr(fetchers, "skipped", ()))
    attempt = int(getattr(task, "attempt_count", 0))
    last_error: str | None = None
    logged_skips: set[str] = set()

    def _log_skip_once(name: str, reason: str) -> None:
        # 不可用原因在一次运行内不会变化，每方案只记录一次，避免重试轮刷屏。
        if name not in logged_skips:
            logged_skips.add(name)
            task.log_skip(name, reason)

    while True:
        task.mark_running()
        for name, reason in pre_skipped:
            _log_skip_once(name, reason)
        pre_skipped = []

        records: list[Any] = []
        hit_name: str | None = None
        hit_fetcher: BaseFetcher | None = None
        truncated = False
        for name, fetcher in pairs:
            if not is_strategy_available(fetcher):
                _log_skip_once(name, fetcher.unavailable_reason or "依赖/密钥/会话未就绪")
                continue
            try:
                # 任务可指定领域（多领域站点据此只采该领域子页面；空表示全量）
                fetcher.domain = getattr(task, "domain", None)
                raw = fetcher.fetch()
            except CaptchaRequired:
                task.mark_captcha_pending()
                return FetchRunResult(
                    status=Status.CAPTCHA_PENDING,
                    hit_strategy=None,
                    hit_count=0,
                    truncated=False,
                    attempts=attempt + 1,
                )
            except FetchFailed as exc:
                last_error = exc.message
                task.log_failure(name, exc.message)
                continue
            found, truncated = fetcher.normalize(raw, data_type=task_type)
            if found:
                records, hit_name, hit_fetcher = found, name, fetcher
                break
            task.log_empty(name)  # normalize 空结果视为未命中，继续降级

        hit_count = (
            _upsert_records(repo, records, task_id=getattr(task, "task_id", None))
            if records
            else 0
        )
        attempt += 1
        task.bump_attempt()  # 回写 DB attempt_count，与终态规则（partial 要求 >=1）对齐
        status = decide_run_result(
            hit_count=hit_count,
            truncated=truncated,
            attempt_count=attempt,
            max_attempts=max_attempts,
            min_hits=min_hits,
        )
        strategy_label = f"{site_key}/{hit_name}" if hit_name else None
        # 部分子页面失败等非致命问题：写进任务日志，partial 时同时落到 error_message
        warnings = list(getattr(hit_fetcher, "warnings", ())) if hit_fetcher else []
        if warnings and hit_name:
            task.log_failure(hit_name, "; ".join(warnings))
        warn_message = "; ".join(warnings) or None

        if status == Status.SUCCEEDED:
            task.mark_succeeded(strategy=strategy_label or "", hit_count=hit_count)
        elif status == Status.PARTIAL_SUCCEEDED:
            task.mark_partial_succeeded(
                strategy=strategy_label or "",
                hit_count=hit_count,
                error_message=warn_message or last_error,
            )
        elif status == Status.FAILED_EXHAUSTED:
            task.mark_failed_exhausted(error_message=last_error)
        else:  # PENDING：指数退避后重试
            delay = backoff_base_seconds * (2 ** (attempt - 1))
            task.mark_retry_pending(error_message=last_error)
            clock.sleep(delay)
            continue
        return FetchRunResult(
            status=status,
            hit_strategy=strategy_label,
            hit_count=hit_count,
            truncated=truncated,
            attempts=attempt,
        )


def _upsert_records(repo: Any, records: list[Any], task_id: uuid.UUID | None = None) -> int:
    """按 DTO 类型路由到 M02 仓储的对应 UPSERT，返回实际落库条数（hit_count）。

    model_metrics 记录在 upsert 前追加 fetch_records 留痕（append-only，同事务）；
    task_id 缺失（如纯编排单测）时跳过留痕。
    """
    total = 0
    for record_type, method_name in _UPSERT_METHOD.items():
        group = [r for r in records if isinstance(r, record_type)]
        if group:
            if record_type is SnapshotRecord and task_id is not None:
                repo.insert_fetch_records(task_id, group)
            total += getattr(repo, method_name)(group)
    unknown = [r for r in records if type(r) not in _UPSERT_METHOD]
    if unknown:
        raise ConfigError(f"标准化产物类型无法路由落库: {type(unknown[0]).__name__}")
    return total


class RepoTaskHandle:
    """把 M02 Repository 的 task_id 方法族适配为 run_fetch 的 task 协议。

    状态迁移走仓储（含状态机校验）；skip/failure/empty 明细留在 event_log，
    是否持久化到 fetch_tasks.data 由调用方决定。
    """

    def __init__(self, repo: Any, task_id: uuid.UUID) -> None:
        self._repo = repo
        self._task_id = task_id
        self.event_log: list[tuple[str, str, str | None]] = []

    @property
    def task_id(self) -> uuid.UUID:
        return self._task_id

    @property
    def attempt_count(self) -> int:
        task = self._repo.get_task(self._task_id)
        return task.attempt_count if task is not None else 0

    @property
    def task_type(self) -> str | None:
        task = self._repo.get_task(self._task_id)
        return task.task_type if task is not None else None

    @property
    def domain(self) -> str | None:
        task = self._repo.get_task(self._task_id)
        return getattr(task, "domain", None) if task is not None else None

    def mark_running(self) -> None:
        self._repo.mark_running(self._task_id)

    def bump_attempt(self) -> None:
        self._repo.bump_attempt(self._task_id)

    def mark_retry_pending(self, error_message: str | None = None) -> None:
        self._repo.mark_retry_pending(self._task_id, error_message=error_message)

    def mark_succeeded(self, *, strategy: str, hit_count: int) -> None:
        self._repo.mark_succeeded(self._task_id, strategy=strategy, hit_count=hit_count)

    def mark_partial_succeeded(self, *, strategy: str, hit_count: int) -> None:
        self._repo.mark_partial_succeeded(self._task_id, strategy=strategy, hit_count=hit_count)

    def mark_failed_exhausted(self, error_message: str | None = None) -> None:
        self._repo.mark_failed_exhausted(self._task_id, error_message=error_message)

    def mark_captcha_pending(self) -> None:
        self._repo.mark_captcha_pending(self._task_id)

    def log_skip(self, strategy: str, reason: str) -> None:
        self.event_log.append(("skipped", strategy, reason))

    def log_failure(self, strategy: str, message: str) -> None:
        self.event_log.append(("failed", strategy, message))

    def log_empty(self, strategy: str) -> None:
        self.event_log.append(("empty", strategy, None))
