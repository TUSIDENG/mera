"""M04 订阅套餐查询路由单测。"""

from __future__ import annotations


def test_list_plans_ok(user_client):
    client, repo, _ = user_client
    resp = client.get("/api/v1/subscription-plans", params={"provider": "openai"})
    assert resp.status_code == 200
    assert resp.json()["items"][0]["plan_key"] == "pro"
    assert repo.calls[0][1] == {
        "provider": "openai",
        "active_only": True,
        "limit": 20,
        "offset": 0,
    }


def test_list_plans_page_size_limit_422(user_client):
    client, _, _ = user_client
    resp = client.get("/api/v1/subscription-plans", params={"page_size": 101})
    assert resp.status_code == 422


def test_list_plans_unauthorized(anon_client):
    client, _, _ = anon_client
    assert client.get("/api/v1/subscription-plans").status_code == 401
