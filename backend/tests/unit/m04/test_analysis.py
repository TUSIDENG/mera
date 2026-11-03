"""M04 分析路由单测：M09 引擎接入后的正常 / 401 / 422 / 空数据。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.unit.m04.conftest import make_snapshot


def make_priced_snapshot(
    model_id: str,
    provider: str,
    benchmark: str,
    input_price: str,
    output_price: str,
    display_name: str,
):
    """构造带每 token 单价的快照（价格与线上数据结构一致，均为字符串）。"""
    return make_snapshot(
        model_id=model_id,
        provider=provider,
        benchmark_score=Decimal(benchmark),
        data={
            "input_price": input_price,
            "output_price": output_price,
            "display_name": display_name,
        },
    )


def test_run_analysis_ranked(user_client):
    client, repo, _ = user_client
    repo.snapshots = [
        make_priced_snapshot(
            "gpt-4o", "openai", "95.50", "0.000003", "0.000015", "GPT-4o"
        ),
        make_priced_snapshot(
            "claude-3", "anthropic", "90.00", "0.00000005", "0.0000005", "Claude 3"
        ),
        make_priced_snapshot(
            "gemini", "google", "80.00", "0.000001", "0.000002", "Gemini"
        ),
    ]

    resp = client.post("/api/v1/analysis/run", json={"domain": "coding"})

    assert resp.status_code == 200
    body = resp.json()
    assert body["domain"] == "coding"
    assert body["total"] == 3
    assert [item["model_id"] for item in body["items"]] == [
        "claude-3",
        "gpt-4o",
        "gemini",
    ]
    assert [item["rank"] for item in body["items"]] == [1, 2, 3]

    first = body["items"][0]
    assert first["provider"] == "anthropic"
    assert first["display_name"] == "Claude 3"
    assert first["monthly_cost"] == pytest.approx(0.185)
    assert first["benchmark_norm"] == pytest.approx(0.645161, abs=1e-6)
    assert first["price_norm"] == pytest.approx(1.0)
    assert first["composite_score"] == pytest.approx(0.787097, abs=1e-6)
    assert body["items"][1]["monthly_cost"] == pytest.approx(6.6)
    assert body["items"][2]["monthly_cost"] == pytest.approx(1.3)

    assert repo.calls[0] == ("latest_snapshots", {"domain": "coding"})


def test_run_analysis_unauthorized(anon_client):
    client, _, _ = anon_client
    resp = client.post("/api/v1/analysis/run", json={"domain": "coding"})
    assert resp.status_code == 401
    assert resp.json()["code"] == "auth_error"


def test_run_analysis_invalid_weights_422(user_client):
    client, _, _ = user_client
    resp = client.post(
        "/api/v1/analysis/run",
        json={"benchmark_weight": 0.6, "price_weight": 0.5},
    )
    assert resp.status_code == 422
    assert resp.json()["code"] == "invalid_weights"


def test_run_analysis_empty_snapshots(user_client):
    client, repo, _ = user_client
    repo.snapshots = []
    resp = client.post("/api/v1/analysis/run", json={"domain": "coding"})
    assert resp.status_code == 200
    assert resp.json() == {"domain": "coding", "items": [], "total": 0}
