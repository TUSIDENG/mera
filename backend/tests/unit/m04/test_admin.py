"""M04 管理端路由单测（mera-admin 角色）。"""

from __future__ import annotations

from app.db.enums import FetchTaskStatus
from tests.unit.m04.conftest import make_task


def test_admin_list_plans_ok(admin_client):
    client, repo, _ = admin_client
    resp = client.get("/api/v1/admin/subscription-plans")
    assert resp.status_code == 200
    assert repo.calls[0][1]["active_only"] is False


def test_admin_list_plans_forbidden(user_client):
    client, _, _ = user_client
    resp = client.get("/api/v1/admin/subscription-plans")
    assert resp.status_code == 403
    assert resp.json()["code"] == "forbidden"


def test_admin_routes_unauthorized(anon_client):
    client, _, _ = anon_client
    assert client.get("/api/v1/admin/subscription-plans").status_code == 401


def test_admin_put_plan_ok(admin_client):
    client, repo, _ = admin_client
    resp = client.put(
        "/api/v1/admin/subscription-plans/openai/pro/monthly",
        json={"plan_name": "Pro", "monthly_price": "20.00"},
    )
    assert resp.status_code == 200
    assert resp.json()["plan_key"] == "pro"
    upsert = [c for c in repo.calls if c[0] == "upsert_subscription_plans"]
    assert len(upsert) == 1
    record = upsert[0][1]["records"][0]
    assert record.provider == "openai"
    assert record.source == "manual"


def test_admin_put_plan_invalid_cycle_422(admin_client):
    client, _, _ = admin_client
    resp = client.put(
        "/api/v1/admin/subscription-plans/openai/pro/weekly",
        json={"plan_name": "Pro", "monthly_price": "20.00"},
    )
    assert resp.status_code == 422


def test_admin_put_plan_negative_price_422(admin_client):
    client, _, _ = admin_client
    resp = client.put(
        "/api/v1/admin/subscription-plans/openai/pro/monthly",
        json={"plan_name": "Pro", "monthly_price": "-1"},
    )
    assert resp.status_code == 422


def test_admin_put_plan_forbidden(user_client):
    client, _, _ = user_client
    resp = client.put(
        "/api/v1/admin/subscription-plans/openai/pro/monthly",
        json={"plan_name": "Pro", "monthly_price": "20.00"},
    )
    assert resp.status_code == 403


def test_admin_list_costs_ok(admin_client):
    client, repo, _ = admin_client
    resp = client.get("/api/v1/admin/infrastructure-costs", params={"cost_type": "gpu_rental"})
    assert resp.status_code == 200
    assert repo.calls[0][1]["cost_type"] == "gpu_rental"


def test_admin_list_costs_invalid_type_422(admin_client):
    client, _, _ = admin_client
    resp = client.get("/api/v1/admin/infrastructure-costs", params={"cost_type": "bad"})
    assert resp.status_code == 422


def test_admin_put_cost_ok(admin_client):
    client, repo, _ = admin_client
    resp = client.put(
        "/api/v1/admin/infrastructure-costs/gpu_rental/A100%2080G",
        json={"unit": "hour", "unit_price": "2.5"},
    )
    assert resp.status_code == 200
    upsert = [c for c in repo.calls if c[0] == "upsert_costs"]
    assert len(upsert) == 1
    record = upsert[0][1]["records"][0]
    assert record.region == "default"


def test_admin_put_cost_invalid_type_422(admin_client):
    client, _, _ = admin_client
    resp = client.put(
        "/api/v1/admin/infrastructure-costs/bad/x",
        json={"unit": "hour", "unit_price": "2.5"},
    )
    assert resp.status_code == 422


def test_retrigger_ok(admin_client):
    client, repo, enqueuer = admin_client
    repo.task = make_task(
        status=FetchTaskStatus.FAILED_EXHAUSTED.value,
        hit_count=0,
        fetch_strategy="playwright",
    )
    resp = client.post(f"/api/v1/admin/fetch-tasks/{repo.task.id}/retrigger")
    assert resp.status_code == 202
    params = repo.created_task_params
    assert params.task_type == "model_metrics"
    assert params.data["retrigger_of"] == str(repo.task.id)
    assert params.data["fetch_strategy"] == "playwright"
    assert enqueuer.enqueued[0][1] == "playwright"


def test_retrigger_not_found(admin_client):
    client, repo, _ = admin_client
    repo.task = None
    resp = client.post("/api/v1/admin/fetch-tasks/00000000-0000-0000-0000-000000000000/retrigger")
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


def test_retrigger_conflict(admin_client):
    client, repo, _ = admin_client
    repo.task = make_task(status=FetchTaskStatus.RUNNING.value)
    resp = client.post(f"/api/v1/admin/fetch-tasks/{repo.task.id}/retrigger")
    assert resp.status_code == 409
    assert resp.json()["code"] == "invalid_transition"


def test_retrigger_forbidden(user_client):
    client, repo, _ = user_client
    repo.task = make_task(status=FetchTaskStatus.FAILED_EXHAUSTED.value)
    resp = client.post(f"/api/v1/admin/fetch-tasks/{repo.task.id}/retrigger")
    assert resp.status_code == 403
