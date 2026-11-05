"""M05 用例④：run_fetch 状态机全分支（FakeFetcher/FakeTask/MockRepo/FakeClock）。"""

from __future__ import annotations

from decimal import Decimal

from fakes import FakeClock, FakeFetcher, FakeTask, MockRepo

from app.core.exceptions import CaptchaRequired, FetchFailed
from app.db.enums import FetchTaskStatus as Status
from app.fetchers.orchestrator import RepoTaskHandle, run_fetch
from app.repositories.dto import SnapshotRecord


def dto(model: str = "m1") -> SnapshotRecord:
    return SnapshotRecord(
        model_id=model, provider="p", domain="general", benchmark_score=Decimal(1)
    )


class FakeSite:
    """模拟 config_loader.SiteConfig：携带 skipped 列表的方案链。"""

    def __init__(self, pairs, skipped=None, key="fakesite"):
        self._pairs = pairs
        self.skipped = skipped or []
        self.key = key

    def __iter__(self):
        return iter(self._pairs)


def run(task, fetchers, repo, clock, **kwargs):
    kwargs.setdefault("backoff_base_seconds", 1.0)
    return run_fetch(task, fetchers, repo, clock, **kwargs)


class TestHitPaths:
    def test_first_strategy_success(self):
        task, repo, clock = FakeTask(), MockRepo(hit_count=2), FakeClock()
        first = FakeFetcher(records=[dto(), dto("m2")])
        second = FakeFetcher(records=[dto("m3")])
        result = run(task, [("api", first), ("playwright", second)], repo, clock)
        assert task.final == "succeeded"
        assert task.transitions[-1][1] == {"strategy": "fakesite/api", "hit_count": 2}
        assert repo.calls == 1
        assert second.fetch_calls == 0  # 命中即止
        assert clock.sleeps == []
        assert result.status == Status.SUCCEEDED
        assert result.hit_strategy == "fakesite/api"

    def test_fallback_success_after_fetch_failed(self):
        task, repo, clock = FakeTask(), MockRepo(hit_count=1), FakeClock()
        first = FakeFetcher(error=FetchFailed("HTTP 403"))
        second = FakeFetcher(records=[dto()])
        run(task, [("reverse_api", first), ("playwright", second)], repo, clock)
        assert task.final == "succeeded"
        assert task.failures == [("reverse_api", "HTTP 403")]
        assert task.transitions[-1][1]["strategy"] == "fakesite/playwright"

    def test_unavailable_strategy_skipped_with_reason(self):
        task, repo, clock = FakeTask(), MockRepo(hit_count=1), FakeClock()
        first = FakeFetcher(available=False, reason="缺少授权密钥（env:AA_SECRET）")
        second = FakeFetcher(records=[dto()])
        run(task, [("reverse_api", first), ("playwright", second)], repo, clock)
        assert task.final == "succeeded"
        assert task.skips == [("reverse_api", "缺少授权密钥（env:AA_SECRET）")]
        assert first.fetch_calls == 0  # 不可用方案不发起请求

    def test_missing_file_strategy_recorded_skipped(self):
        task, repo, clock = FakeTask(), MockRepo(hit_count=1), FakeClock()
        site = FakeSite(
            [("api", FakeFetcher(records=[dto()]))],
            skipped=[("playwright", "方案文件缺失: playwright.py")],
        )
        run(task, site, repo, clock)
        assert task.skips == [("playwright", "方案文件缺失: playwright.py")]
        assert task.final == "succeeded"

    def test_skip_and_failure_mixed_then_success(self):
        task, repo, clock = FakeTask(), MockRepo(hit_count=1), FakeClock()
        pairs = [
            ("api", FakeFetcher(available=False, reason="无登录会话")),
            ("reverse_api", FakeFetcher(error=FetchFailed("HTTP 500"))),
            ("playwright", FakeFetcher(records=[dto()])),
        ]
        run(task, pairs, repo, clock)
        assert task.final == "succeeded"
        assert task.skips == [("api", "无登录会话")]
        assert task.failures == [("reverse_api", "HTTP 500")]

    def test_empty_normalize_falls_through(self):
        task, repo, clock = FakeTask(), MockRepo(hit_count=1), FakeClock()
        first = FakeFetcher(records=[])  # normalize 空结果 -> 未命中
        second = FakeFetcher(records=[dto()])
        run(task, [("api", first), ("playwright", second)], repo, clock)
        assert task.final == "succeeded"
        assert task.empties == ["api"]


class TestTerminalRouting:
    def test_all_skipped_zero_hit_failed_exhausted_after_retries(self):
        task, repo, clock = FakeTask(), MockRepo(), FakeClock()
        pairs = [
            ("api", FakeFetcher(available=False, reason="缺密钥")),
            ("playwright", FakeFetcher(available=False, reason="未安装 playwright")),
        ]
        result = run(task, pairs, repo, clock, max_attempts=3)
        assert task.final == "failed_exhausted"
        assert result.hit_count == 0
        assert repo.calls == 0  # 0 条记录不落库
        assert len(task.skips) == 2  # 跳过原因只在首轮记录
        assert task.attempt_count == 3  # 每次尝试回写 attempt_count

    def test_max_attempts_with_hits_partial_succeeded(self):
        task = FakeTask(attempt_count=2)  # 已尝试 2 次，本轮到顶
        repo, clock = MockRepo(hit_count=2), FakeClock()
        result = run(task, [("api", FakeFetcher(records=[dto(), dto("m2")]))], repo, clock)
        assert task.final == "partial_succeeded"
        assert task.transitions[-1][1]["hit_count"] == 2
        assert clock.sleeps == []  # 部分成功不熔断、不再重试
        assert result.status == Status.PARTIAL_SUCCEEDED
        assert task.attempt_count == 3  # 既有 2 次 + 本轮 1 次

    def test_max_attempts_zero_hit_failed_exhausted(self):
        task = FakeTask(attempt_count=2)
        repo, clock = MockRepo(), FakeClock()
        run(
            task,
            [("api", FakeFetcher(error=FetchFailed("HTTP 500")))],
            repo,
            clock,
        )
        assert task.final == "failed_exhausted"
        assert task.transitions[-1][1]["error"] == "HTTP 500"
        assert clock.sleeps == []

    def test_truncated_partial_succeeded(self):
        task, repo, clock = FakeTask(), MockRepo(hit_count=2), FakeClock()
        fetcher = FakeFetcher(records=[dto(), dto("m2")], truncated=True)
        result = run(task, [("api", fetcher)], repo, clock)
        assert task.final == "partial_succeeded"
        assert result.truncated is True

    def test_captcha_short_circuits(self):
        task, repo, clock = FakeTask(), MockRepo(), FakeClock()
        first = FakeFetcher(error=CaptchaRequired("captcha"))
        second = FakeFetcher(records=[dto()])
        result = run(task, [("api", first), ("playwright", second)], repo, clock)
        assert task.final == "captcha_pending"
        assert second.fetch_calls == 0  # 不再降级
        assert repo.calls == 0
        assert clock.sleeps == []
        assert result.status == Status.CAPTCHA_PENDING


class TestRetryBackoff:
    def test_exponential_backoff_and_retry_transitions(self):
        task, repo, clock = FakeTask(), MockRepo(), FakeClock()
        fetcher = FakeFetcher(error=FetchFailed("HTTP 500"))
        run(task, [("api", fetcher)], repo, clock, max_attempts=3, backoff_base_seconds=10)
        assert clock.sleeps == [10.0, 20.0]  # 指数退避：base * 2^(attempt-1)
        names = [name for name, _ in task.transitions]
        assert names == [
            "running",
            "retry_pending",
            "running",
            "retry_pending",
            "running",
            "failed_exhausted",
        ]
        assert fetcher.fetch_calls == 3  # 每轮重试都会重新请求

    def test_success_after_retry(self):
        task, clock = FakeTask(), FakeClock()
        repo = MockRepo(hit_count=1)
        flaky = FlakyFetcher(fail_times=2)
        result = run(task, [("api", flaky)], repo, clock, max_attempts=3)
        # 第 3 次尝试才命中：已到最大尝试次数，按 M02 共享规则置 partial_succeeded。
        assert task.final == "partial_succeeded"
        assert clock.sleeps == [1.0, 2.0]
        assert result.attempts == 3


class FlakyFetcher(FakeFetcher):
    """前 fail_times 次抛 FetchFailed，之后返回记录。"""

    def __init__(self, fail_times: int):
        super().__init__(records=[dto()])
        self._fail_times = fail_times

    def fetch(self):
        self.fetch_calls += 1
        if self.fetch_calls <= self._fail_times:
            raise FetchFailed("HTTP 500")
        return self._records


class TestRepoTaskHandle:
    def test_delegates_state_transitions_and_logs_events(self):
        calls: list[tuple] = []

        class StubRepo:
            def get_task(self, task_id):
                return type("T", (), {"attempt_count": 2})()

            def __getattr__(self, name):
                return lambda *a, **kw: calls.append((name, a, kw))

        handle = RepoTaskHandle(StubRepo(), "task-id")
        assert handle.attempt_count == 2
        handle.mark_running()
        handle.mark_succeeded(strategy="s/api", hit_count=3)
        handle.log_skip("api", "缺密钥")
        assert ("mark_running", ("task-id",), {}) in calls
        assert (
            "mark_succeeded",
            ("task-id",),
            {"strategy": "s/api", "hit_count": 3},
        ) in calls
        assert handle.event_log == [("skipped", "api", "缺密钥")]
