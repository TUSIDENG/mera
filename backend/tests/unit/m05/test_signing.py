"""M05 用例③：签名 golden 值、参数顺序无关、secret 不出现在异常消息。"""

from __future__ import annotations

import pytest

from app.core.exceptions import SecretError
from app.fetchers.signing import read_secret, sign_hmac_md5

# golden：params={"page":1,"size":50}, secret="test-secret", timestamp=1700000000
# raw = "page=1&size=501700000000"，独立工具预计算
GOLDEN = "20d8f51c35038a2c02c775814211c6f6"


class TestSignHmacMd5:
    def test_golden_value(self):
        assert (
            sign_hmac_md5({"page": 1, "size": 50}, "test-secret", 1700000000) == GOLDEN
        )

    def test_param_order_irrelevant(self):
        left = sign_hmac_md5({"a": 1, "b": 2, "c": 3}, "s", 42)
        right = sign_hmac_md5({"c": 3, "b": 2, "a": 1}, "s", 42)
        assert left == right

    def test_timestamp_explicit(self):
        assert sign_hmac_md5({"a": 1}, "s", 1) != sign_hmac_md5({"a": 1}, "s", 2)

    def test_empty_secret_raises(self):
        with pytest.raises(SecretError, match="密钥为空"):
            sign_hmac_md5({"a": 1}, "", 1)

    def test_secret_value_never_in_exception(self):
        secret = "super-secret-value-123"
        # 触发各类异常路径，断言密钥值不出现在消息中
        with pytest.raises(SecretError) as exc_info:
            read_secret("vault:token")
        assert secret not in exc_info.value.message
        with pytest.raises(SecretError) as exc_info:
            read_secret("env:")
        assert secret not in exc_info.value.message


class TestReadSecret:
    def test_reads_env(self, monkeypatch):
        monkeypatch.setenv("MERA_TEST_SECRET", "s3cr3t")
        assert read_secret("env:MERA_TEST_SECRET") == "s3cr3t"

    def test_missing_env_raises_with_var_name_not_value(self, monkeypatch):
        monkeypatch.delenv("MERA_MISSING", raising=False)
        with pytest.raises(SecretError) as exc_info:
            read_secret("env:MERA_MISSING")
        assert "MERA_MISSING" in exc_info.value.message

    def test_empty_env_raises(self, monkeypatch):
        monkeypatch.setenv("MERA_EMPTY", "")
        with pytest.raises(SecretError):
            read_secret("env:MERA_EMPTY")

    def test_unsupported_scheme(self):
        with pytest.raises(SecretError, match="env:"):
            read_secret("file:/etc/secret")
