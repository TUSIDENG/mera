"""M06 artificial_analysis 结构化解析方案：RSC 提取/字段映射/异常分类。"""

from __future__ import annotations

import json

import pytest
import responses
from helpers import make_fetcher, site_config

from app.core.exceptions import FetchFailed
from app.fetchers.sites.artificial_analysis.reverse_api import (
    build_request,
    extract_named_array,
    extract_rsc_payload,
    map_records,
)

PAGE_URL = "https://artificialanalysis.ai/leaderboards/models"

_MODELS = [
    {
        "slug": "gpt-6-1-sol-xhigh",
        "name": "GPT-6.1 Sol (Xhigh)",
        "modelCreatorName": "OpenAI",
        "intelligenceIndex": 52.458219253291,
    },
    {
        "slug": "jt-35b-flash",
        "name": "JT-35B-Flash",
        "modelCreatorName": "China Mobile",
        "intelligenceIndex": None,
    },
    {"slug": "broken", "modelCreatorName": "NoName"},  # 缺 name，应被丢弃
]


def _page_html(models: list[dict] | None = None) -> str:
    """构造含 RSC 内嵌数据的假页面；字符串内含引号/括号，覆盖配平扫描。"""
    if models is None:
        models = _MODELS
    payload = '22:["$","div",null,{"initialModels":' + json.dumps(models) + "}]"
    frame = json.dumps([1, payload])
    return f'<html><script>self.__next_f.push({frame})</script></html>'


@pytest.fixture
def cfg() -> dict:
    return site_config("artificial_analysis")


class TestBuildRequest:
    def test_get_public_page(self, cfg):
        spec = build_request(cfg)
        assert spec.method == "GET"
        assert spec.url == PAGE_URL
        assert spec.params == {}
        assert "User-Agent" in spec.headers

    def test_no_secret_or_signature(self, cfg):
        spec = build_request(cfg)
        assert not spec.params
        assert "sign" not in str(spec.headers).lower()


class TestExtractRscPayload:
    def test_joins_string_frames(self):
        html = _page_html()
        blob = extract_rsc_payload(html)
        assert '"initialModels"' in blob
        assert "GPT-6.1 Sol" in blob

    def test_skips_dirty_frames(self):
        html = "<script>self.__next_f.push({bad})</script>" + _page_html()
        assert '"initialModels"' in extract_rsc_payload(html)

    def test_no_frames(self):
        assert extract_rsc_payload("<html></html>") == ""


class TestExtractNamedArray:
    def test_extracts_array_with_nested_brackets_in_strings(self):
        blob = 'x:{"a":"[not an array ] \\"quoted\\""},"initialModels":[{"name":"m1"}]'
        arr = extract_named_array(blob, "initialModels")
        assert arr == [{"name": "m1"}]

    def test_missing_key(self):
        assert extract_named_array('{"other":[]}', "initialModels") == []

    def test_dirty_json(self):
        assert extract_named_array('"initialModels":[{bad', "initialModels") == []


class TestMapRecords:
    def test_maps_config_fields(self, cfg):
        fields = cfg["reverse_api"]["fields"]
        records = map_records(_MODELS, fields)
        assert records == [
            {"model": "GPT-6.1 Sol (Xhigh)", "provider": "OpenAI", "score": 52.458219253291},
            {"model": "JT-35B-Flash", "provider": "China Mobile", "score": None},
        ]

    def test_skips_non_dict(self, cfg):
        assert map_records(["x", None], cfg["reverse_api"]["fields"]) == []


class TestAvailability:
    def test_available_without_any_secret(self, monkeypatch):
        monkeypatch.delenv("AA_SECRET", raising=False)
        fetcher = make_fetcher("artificial_analysis", "reverse_api")
        assert fetcher.is_available() is True


class TestFetch:
    @responses.activate
    def test_fetch_parses_embedded_models(self, cfg):
        responses.get(PAGE_URL, body=_page_html(), status=200)
        fetcher = make_fetcher("artificial_analysis", "reverse_api")
        records = fetcher.fetch()
        assert [r["model"] for r in records] == ["GPT-6.1 Sol (Xhigh)", "JT-35B-Flash"]
        assert records[0]["score"] == pytest.approx(52.458, abs=1e-3)
        assert fetcher.truncated is False

    @responses.activate
    def test_http_500_raises_fetch_failed(self):
        responses.get(PAGE_URL, status=500)
        fetcher = make_fetcher("artificial_analysis", "reverse_api")
        with pytest.raises(FetchFailed, match="500"):
            fetcher.fetch()

    @responses.activate
    def test_missing_array_returns_empty(self):
        responses.get(PAGE_URL, body="<html><script>self.__next_f.push([1,\"x\"])</script></html>")
        fetcher = make_fetcher("artificial_analysis", "reverse_api")
        assert fetcher.fetch() == []
