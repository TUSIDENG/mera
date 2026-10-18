"""M04 内网回调路由单测：X-Internal-Token 鉴权与终态分流。"""

from __future__ import annotations

import uuid

from tests.unit.m04.conftest import INTERNAL_TOKEN, build_client


def _post_callback(client, task_id: uuid.UUID, body: dict, token: str | None = INTERNAL_TOKEN):
    headers = {"X-Internal-Token": token} if token is not None else {}
    return client.post(f"/internal/fetch/callback/{task_id}", json=body, headers=headers)


def test_callback_succeeded():
    client, repo, _ = build_client()
    resp = _post_callback(
        client,
        uuid.uuid4(),
        {"result": "succeeded", "strategy": "api", "hit_count": 10},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "succeeded"
    call = next(c for c in repo.calls if c[0] == "mark_succeeded")
    assert call[1]["strategy"] == "api"
    assert call[1]["hit_count"] == 10
    assert call[1]["min_hits"] == 1


def test_callback_partial_succeeded():
    client, _, _ = build_client()
    resp = _post_callback(
        client,
        uuid.uuid4(),
        {"result": "partial_succeeded", "strategy": "reverse_api", "hit_count": 3},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "partial_succeeded"


def test_callback_failed_exhausted():
    client, repo, _ = build_client()
    resp = _post_callback(
        client,
        uuid.uuid4(),
        {"result": "failed_exhausted", "error_message": "all strategies failed"},
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "failed_exhausted"
    call = next(c for c in repo.calls if c[0] == "mark_failed_exhausted")
    assert call[1]["error_message"] == "all strategies failed"


def test_callback_captcha_pending():
    client, _, _ = build_client()
    resp = _post_callback(client, uuid.uuid4(), {"result": "captcha_pending"})
    assert resp.status_code == 200
    assert resp.json()["status"] == "captcha_pending"


def test_callback_task_not_found():
    client, repo, _ = build_client()
    repo.task = None
    resp = _post_callback(
        client, uuid.uuid4(), {"result": "succeeded", "hit_count": 1}
    )
    assert resp.status_code == 404
    assert resp.json()["code"] == "not_found"


def test_callback_missing_token():
    client, _, _ = build_client()
    resp = _post_callback(
        client, uuid.uuid4(), {"result": "succeeded", "hit_count": 1}, token=None
    )
    assert resp.status_code == 401


def test_callback_wrong_token():
    client, _, _ = build_client()
    resp = _post_callback(
        client, uuid.uuid4(), {"result": "succeeded", "hit_count": 1}, token="wrong"
    )
    assert resp.status_code == 401


def test_callback_invalid_result_422():
    client, _, _ = build_client()
    resp = _post_callback(client, uuid.uuid4(), {"result": "running"})
    assert resp.status_code == 422


def test_callback_negative_hit_count_422():
    client, _, _ = build_client()
    resp = _post_callback(
        client, uuid.uuid4(), {"result": "succeeded", "hit_count": -1}
    )
    assert resp.status_code == 422
