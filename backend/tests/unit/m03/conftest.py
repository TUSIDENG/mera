"""M03 单测公共夹具：本地 RSA keypair 与 token 构造工具（无网络、无 Casdoor 依赖）。"""

from __future__ import annotations

import json
import time
from typing import Any

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

ISSUER = "http://casdoor.local"
AUDIENCE = "mera-client"
KID = "test-key"


@pytest.fixture(scope="module")
def rsa_private_key() -> Any:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def other_private_key() -> Any:
    return rsa.generate_private_key(public_exponent=65537, key_size=2048)


@pytest.fixture(scope="module")
def jwks(rsa_private_key: Any) -> dict[str, Any]:
    public_jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(rsa_private_key.public_key()))
    public_jwk.update({"kid": KID, "alg": "RS256", "use": "sig"})
    return {"keys": [public_jwk]}


def make_token(
    private_key: Any,
    *,
    now: float | None = None,
    headers: dict[str, Any] | None = None,
    algorithm: str = "RS256",
    **claims: Any,
) -> str:
    """构造 Casdoor 风格 token；claims 传 None 表示删除该字段。"""
    base = time.time() if now is None else now
    payload: dict[str, Any] = {
        "iss": ISSUER,
        "aud": AUDIENCE,
        "sub": "user-1",
        "owner": "org-1",
        "roles": ["user", "admin"],
        "iat": int(base),
        "nbf": int(base) - 10,
        "exp": int(base) + 600,
    }
    for key, value in claims.items():
        if value is None:
            payload.pop(key, None)
        else:
            payload[key] = value

    merged_headers: dict[str, Any] = {"kid": KID}
    if headers:
        merged_headers.update(headers)

    key: Any = private_key
    if algorithm == "none":
        key = None
    elif algorithm == "HS256":
        key = "test-secret"
    return jwt.encode(payload, key, algorithm=algorithm, headers=merged_headers)
