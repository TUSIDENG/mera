"""M08 用例：eager 全链路触发注入的 fetcher/repo、策略子集、兜底状态机、worker 装配。"""

from __future__ import annotations

import uuid

import pytest

from app.core.exceptions import CaptchaRequired, ConfigError
from app.db.enums import FetchTaskStatus
from app.fetchers.config_loader import SITES_DIR, load_site
from app.services.enqueue import FETCH_TASK_NAME
from app.tasks.fetch import run_fetch_task, select_site_strategies
from app.worker import celery_app
from tests.unit.m08.conftest import FakeFetcher, make_site, make_task_row


class TestEagerExecution:
    """task_always_eager 模式：delay 即同步执行，断言注入的 fetcher/repo 被触发。"""

    def test_success_full_chain(self, wire_task):
        task = make_task_row()
        fetcher = FakeFetcher()
        env = wire_task(task, make_site([("api", fetcher)]))

        result = run_fetch_task.delay(str(task.id))

        assert result.result == "succeeded"
        assert fetcher.fetch_calls == 1
        assert env.loaded_sites == ["openrouter"]
        assert env.repo.upserts == [("snapshots", 1)]
        assert env.repo.task.status == FetchTaskStatus.SUCCEEDED.value
        assert env.repo.task.fetch_strategy == "openrouter/api"
        assert env.repo.task.hit_count == 1
        assert env.session.commits == 1
        assert env.session.rollbacks == 0
        assert env.session.closed

    def test_task_not_found_returns_none(self, wire_task):
        env = wire_task(None, make_site([("api", FakeFetcher())]))

        result = run_fetch_task.delay(str(uuid.uuid4()))

        assert result.result is None
        assert env.loaded_sites == []  # 任务不存在：不加载站点、不产生写入
        assert env.repo.upserts == []
        assert env.session.commits == 0

    def test_strategy_subset_only_selected_fetcher_runs(self, wire_task):
        task = make_task_row(data={"fetch_strategy": "playwright"})
        api, browser = FakeFetcher(), FakeFetcher()
        env = wire_task(task, make_site([("api", api), ("playwright", browser)]))

        result = run_fetch_task.delay(str(task.id))

        assert result.result == "succeeded"
        assert api.fetch_calls == 0  # 未指定的方案不执行
        assert browser.fetch_calls == 1
        assert env.repo.task.fetch_strategy == "openrouter/playwright"

    def test_undeclared_strategy_fails_fast(self, wire_task):
        task = make_task_row(data={"fetch_strategy": "selenium"})
        env = wire_task(task, make_site([("api", FakeFetcher())]))

        result = run_fetch_task.delay(str(task.id))

        assert result.result is None
        assert env.repo.task.status == FetchTaskStatus.FAILED_EXHAUSTED.value
        assert "selenium" in (env.repo.error_message or "")
        # 配置错配快速失败：running -> failed_exhausted，无退避重试
        assert env.repo.transitions == ["running", "failed_exhausted"]

    def test_unexpected_exception_marks_failed_exhausted(self, wire_task):
        task = make_task_row()
        fetcher = FakeFetcher(error=RuntimeError("boom"))
        env = wire_task(task, make_site([("api", fetcher)]))

        result = run_fetch_task.delay(str(task.id))

        assert result.result is None  # 不裸抛，broker 层不会无限重投
        assert env.repo.task.status == FetchTaskStatus.FAILED_EXHAUSTED.value
        assert "RuntimeError" in (env.repo.error_message or "")
        assert env.repo.transitions == ["running", "failed_exhausted"]
        assert env.session.rollbacks == 1
        assert env.session.commits == 1  # 兜底标记在新事务单独提交

    def test_captcha_passthrough_without_fallback(self, wire_task):
        task = make_task_row()
        fetcher = FakeFetcher(error=CaptchaRequired("目标站点要求验证码"))
        env = wire_task(task, make_site([("api", fetcher)]))

        result = run_fetch_task.delay(str(task.id))

        assert result.result == "captcha_pending"
        assert env.repo.task.status == FetchTaskStatus.CAPTCHA_PENDING.value
        assert env.repo.transitions == ["running", "captcha_pending"]
        assert env.session.commits == 1

    def test_terminal_task_redelivery_is_noop(self, wire_task):
        """幂等：终态任务重复投递时状态机拒绝 running 迁移，兜底仅记日志。"""
        task = make_task_row(
            status=FetchTaskStatus.SUCCEEDED.value,
            hit_count=5,
            fetch_strategy="openrouter/api",
        )
        fetcher = FakeFetcher()
        env = wire_task(task, make_site([("api", fetcher)]))

        result = run_fetch_task.delay(str(task.id))

        assert result.result is None
        assert fetcher.fetch_calls == 0
        assert env.repo.task.status == FetchTaskStatus.SUCCEEDED.value
        assert env.repo.task.hit_count == 5
        assert env.repo.upserts == []


class TestWorkerAssembly:
    def test_fetch_task_registered(self):
        assert FETCH_TASK_NAME in celery_app.tasks

    def test_fallback_route_default_queue(self):
        # 生产者已按策略显式指定队列（M04 覆盖），worker 侧仅兜底 default
        assert celery_app.conf.task_routes[FETCH_TASK_NAME]["queue"] == "default"

    def test_beat_schedule_empty(self):
        assert celery_app.conf.beat_schedule == {}


class TestSelectSiteStrategies:
    def test_none_returns_full_site(self):
        site = make_site([("api", FakeFetcher())])
        assert select_site_strategies(site, None) is site

    def test_filters_to_declared_subset(self):
        site = make_site(
            [("api", FakeFetcher())],
            strategies=["api", "playwright"],
            skipped=[("playwright", "方案文件缺失: playwright.py")],
        )
        selected = select_site_strategies(site, "playwright")
        assert selected.strategies == ["playwright"]
        assert selected.fetchers == []
        assert selected.skipped == [("playwright", "方案文件缺失: playwright.py")]

    def test_undeclared_strategy_raises(self):
        with pytest.raises(ConfigError):
            select_site_strategies(make_site([("api", FakeFetcher())]), "selenium")


class TestOpenRouterSiteSmoke:
    def test_real_config_loads_api_strategy(self):
        site = load_site(SITES_DIR, "openrouter")
        assert site.strategies == ["api"]
        assert [name for name, _ in site.fetchers] == ["api"]
        assert site.skipped == []
