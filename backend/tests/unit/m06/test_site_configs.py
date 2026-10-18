"""M06 站点目录冒烟：discover/load 真实站点，声明与文件一致，config.yaml 键齐全。"""

from __future__ import annotations

import importlib.util

from app.fetchers.config_loader import SITES_DIR, discover_sites, load_site


class TestSiteDirectory:
    def test_discovers_first_batch_sites(self):
        keys = discover_sites(SITES_DIR)
        assert {"openrouter", "artificial_analysis", "aider_leaderboard", "lmarena"} <= set(keys)

    def test_all_sites_load_with_declared_strategies(self, monkeypatch):
        # camoufox 为重依赖不进 dev 环境；load_site 会做 is_available 筛查，补丁使其可加载
        real_find_spec = importlib.util.find_spec

        def fake_find_spec(name, *args, **kwargs):
            if name == "camoufox":
                return object()
            return real_find_spec(name, *args, **kwargs)

        monkeypatch.setattr(importlib.util, "find_spec", fake_find_spec)
        expected = {
            "openrouter": ["api"],
            "artificial_analysis": ["reverse_api", "playwright"],
            "aider_leaderboard": ["playwright"],
            "lmarena": ["playwright"],
        }
        for key, strategies in expected.items():
            site = load_site(SITES_DIR, key)
            assert site.strategies == strategies
            assert [name for name, _ in site.fetchers] == strategies  # 声明的方案均有文件
            assert site.skipped == []

    def test_config_declares_auth_rate_limit_and_compliance(self):
        for key in discover_sites(SITES_DIR):
            site = load_site(SITES_DIR, key)
            assert "auth_required" in site.cfg
            assert site.cfg["rate_limit_per_min"] > 0
            assert site.cfg["compliance"]["public_only"] is True
            assert site.data_type == "model_metrics"
            assert site.domain
