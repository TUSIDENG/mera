"""M06 采集代理解析单测：优先级（站点配置 > MERA_FETCH_PROXY > 默认）、禁用与归一化。"""

from __future__ import annotations

import pytest

from app.fetchers.proxy import DEFAULT_PROXY, proxy_kwargs, resolve_proxy_server


@pytest.fixture(autouse=True)
def _clean_proxy_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("MERA_FETCH_PROXY", raising=False)
    monkeypatch.delenv("LMARENA_PROXY", raising=False)


class TestResolveOrder:
    def test_default_local_proxy(self):
        assert resolve_proxy_server({}) == DEFAULT_PROXY

    def test_env_var_overrides_default(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("MERA_FETCH_PROXY", "http://10.0.0.2:1080")
        assert resolve_proxy_server({}) == "http://10.0.0.2:1080"

    def test_site_config_overrides_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("MERA_FETCH_PROXY", "http://10.0.0.2:1080")
        cfg = {"playwright": {"proxy": "http://10.0.0.3:7890"}}
        assert resolve_proxy_server(cfg) == "http://10.0.0.3:7890"

    def test_site_config_env_ref(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("LMARENA_PROXY", "http://10.0.0.4:7890")
        cfg = {"playwright": {"proxy": "env:LMARENA_PROXY"}}
        assert resolve_proxy_server(cfg) == "http://10.0.0.4:7890"

    def test_env_ref_unset_falls_back(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("MERA_FETCH_PROXY", "http://10.0.0.2:1080")
        cfg = {"playwright": {"proxy": "env:LMARENA_PROXY"}}  # 未设置
        assert resolve_proxy_server(cfg) == "http://10.0.0.2:1080"

    def test_env_ref_unset_falls_back_to_default(self):
        cfg = {"playwright": {"proxy": "env:LMARENA_PROXY"}}  # 未设置且无全局环境变量
        assert resolve_proxy_server(cfg) == DEFAULT_PROXY


class TestNormalize:
    def test_bare_address_gets_http_prefix(self):
        cfg = {"playwright": {"proxy": "127.0.0.1:7890"}}
        assert resolve_proxy_server(cfg) == "http://127.0.0.1:7890"

    def test_socks5_scheme_kept(self):
        cfg = {"playwright": {"proxy": "socks5://127.0.0.1:1080"}}
        assert resolve_proxy_server(cfg) == "socks5://127.0.0.1:1080"

    @pytest.mark.parametrize("value", ["", "  ", "none", "None", "NONE"])
    def test_disable_values(self, value: str):
        cfg = {"playwright": {"proxy": value}}
        assert resolve_proxy_server(cfg) is None

    def test_disable_via_global_env(self, monkeypatch: pytest.MonkeyPatch):
        monkeypatch.setenv("MERA_FETCH_PROXY", "none")
        assert resolve_proxy_server({}) is None


class TestProxyKwargs:
    def test_kwargs_with_server(self):
        cfg = {"playwright": {"proxy": "http://10.0.0.3:7890"}}
        assert proxy_kwargs(cfg) == {"proxy": {"server": "http://10.0.0.3:7890"}}

    def test_kwargs_empty_when_disabled(self):
        cfg = {"playwright": {"proxy": "none"}}
        assert proxy_kwargs(cfg) == {}
