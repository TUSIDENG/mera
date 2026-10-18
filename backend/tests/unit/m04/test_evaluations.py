"""M04 用户评测路由单测。"""

from __future__ import annotations


def test_create_evaluation_ok(user_client):
    client, repo, _ = user_client
    resp = client.post(
        "/api/v1/evaluations",
        json={"domain": "coding", "snapshot_used_ids": [], "data": {"note": "x"}},
    )
    assert resp.status_code == 201
    kwargs = repo.created_evaluation_kwargs
    assert kwargs["org_id"] == "main"
    assert kwargs["user_id"] == "user-1"
    assert kwargs["domain"] == "coding"


def test_create_evaluation_missing_domain_422(user_client):
    client, _, _ = user_client
    resp = client.post("/api/v1/evaluations", json={})
    assert resp.status_code == 422


def test_create_evaluation_unauthorized(anon_client):
    client, _, _ = anon_client
    resp = client.post("/api/v1/evaluations", json={"domain": "coding"})
    assert resp.status_code == 401


def test_list_evaluations_ok(user_client):
    client, repo, _ = user_client
    resp = client.get("/api/v1/evaluations")
    assert resp.status_code == 200
    assert resp.json()["items"][0]["user_id"] == "user-1"
    assert repo.calls[0][1]["user_id"] == "user-1"


def test_list_evaluations_unauthorized(anon_client):
    client, _, _ = anon_client
    assert client.get("/api/v1/evaluations").status_code == 401
