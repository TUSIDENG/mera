"""M06 artificial_analysis 逆向接口方案：签名构造/解析/异常/密钥缺失跳过。"""

from __future__ import annotations

from urllib.parse import parse_qs, urlparse

import pytest
import responses
from helpers import make_fetcher, site_config

from app.core.exceptions import CaptchaRequired, FetchFailed, SecretError
from app.fetchers.signing import sign_hmac_md5
from app.fetchers.sites.artificial_analysis.reverse_api import build_request, parse_response

ENDPOINT = "https://artificialanalysis.ai/api/v1/leaderboard/models"
TS = 1700000000


@pytest.fixture
def cfg() -> dict:
    return site_config("artificial_analysis")


class TestBuildRequest:
    def test_signed_params(self, cfg):
        spec = build_request(cfg, secret="s3cr3t", timestamp=TS, page=2)
        assert spec.method == "GET"
        assert spec.url == ENDPOINT
        expected = sign_hmac_md5({"page": 2, "size": 50}, "s3cr3t", TS)
        assert spec.params["sign"] == expected
        assert spec.params["timestamp"] == TS
        assert spec.params["page"] == 2

    def test_secret_not_in_request(self, cfg):
        spec = build_request(cfg, secret="s3cr3t-value", timestamp=TS)
        assert "s3cr3t-value" not in str(spec.params.values())
        assert "s3cr3t-value" not in str(spec.headers.values())

    def test_referer_from_playwright_url(self, cfg):
        spec = build_request(cfg, secret="s", timestamp=TS)
        assert spec.headers["Referer"] == cfg["playwright"]["url"]


class TestParseResponse:
    def test_extracts_records_and_flags(self):
        payload = {"code": 0, "data": {"list": [{"model": "GPT-4o"}], "has_more": True}}
        records, has_more, truncated = parse_response(payload)
        assert records == [{"model": "GPT-4o"}]
        assert has_more is True
        assert truncated is False

    def test_server_truncated(self):
        payload = {"code": 0, "data": {"list": [], "truncated": True}}
        _, _, truncated = parse_response(payload)
        assert truncated is True

    @pytest.mark.parametrize("payload", [None, [], {}, {"data": "x"}, {"data": {"list": "x"}}])
    def test_dirty_payload(self, payload):
        assert parse_response(payload) == ([], False, False)


class TestAvailability:
    def test_missing_secret_unavailable_with_reason(self, monkeypatch):
        monkeypatch.delenv("AA_SECRET", raising=False)
        fetcher = make_fetcher("artificial_analysis", "reverse_api")
        assert fetcher.is_available() is False
        assert "env:AA_SECRET" in fetcher.unavailable_reason

    def test_fetch_without_secret_raises_before_request(self, monkeypatch):
        monkeypatch.delenv("AA_SECRET", raising=False)
        fetcher = make_fetcher("artificial_analysis", "reverse_api")
        with pytest.raises(SecretError):
            fetcher.fetch()

    def test_reason_does_not_contain_secret_value(self, monkeypatch):
        monkeypatch.delenv("AA_SECRET", raising=False)
        fetcher = make_fetcher("artificial_analysis", "reverse_api")
        assert "AA_SECRET" in fetcher.unavailable_reason  # 变量名可出现，值不可出现


class TestFetch:
    @responses.activate
    def test_fetch_single_page(self, monkeypatch, cfg):
        monkeypatch.setenv("AA_SECRET", "s3cr3t")
        payload = {"code": 0, "data": {"list": [{"model": "GPT-4o"}], "has_more": False}}
        responses.get(ENDPOINT, json=payload, status=200)
        sleeps: list[float] = []
        fetcher = make_fetcher(
            "artificial_analysis", "reverse_api", _sleep=sleeps.append, _now=lambda: float(TS)
        )
        records = fetcher.fetch()
        assert records == [{"model": "GPT-4o"}]
        assert fetcher.truncated is False
        assert sleeps == [6.0]  # rate_limit_per_min=10 -> 限频 6s
        query = parse_qs(urlparse(responses.calls[0].request.url).query)
        assert query["sign"] == [sign_hmac_md5({"page": 1, "size": 50}, "s3cr3t", TS)]
        assert query["timestamp"] == [str(TS)]

    @responses.activate
    def test_fetch_paginates_until_no_more(self, monkeypatch):
        monkeypatch.setenv("AA_SECRET", "s3cr3t")
        responses.get(
            ENDPOINT,
            json={"code": 0, "data": {"list": [{"model": "m1"}], "has_more": True}},
        )
        responses.get(
            ENDPOINT,
            json={"code": 0, "data": {"list": [{"model": "m2"}], "has_more": False}},
        )
        fetcher = make_fetcher(
            "artificial_analysis", "reverse_api", _sleep=lambda s: None, _now=lambda: float(TS)
        )
        records = fetcher.fetch()
        assert [r["model"] for r in records] == ["m1", "m2"]
        assert fetcher.truncated is False
        assert len(responses.calls) == 2

    @responses.activate
    def test_max_pages_marks_truncated(self, monkeypatch):
        monkeypatch.setenv("AA_SECRET", "s3cr3t")
        responses.get(
            ENDPOINT,
            json={"code": 0, "data": {"list": [{"model": "m"}], "has_more": True}},
        )
        fetcher = make_fetcher(
            "artificial_analysis", "reverse_api", _sleep=lambda s: None, _now=lambda: float(TS)
        )
        fetcher.cfg["reverse_api"]["max_pages"] = 2
        records = fetcher.fetch()
        assert len(records) == 2  # 已到翻页上限
        assert fetcher.truncated is True

    @responses.activate
    def test_http_500_raises_fetch_failed(self, monkeypatch):
        monkeypatch.setenv("AA_SECRET", "s3cr3t")
        responses.get(ENDPOINT, status=500)
        fetcher = make_fetcher(
            "artificial_analysis", "reverse_api", _sleep=lambda s: None, _now=lambda: float(TS)
        )
        with pytest.raises(FetchFailed, match="500"):
            fetcher.fetch()

    @responses.activate
    def test_captcha_code_raises_captcha_required(self, monkeypatch):
        monkeypatch.setenv("AA_SECRET", "s3cr3t")
        responses.get(ENDPOINT, json={"code": "CAPTCHA_REQUIRED"}, status=200)
        fetcher = make_fetcher(
            "artificial_analysis", "reverse_api", _sleep=lambda s: None, _now=lambda: float(TS)
        )
        with pytest.raises(CaptchaRequired):
            fetcher.fetch()
