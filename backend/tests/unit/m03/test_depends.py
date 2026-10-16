"""M03 FastAPI 依赖单测：get_current_identity 各 401 分支与 get_db_session RLS 注入。"""

from __future__ import annotations

from typing import Annotated, Any

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from app.api.depends import get_current_identity, get_db_session
from app.core.config import Settings
from app.core.security import Identity, JwksCache
from app.main import create_app
from tests.unit.m03.conftest import AUDIENCE, ISSUER, make_token

NOW = 1_700_000_000.0


def _make_settings(**overrides: Any) -> Settings:
    values: dict[str, Any] = {
        "database_url": "sqlite://",
        "redis_url": "redis://localhost:6379/0",
        "casdoor_endpoint": ISSUER,
        "casdoor_client_id": AUDIENCE,
    }
    values.update(overrides)
    return Settings(_env_file=None, **values)


def _stub_jwks_cache(monkeypatch: pytest.MonkeyPatch, jwks: dict[str, Any]) -> None:
    """替换启动 JWKS 拉取为本地 keyset，避免测试触网。"""

    def factory(url: str, ttl_seconds: int = 3600) -> JwksCache:
        return JwksCache(url, ttl_seconds=ttl_seconds, fetcher=lambda _url: jwks)

    monkeypatch.setattr("app.main.JwksCache", factory)


def _build_app(monkeypatch: pytest.MonkeyPatch, jwks: dict[str, Any], **overrides: Any) -> FastAPI:
    _stub_jwks_cache(monkeypatch, jwks)
    app = create_app(_make_settings(**overrides))

    @app.get("/whoami")
    def whoami(identity: Annotated[Identity, Depends(get_current_identity)]) -> dict[str, Any]:
        return {
            "user_id": identity.user_id,
            "org_id": identity.org_id,
            "roles": list(identity.roles),
        }

    return app


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch, jwks: dict[str, Any]) -> TestClient:
    return TestClient(_build_app(monkeypatch, jwks))


def test_valid_bearer_token_returns_identity(client: TestClient, rsa_private_key: Any) -> None:
    token = make_token(rsa_private_key)

    response = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json() == {"user_id": "user-1", "org_id": "org-1", "roles": ["user", "admin"]}


def test_missing_authorization_header_returns_401(client: TestClient) -> None:
    response = client.get("/whoami")

    assert response.status_code == 401
    assert response.json()["code"] == "auth_error"


def test_non_bearer_scheme_returns_401(client: TestClient) -> None:
    response = client.get("/whoami", headers={"Authorization": "Token abc"})

    assert response.status_code == 401


def test_empty_bearer_token_returns_401(client: TestClient) -> None:
    response = client.get("/whoami", headers={"Authorization": "Bearer "})

    assert response.status_code == 401


def test_expired_token_returns_401(client: TestClient, rsa_private_key: Any) -> None:
    token = make_token(rsa_private_key, now=NOW - 10_000)

    response = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_wrong_audience_token_returns_401(client: TestClient, rsa_private_key: Any) -> None:
    token = make_token(rsa_private_key, aud="another-client")

    response = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_tampered_signature_returns_401(client: TestClient, other_private_key: Any) -> None:
    token = make_token(other_private_key)

    response = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401


def test_issuer_override_for_split_endpoint(
    monkeypatch: pytest.MonkeyPatch, jwks: dict[str, Any], rsa_private_key: Any
) -> None:
    """容器内外地址不一致（多环境常见）：endpoint 走内网，token iss 为外部地址。"""
    app = _build_app(
        monkeypatch,
        jwks,
        casdoor_endpoint="http://casdoor-internal:8000",
        casdoor_issuer=ISSUER,
    )
    token = make_token(rsa_private_key)

    response = TestClient(app).get("/whoami", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 200
    assert response.json()["user_id"] == "user-1"


def test_casdoor_not_configured_returns_401(
    monkeypatch: pytest.MonkeyPatch, jwks: dict[str, Any], rsa_private_key: Any
) -> None:
    app = _build_app(monkeypatch, jwks, casdoor_endpoint=None, casdoor_client_id=None)
    token = make_token(rsa_private_key)

    response = TestClient(app).get("/whoami", headers={"Authorization": f"Bearer {token}"})

    assert response.status_code == 401
    assert response.json()["code"] == "auth_error"


def test_get_db_session_injects_rls_context(
    monkeypatch: pytest.MonkeyPatch, jwks: dict[str, Any]
) -> None:
    _stub_jwks_cache(monkeypatch, jwks)
    app = create_app(_make_settings())

    recorded: dict[str, str] = {}

    def fake_set_rls_context(session: Session, *, user_id: str, org_id: str, role: str = "authenticated_users") -> None:
        recorded["user_id"] = user_id
        recorded["org_id"] = org_id

    monkeypatch.setattr("app.api.depends.set_rls_context", fake_set_rls_context)
    app.dependency_overrides[get_current_identity] = lambda: Identity(user_id="user-1", org_id="org-1")

    @app.get("/db-ping")
    def db_ping(session: Annotated[Session, Depends(get_db_session)]) -> dict[str, Any]:
        return {"ok": session.execute(text("SELECT 1")).scalar() == 1}

    response = TestClient(app).get("/db-ping")

    assert response.status_code == 200
    assert response.json() == {"ok": True}
    assert recorded == {"user_id": "user-1", "org_id": "org-1"}
