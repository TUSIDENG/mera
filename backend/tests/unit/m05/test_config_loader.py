"""M05 用例①：站点配置发现/加载校验。

缺 key / strategies 非法 / 引用不存在方案 -> ConfigError；
声明但缺文件的方案 -> skipped 不报错；未声明的已存在方案文件 -> 不注册不报错。
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from app.core.exceptions import ConfigError
from app.fetchers.config_loader import discover_sites, load_site

_FETCHER_SRC = """\
from app.fetchers.base import BaseFetcher


class Fetcher(BaseFetcher):
    strategy = "api"

    def fetch(self):
        return []
"""


def make_site(tmp_path: Path, key: str, cfg: dict, modules: dict[str, str] | None = None) -> Path:
    site_dir = tmp_path / key
    site_dir.mkdir(parents=True)
    (site_dir / "config.yaml").write_text(
        yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8"
    )
    for filename, content in (modules or {}).items():
        (site_dir / filename).write_text(content, encoding="utf-8")
    return tmp_path


def valid_cfg(**overrides) -> dict:
    cfg = {
        "key": "demo",
        "data_type": "model_metrics",
        "auth_required": False,
        "strategies": ["api"],
    }
    cfg.update(overrides)
    return cfg


class TestDiscoverSites:
    def test_returns_sorted_keys_with_config(self, tmp_path):
        make_site(tmp_path, "beta", valid_cfg(key="beta"))
        make_site(tmp_path, "alpha", valid_cfg(key="alpha"))
        (tmp_path / "no_config").mkdir()
        assert discover_sites(tmp_path) == ["alpha", "beta"]

    def test_missing_dir_returns_empty(self, tmp_path):
        assert discover_sites(tmp_path / "nope") == []


class TestLoadSiteValidation:
    def test_missing_config_raises(self, tmp_path):
        with pytest.raises(ConfigError):
            load_site(tmp_path, "ghost")

    def test_missing_key_raises(self, tmp_path):
        cfg = valid_cfg()
        del cfg["key"]
        root = make_site(tmp_path, "demo", cfg)
        with pytest.raises(ConfigError):
            load_site(root, "demo")

    def test_key_dir_mismatch_raises(self, tmp_path):
        root = make_site(tmp_path, "demo", valid_cfg(key="other"))
        with pytest.raises(ConfigError):
            load_site(root, "demo")

    def test_invalid_data_type_raises(self, tmp_path):
        root = make_site(tmp_path, "demo", valid_cfg(data_type="unknown"))
        with pytest.raises(ConfigError):
            load_site(root, "demo")

    def test_invalid_auth_required_raises(self, tmp_path):
        root = make_site(tmp_path, "demo", valid_cfg(auth_required="password"))
        with pytest.raises(ConfigError):
            load_site(root, "demo")

    @pytest.mark.parametrize("strategies", [None, [], "api", ["api", "api"]])
    def test_invalid_strategies_raises(self, tmp_path, strategies):
        root = make_site(tmp_path, "demo", valid_cfg(strategies=strategies))
        with pytest.raises(ConfigError):
            load_site(root, "demo")

    def test_unknown_strategy_name_raises(self, tmp_path):
        root = make_site(tmp_path, "demo", valid_cfg(strategies=["api", "selenium"]))
        with pytest.raises(ConfigError, match="不存在的方案"):
            load_site(root, "demo")


class TestLoadSiteStrategies:
    def test_declared_and_implemented_registered_in_order(self, tmp_path):
        root = make_site(
            tmp_path,
            "demo",
            valid_cfg(strategies=["reverse_api", "api"]),
            modules={
                "reverse_api.py": _FETCHER_SRC.replace('"api"', '"reverse_api"'),
                "api.py": _FETCHER_SRC,
            },
        )
        site = load_site(root, "demo")
        assert [name for name, _ in site.fetchers] == ["reverse_api", "api"]
        assert site.skipped == []

    def test_declared_but_missing_file_recorded_skipped(self, tmp_path):
        root = make_site(
            tmp_path,
            "demo",
            valid_cfg(strategies=["api", "playwright"]),
            modules={"api.py": _FETCHER_SRC},
        )
        site = load_site(root, "demo")
        assert [name for name, _ in site.fetchers] == ["api"]
        assert site.skipped == [("playwright", "方案文件缺失: playwright.py")]

    def test_implemented_but_undeclared_not_registered(self, tmp_path):
        root = make_site(
            tmp_path,
            "demo",
            valid_cfg(strategies=["api"]),
            modules={"api.py": _FETCHER_SRC, "playwright.py": _FETCHER_SRC},
        )
        site = load_site(root, "demo")
        assert [name for name, _ in site.fetchers] == ["api"]
        assert site.skipped == []

    def test_module_without_fetcher_class_raises(self, tmp_path):
        root = make_site(
            tmp_path, "demo", valid_cfg(), modules={"api.py": "X = 1\n"}
        )
        with pytest.raises(ConfigError, match="Fetcher"):
            load_site(root, "demo")
