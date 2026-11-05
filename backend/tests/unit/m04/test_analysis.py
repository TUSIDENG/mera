"""M04 分析路由单测：M09 引擎接入后的正常 / 401 / 422 / 空数据。"""

from __future__ import annotations

from decimal import Decimal

import pytest

from tests.unit.m04.conftest import make_price, make_snapshot


def make_priced_pair(
    model_id: str,
    provider: str,
    benchmark: str,
    input_price: str,
    output_price: str,
    display_name: str,
):
    """榜单快照 + 独立价格行（分表后的线上结构）。"""
    snapshot = make_snapshot(
        model_id=model_id,
        provider=provider,
        benchmark_score=Decimal(benchmark),
        data={"display_name": display_name},
    )
    price = make_price(
        model_id=model_id,
        provider=provider,
        input_price=Decimal(input_price),
        output_price=Decimal(output_price),
    )
    return snapshot, price


def test_run_analysis_ranked(user_client):
    client, repo, _ = user_client
    pairs = [
        make_priced_pair("gpt-4o", "openai", "95.50", "0.000003", "0.000015", "GPT-4o"),
        make_priced_pair(
            "claude-3", "anthropic", "90.00", "0.00000005", "0.0000005", "Claude 3"
        ),
        make_priced_pair("gemini", "google", "80.00", "0.000001", "0.000002", "Gemini"),
    ]
    repo.snapshots = [snapshot for snapshot, _ in pairs]
    repo.prices = [price for _, price in pairs]

    resp = client.post("/api/v1/analysis/run", json={})

    assert resp.status_code == 200
    body = resp.json()
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

    assert ("latest_prices", {}) in repo.calls
    assert ("latest_snapshots", {}) in repo.calls


def test_run_analysis_skips_scoreless_models(user_client):
    """benchmark_score 为 None（无分）的模型不参与排名。"""
    client, repo, _ = user_client
    repo.snapshots = [
        make_snapshot(model_id="scored", benchmark_score=Decimal(90)),
        make_snapshot(model_id="scoreless", benchmark_score=None),
    ]
    repo.prices = [make_price(model_id="scored")]
    resp = client.post("/api/v1/analysis/run", json={})
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] == 1
    assert body["items"][0]["model_id"] == "scored"


def test_run_analysis_unauthorized(anon_client):
    client, _, _ = anon_client
    resp = client.post("/api/v1/analysis/run", json={})
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
    resp = client.post("/api/v1/analysis/run", json={})
    assert resp.status_code == 200
    assert resp.json() == {"items": [], "total": 0}
