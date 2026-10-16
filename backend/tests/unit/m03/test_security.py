"""M03 decode_token / build_rls_vars 单测：合法与各非法分支全覆盖。"""

from __future__ import annotations

from typing import Any

import pytest

from app.core.exceptions import AuthError
from app.core.security import Identity, build_rls_vars, decode_token
from tests.unit.m03.conftest import AUDIENCE, ISSUER, make_token

NOW = 1_700_000_000.0


def _decode(token: str, jwks: dict[str, Any], **kwargs: Any) -> Identity:
    return decode_token(token, jwks, NOW, audience=AUDIENCE, issuer=ISSUER, **kwargs)


def _assert_auth_error(exc_info: pytest.ExceptionInfo[AuthError]) -> None:
    assert exc_info.value.status_code == 401
    assert exc_info.value.code == "auth_error"


def test_valid_token_returns_identity(rsa_private_key: Any, jwks: dict[str, Any]) -> None:
    token = make_token(rsa_private_key, now=NOW)

    identity = _decode(token, jwks)

    assert identity.user_id == "user-1"
    assert identity.org_id == "org-1"
    assert identity.roles == ("user", "admin")


def test_roles_missing_defaults_to_empty(rsa_private_key: Any, jwks: dict[str, Any]) -> None:
    token = make_token(rsa_private_key, now=NOW, roles=None)

    assert _decode(token, jwks).roles == ()


def test_roles_as_casdoor_objects_normalized(rsa_private_key: Any, jwks: dict[str, Any]) -> None:
    token = make_token(
        rsa_private_key,
        now=NOW,
        roles=[{"owner": "org-1", "name": "admin"}, "user", {"name": 1}],
    )

    assert _decode(token, jwks).roles == ("admin", "user")


def test_expired_token_via_injected_now(rsa_private_key: Any, jwks: dict[str, Any]) -> None:
    token = make_token(rsa_private_key, now=NOW)

    with pytest.raises(AuthError, match="已过期") as exc_info:
        decode_token(token, jwks, NOW + 700, audience=AUDIENCE, issuer=ISSUER)
    _assert_auth_error(exc_info)


def test_token_missing_exp_rejected(rsa_private_key: Any, jwks: dict[str, Any]) -> None:
    token = make_token(rsa_private_key, now=NOW, exp=None)

    with pytest.raises(AuthError, match="过期时间"):
        _decode(token, jwks)


def test_token_not_yet_valid(rsa_private_key: Any, jwks: dict[str, Any]) -> None:
    token = make_token(rsa_private_key, now=NOW, nbf=int(NOW) + 600, exp=int(NOW) + 1200)

    with pytest.raises(AuthError, match="尚未生效"):
        _decode(token, jwks)


def test_tampered_signature_rejected(other_private_key: Any, jwks: dict[str, Any]) -> None:
    token = make_token(other_private_key, now=NOW)

    with pytest.raises(AuthError, match="验签失败") as exc_info:
        _decode(token, jwks)
    _assert_auth_error(exc_info)


def test_wrong_audience_rejected(rsa_private_key: Any, jwks: dict[str, Any]) -> None:
    token = make_token(rsa_private_key, now=NOW, aud="another-client")

    with pytest.raises(AuthError, match="验签失败") as exc_info:
        _decode(token, jwks)
    _assert_auth_error(exc_info)


def test_wrong_issuer_rejected(rsa_private_key: Any, jwks: dict[str, Any]) -> None:
    token = make_token(rsa_private_key, now=NOW, iss="http://evil.local")

    with pytest.raises(AuthError, match="验签失败") as exc_info:
        _decode(token, jwks)
    _assert_auth_error(exc_info)


def test_missing_sub_rejected(rsa_private_key: Any, jwks: dict[str, Any]) -> None:
    token = make_token(rsa_private_key, now=NOW, sub=None)

    with pytest.raises(AuthError, match="sub"):
        _decode(token, jwks)


def test_missing_org_rejected(rsa_private_key: Any, jwks: dict[str, Any]) -> None:
    token = make_token(rsa_private_key, now=NOW, owner=None)

    with pytest.raises(AuthError, match="组织"):
        _decode(token, jwks)


def test_alg_none_rejected(jwks: dict[str, Any]) -> None:
    token = make_token(None, now=NOW, algorithm="none", headers={"kid": "test-key"})

    with pytest.raises(AuthError, match="白名单") as exc_info:
        _decode(token, jwks)
    _assert_auth_error(exc_info)


def test_alg_confusion_hs256_rejected(jwks: dict[str, Any]) -> None:
    token = make_token(None, now=NOW, algorithm="HS256")

    with pytest.raises(AuthError, match="白名单"):
        _decode(token, jwks)


def test_unknown_kid_rejected(rsa_private_key: Any, jwks: dict[str, Any]) -> None:
    token = make_token(rsa_private_key, now=NOW, headers={"kid": "unknown-key"})

    with pytest.raises(AuthError, match="签名密钥"):
        _decode(token, jwks)


def test_malformed_token_rejected(jwks: dict[str, Any]) -> None:
    with pytest.raises(AuthError, match="结构非法"):
        _decode("not-a-jwt", jwks)


def test_jwks_without_keys_rejected(rsa_private_key: Any) -> None:
    token = make_token(rsa_private_key, now=NOW)

    with pytest.raises(AuthError, match="缺少 keys"):
        _decode(token, {})


def test_jwks_empty_keys_rejected(rsa_private_key: Any) -> None:
    token = make_token(rsa_private_key, now=NOW)

    with pytest.raises(AuthError, match="找不到匹配的签名密钥"):
        _decode(token, {"keys": []})


def test_build_rls_vars_quotes_literals() -> None:
    identity = Identity(user_id="user-1", org_id="org-1")

    assert build_rls_vars(identity) == {
        "app.current_user_id": "'user-1'",
        "app.current_org_id": "'org-1'",
    }


def test_build_rls_vars_escapes_single_quote_and_backslash() -> None:
    identity = Identity(user_id="u'evil", org_id="o\\rg")

    vars_map = build_rls_vars(identity)
    assert vars_map["app.current_user_id"] == "'u''evil'"
    assert vars_map["app.current_org_id"] == "'o\\\\rg'"
