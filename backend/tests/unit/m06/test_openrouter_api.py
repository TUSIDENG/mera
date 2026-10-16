"""M06 openrouter 官方 API 方案：请求构造/解析/异常分类（responses mock 全部 HTTP）。"""

from __future__ import annotations

import pytest
import requests
import responses
from helpers import make_fetcher, site_config

from app.core.exceptions import CaptchaRequired, FetchFailed
from app.fetchers.sites.openrouter.api import build_request, parse_response

URL = "https://openrouter.ai/api/v1/models"

PAYLOAD = {
    "data": [
        {
            "id": "openai/gpt-4o",
            "name": "GPT-4o",
            "context_length": 128000,
            "pricing": {"prompt": "0.0000025", "completion": "0.00001"},
        },
        {"id": "anthropic/claude-sonnet-4", "name": "Claude Sonnet 4"},
    ]
}


@pytest.fixture
def cfg() -> dict:
    return site_config("openrouter")


class TestBuildRequest:
    def test_request_spec_without_key(self, cfg):
        spec = build_request(cfg)
        assert spec.method == "GET"
        assert spec.url == URL
        assert "MERA-Fetcher" in spec.headers["User-Agent"]
        assert "Authorization" not in spec.headers  # 未配置密钥不带授权头
        assert spec.params == {}

    def test_request_spec_with_key_goes_to_header(self, cfg):
        spec = build_request(cfg, api_key="sk-or-test")
        assert spec.headers["Authorization"] == "Bearer sk-or-test"
        assert all("sk-or-test" not in str(v) for v in spec.params.values())


class TestParseResponse:
    def test_extracts_records(self):
        records = parse_response(PAYLOAD)
        assert len(records) == 2
        assert records[0]["id"] == "openai/gpt-4o"

    @pytest.mark.parametrize("payload", [None, [], {}, {"data": "oops"}, {"data": [1, "x"]}])
    def test_dirty_payload_returns_empty_or_filtered(self, payload):
        assert parse_response(payload) == []


class TestFetch:
    @responses.activate
    def test_fetch_200(self, cfg):
        responses.get(URL, json=PAYLOAD, status=200)
        sleeps: list[float] = []
        fetcher = make_fetcher("openrouter", "api", _sleep=sleeps.append)
        records = fetcher.fetch()
        assert [r["id"] for r in records] == ["openai/gpt-4o", "anthropic/claude-sonnet-4"]
        assert sleeps == [2.0]  # rate_limit_per_min=30 -> 每次请求后限频 2s
        assert fetcher.is_available() is True

    @responses.activate
    def test_api_key_from_env_sent_as_header(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-env")
        responses.get(URL, json=PAYLOAD, status=200)
        fetcher = make_fetcher("openrouter", "api", _sleep=lambda s: None)
        fetcher.fetch()
        assert responses.calls[0].request.headers["Authorization"] == "Bearer sk-or-env"

    @responses.activate
    def test_missing_api_key_still_available(self, monkeypatch):
        monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
        fetcher = make_fetcher("openrouter", "api")
        assert fetcher.is_available() is True  # 公开接口，可选密钥缺失不降级

    @responses.activate
    def test_http_403_raises_fetch_failed(self):
        responses.get(URL, status=403)
        fetcher = make_fetcher("openrouter", "api", _sleep=lambda s: None)
        with pytest.raises(FetchFailed, match="403"):
            fetcher.fetch()

    @responses.activate
    def test_timeout_raises_fetch_failed(self):
        responses.get(URL, body=requests.Timeout("timeout"))
        fetcher = make_fetcher("openrouter", "api", _sleep=lambda s: None)
        with pytest.raises(FetchFailed, match="Timeout"):
            fetcher.fetch()

    @responses.activate
    def test_bad_json_raises_fetch_failed(self):
        responses.get(URL, body="<html>oops</html>", content_type="text/html")
        fetcher = make_fetcher("openrouter", "api", _sleep=lambda s: None)
        with pytest.raises(FetchFailed, match="JSON"):
            fetcher.fetch()

    @responses.activate
    def test_captcha_code_raises_captcha_required(self):
        responses.get(URL, json={"code": "CAPTCHA_REQUIRED"}, status=200)
        fetcher = make_fetcher("openrouter", "api", _sleep=lambda s: None)
        with pytest.raises(CaptchaRequired):
            fetcher.fetch()

    @responses.activate
    def test_exception_messages_do_not_echo_secrets(self, monkeypatch):
        monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-secret-xyz")
        responses.get(URL, status=500)
        fetcher = make_fetcher("openrouter", "api", _sleep=lambda s: None)
        with pytest.raises(FetchFailed) as exc_info:
            fetcher.fetch()
        assert "sk-or-secret-xyz" not in exc_info.value.message

    def test_normalize_end_to_end(self, cfg):
        fetcher = make_fetcher("openrouter", "api")
        records, truncated = fetcher.normalize(PAYLOAD["data"])
        assert truncated is False
        first = records[0]
        assert first.model_id == "openai/gpt-4o"
        assert first.provider == "openrouter"  # defaults 填充
        assert first.data["input_price"] == "0.0000025"
        assert first.data["context_length"] == 128000
