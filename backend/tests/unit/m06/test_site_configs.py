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
            if key != "lmarena":  # 多领域站点不声明单一 domain，领域由 playwright.pages 给出
                assert site.domain

    def test_lmarena_covers_all_five_domains(self):
        site = load_site(SITES_DIR, "lmarena")
        pages = site.cfg["playwright"]["pages"]
        # 五个领域共 14 个子分类
        assert [page["domain"] for page in pages] == (
            ["chat"] * 4 + ["agent"] * 2 + ["code"] * 2 + ["image"] * 3 + ["video"] * 3
        )
        assert site.cfg["domains"] == ["chat", "agent", "code", "image", "video"]
        # Elo/百分比量纲只写维度分，不参与跨源主榜分
        assert site.cfg["normalize"]["score_as_dimension"] is True
        assert site.cfg["normalize"]["primary_sub"]["chat"] == "text"
        assert site.cfg["normalize"]["provider_fallback"] == "unknown"
