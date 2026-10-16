"""M03 JwksCache 单测：TTL 过期与失败分类（时钟注入，无网络）。"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.exceptions import AuthError
from app.core.security import JwksCache


class _FakeClock:
    def __init__(self, start: float = 1_000.0) -> None:
        self.now = start

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _jwks_payload(tag: str) -> dict[str, Any]:
    return {"keys": [{"kid": tag}]}


def test_cache_hit_within_ttl() -> None:
    clock = _FakeClock()
    calls: list[str] = []

    def fetcher(url: str) -> dict[str, Any]:
        calls.append(url)
        return _jwks_payload("k1")

    cache = JwksCache("http://casdoor.local/.well-known/jwks", ttl_seconds=60, clock=clock, fetcher=fetcher)

    first = cache.get_jwks()
    clock.advance(30)
    second = cache.get_jwks()

    assert first is second
    assert calls == ["http://casdoor.local/.well-known/jwks"]


def test_cache_refetch_after_ttl() -> None:
    clock = _FakeClock()
    calls = 0

    def fetcher(url: str) -> dict[str, Any]:
        nonlocal calls
        calls += 1
        return _jwks_payload(f"k{calls}")

    cache = JwksCache("http://x/jwks", ttl_seconds=60, clock=clock, fetcher=fetcher)

    assert cache.get_jwks()["keys"][0]["kid"] == "k1"
    clock.advance(59)
    assert cache.get_jwks()["keys"][0]["kid"] == "k1"
    clock.advance(2)
    assert cache.get_jwks()["keys"][0]["kid"] == "k2"


def test_fetch_failure_wrapped_as_auth_error() -> None:
    def fetcher(url: str) -> dict[str, Any]:
        raise ConnectionError("boom")

    cache = JwksCache("http://x/jwks", fetcher=fetcher)

    with pytest.raises(AuthError, match="JWKS") as exc_info:
        cache.get_jwks()
    assert exc_info.value.status_code == 401
    assert "boom" not in str(exc_info.value.message)


def test_auth_error_from_fetcher_propagates() -> None:
    def fetcher(url: str) -> dict[str, Any]:
        raise AuthError("JWKS 响应格式非法")

    cache = JwksCache("http://x/jwks", fetcher=fetcher)

    with pytest.raises(AuthError, match="格式非法"):
        cache.get_jwks()
