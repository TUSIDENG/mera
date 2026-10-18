"""M04 模型榜单路由单测。"""

from __future__ import annotations


def test_list_models_ok(user_client):
    client, repo, _ = user_client
    resp = client.get("/api/v1/models", params={"domain": "coding"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["page"] == 1
    assert body["page_size"] == 20
    assert body["items"][0]["model_id"] == "gpt-4o"
    assert repo.calls[0] == ("list_snapshots", {"domain": "coding", "limit": 20, "offset": 0})


def test_list_models_pagination(user_client):
    client, repo, _ = user_client
    resp = client.get(
        "/api/v1/models", params={"domain": "coding", "page": 2, "page_size": 5}
    )
    assert resp.status_code == 200
    assert repo.calls[0][1]["limit"] == 5
    assert repo.calls[0][1]["offset"] == 5


def test_list_models_missing_domain_422(user_client):
    client, _, _ = user_client
    assert client.get("/api/v1/models").status_code == 422


def test_list_models_invalid_page_422(user_client):
    client, _, _ = user_client
    resp = client.get("/api/v1/models", params={"domain": "coding", "page_size": 0})
    assert resp.status_code == 422


def test_list_models_unauthorized(anon_client):
    client, _, _ = anon_client
    resp = client.get("/api/v1/models", params={"domain": "coding"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "auth_error"


def test_model_snapshots_ok(user_client):
    client, repo, _ = user_client
    resp = client.get("/api/v1/models/gpt-4o/snapshots")
    assert resp.status_code == 200
    assert resp.json()[0]["domain"] == "coding"
    assert repo.calls[0] == ("snapshots_by_model", {"model_id": "gpt-4o"})
