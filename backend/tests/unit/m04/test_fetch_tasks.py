"""M04 采集任务路由单测。"""

from __future__ import annotations


def test_create_task_accepted(user_client):
    client, repo, enqueuer = user_client
    resp = client.post(
        "/api/v1/fetch-tasks",
        json={
            "task_type": "model_metrics",
            "source_key": "openrouter",
            "domain": "coding",
            "fetch_strategy": "api",
        },
    )
    assert resp.status_code == 202
    body = resp.json()
    assert body["task_type"] == "model_metrics"
    params = repo.created_task_params
    assert params.task_type == "model_metrics"
    assert params.triggered_by == "user-1"
    assert params.auto_start is True
    assert params.data == {"fetch_strategy": "api"}
    assert len(enqueuer.enqueued) == 1
    assert enqueuer.enqueued[0][1] == "api"


def test_create_task_default_strategy(user_client):
    client, _, enqueuer = user_client
    resp = client.post(
        "/api/v1/fetch-tasks",
        json={"task_type": "api_price", "source_key": "openrouter"},
    )
    assert resp.status_code == 202
    assert enqueuer.enqueued[0][1] is None


def test_create_task_type_not_supported_by_site_422(user_client):
    """openrouter 未声明 infrastructure_cost 能力，语义错配的任务被拒。"""
    client, _, _ = user_client
    resp = client.post(
        "/api/v1/fetch-tasks",
        json={"task_type": "infrastructure_cost", "source_key": "openrouter"},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "invalid_task_type"


def test_create_task_unknown_source_422(user_client):
    client, _, _ = user_client
    resp = client.post(
        "/api/v1/fetch-tasks",
        json={"task_type": "model_metrics", "source_key": "no-such-site"},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "unknown_source"


def test_create_task_invalid_type_422(user_client):
    client, _, _ = user_client
    resp = client.post(
        "/api/v1/fetch-tasks",
        json={"task_type": "bad_type", "source_key": "openrouter"},
    )
    assert resp.status_code == 422


def test_create_task_unauthorized(anon_client):
    client, _, _ = anon_client
    resp = client.post(
        "/api/v1/fetch-tasks",
        json={"task_type": "model_metrics", "source_key": "openrouter"},
    )
    assert resp.status_code == 401


def test_list_tasks_ok(user_client):
    client, repo, _ = user_client
    resp = client.get("/api/v1/fetch-tasks", params={"status": "pending"})
    assert resp.status_code == 200
    assert resp.json()["total"] == 1
    assert repo.calls[0][1] == {"status": "pending", "limit": 20, "offset": 0}


def test_list_tasks_unauthorized(anon_client):
    client, _, _ = anon_client
    assert client.get("/api/v1/fetch-tasks").status_code == 401
