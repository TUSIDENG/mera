"""M04 采集任务入队：生产者侧 send_task，按策略名路由到站点队列。

队列分工（架构文档）：default 双 worker 冗余、fetch_api 仅 worker-1、
fetch_browser 仅 worker-2；M08 worker 侧 autoretry 为最终兜底。
"""

from __future__ import annotations

import uuid

from celery import Celery

from app.core.config import Settings

FETCH_TASK_NAME = "app.tasks.fetch.run_fetch_task"

_QUEUE_BY_STRATEGY = {
    "api": "fetch_api",
    "reverse_api": "fetch_api",
    "playwright": "fetch_browser",
}


def queue_for_strategy(strategy: str | None) -> str:
    """按采集策略选择队列；未指定策略时走 default（worker 编排层自行降级）。"""
    if strategy is None:
        return "default"
    return _QUEUE_BY_STRATEGY.get(strategy, "default")


class FetchTaskEnqueuer:
    """懒加载 Celery 客户端的任务入队器；测试以 dependency_overrides 替换。"""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._celery: Celery | None = None

    def _get_celery(self) -> Celery:
        if self._celery is None:
            self._celery = Celery(
                "mera-producer",
                broker=self._settings.broker_url,
                backend=self._settings.result_backend,
            )
        return self._celery

    def enqueue(self, task_id: uuid.UUID, *, strategy: str | None = None) -> str:
        """入队并返回队列名；countdown=1 缓解"先入队后提交"的读取竞态。"""
        queue = queue_for_strategy(strategy)
        self._get_celery().send_task(
            FETCH_TASK_NAME,
            args=[str(task_id)],
            queue=queue,
            countdown=1,
        )
        return queue
