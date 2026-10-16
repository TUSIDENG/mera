"""M05 单元测试假体：FakeFetcher / FakeTask / MockRepo / FakeClock（无网络/DB）。"""

from __future__ import annotations

from typing import Any

from app.fetchers.base import BaseFetcher


class FakeFetcher(BaseFetcher):
    """构造时给定可用性、记录或异常；normalize 原样返回注入的 DTO。"""

    def __init__(
        self,
        *,
        available: bool = True,
        reason: str | None = None,
        records: list[Any] | None = None,
        error: Exception | None = None,
        truncated: bool = False,
        site_key: str = "fakesite",
    ) -> None:
        super().__init__({"key": site_key, "data_type": "model_metrics"})
        self._available = available
        self._records = records or []
        self._error = error
        self.truncated = truncated
        self.unavailable_reason = reason
        self.fetch_calls = 0

    def is_available(self) -> bool:
        return self._available

    def fetch(self) -> list[Any]:
        self.fetch_calls += 1
        if self._error is not None:
            raise self._error
        return self._records

    def normalize(self, raw: Any) -> tuple[list[Any], bool]:
        return list(raw), self.truncated


class FakeTask:
    """记录状态迁移与 skip/failure/empty 明细。"""

    def __init__(self, *, attempt_count: int = 0, source_key: str = "fakesite") -> None:
        self.attempt_count = attempt_count
        self.source_key = source_key
        self.transitions: list[tuple[str, dict[str, Any]]] = []
        self.skips: list[tuple[str, str]] = []
        self.failures: list[tuple[str, str]] = []
        self.empties: list[str] = []

    def mark_running(self) -> None:
        self.transitions.append(("running", {}))

    def mark_retry_pending(self, error_message: str | None = None) -> None:
        self.transitions.append(("retry_pending", {"error": error_message}))

    def mark_succeeded(self, *, strategy: str, hit_count: int) -> None:
        self.transitions.append(("succeeded", {"strategy": strategy, "hit_count": hit_count}))

    def mark_partial_succeeded(self, *, strategy: str, hit_count: int) -> None:
        self.transitions.append(
            ("partial_succeeded", {"strategy": strategy, "hit_count": hit_count})
        )

    def mark_failed_exhausted(self, error_message: str | None = None) -> None:
        self.transitions.append(("failed_exhausted", {"error": error_message}))

    def mark_captcha_pending(self) -> None:
        self.transitions.append(("captcha_pending", {}))

    def log_skip(self, strategy: str, reason: str) -> None:
        self.skips.append((strategy, reason))

    def log_failure(self, strategy: str, message: str) -> None:
        self.failures.append((strategy, message))

    def log_empty(self, strategy: str) -> None:
        self.empties.append(strategy)

    @property
    def final(self) -> str:
        return self.transitions[-1][0]


class MockRepo:
    """注入固定 hit_count；记录收到的记录数。"""

    def __init__(self, hit_count: int = 0) -> None:
        self.hit_count = hit_count
        self.upserted: list[list[Any]] = []
        self.calls = 0

    def _record(self, records: list[Any]) -> int:
        self.calls += 1
        self.upserted.append(list(records))
        return self.hit_count

    def upsert_snapshots(self, records: list[Any]) -> int:
        return self._record(records)

    def upsert_costs(self, records: list[Any]) -> int:
        return self._record(records)

    def upsert_subscription_plans(self, records: list[Any]) -> int:
        return self._record(records)


class FakeClock:
    def __init__(self) -> None:
        self.sleeps: list[float] = []

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
