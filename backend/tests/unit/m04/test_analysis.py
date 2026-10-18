"""M04 分析路由单测：M09 就绪前 501 占位。"""

from __future__ import annotations


def test_run_analysis_not_implemented(user_client):
    client, _, _ = user_client
    resp = client.post("/api/v1/analysis/run")
    assert resp.status_code == 501
    assert resp.json()["code"] == "not_implemented"


def test_run_analysis_unauthorized(anon_client):
    client, _, _ = anon_client
    assert client.post("/api/v1/analysis/run").status_code == 401
