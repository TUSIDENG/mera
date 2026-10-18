"""M04 装配单测：OpenAPI 可访问、关键路径注册、入队队列映射。"""

from __future__ import annotations

from app.services.enqueue import FETCH_TASK_NAME, queue_for_strategy
from tests.unit.m04.conftest import build_client


def test_openapi_accessible():
    client, _, _ = build_client()
    resp = client.get("/openapi.json")
    assert resp.status_code == 200
    paths = resp.json()["paths"]
    assert "/api/v1/models" in paths
    assert "/api/v1/fetch-tasks" in paths
    assert "/api/v1/evaluations" in paths
    assert "/api/v1/subscription-plans" in paths
    assert "/api/v1/analysis/run" in paths
    assert "/api/v1/admin/subscription-plans" in paths
    assert "/internal/fetch/callback/{fetch_task_id}" in paths


def test_fetch_task_name_stable():
    # M08 worker 侧任务名契约，改动需同步
    assert FETCH_TASK_NAME == "app.tasks.fetch.run_fetch_task"


def test_queue_for_strategy_mapping():
    assert queue_for_strategy("api") == "fetch_api"
    assert queue_for_strategy("reverse_api") == "fetch_api"
    assert queue_for_strategy("playwright") == "fetch_browser"
    assert queue_for_strategy(None) == "default"
    assert queue_for_strategy("unknown") == "default"
