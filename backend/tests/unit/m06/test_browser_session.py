"""M06.2 浏览器登录态管理单测：profiles:// 解析、TTL 判定、config schema 校验。"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest

from app.core.exceptions import ConfigError
from app.fetchers.base import BaseFetcher
from app.fetchers.config_loader import load_site
from app.fetchers.profiles import (
    DEFAULT_PROFILES_DIR,
    BrowserSessionSpec,
    browser_session_available,
    new_context_kwargs,
    parse_browser_session,
    profiles_dir,
    resolve_profile_ref,
)

SPEC = BrowserSessionSpec(storage_state="profiles://lmarena/storage_state.json", session_ttl_days=30)


# --- resolve_profile_ref ---


def test_resolve_ref_with_base_dir(tmp_path: Path):
    path = resolve_profile_ref("profiles://lmarena/storage_state.json", base_dir=tmp_path)
    assert path == tmp_path / "lmarena" / "storage_state.json"


def test_resolve_ref_env_override(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PROFILES_DIR", str(tmp_path))
    assert profiles_dir() == tmp_path
    path = resolve_profile_ref("profiles://a/b.json")
    assert path == tmp_path / "a" / "b.json"


def test_resolve_ref_default_dir(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("PROFILES_DIR", raising=False)
    assert profiles_dir() == Path(DEFAULT_PROFILES_DIR)


@pytest.mark.parametrize(
    "ref",
    [
        "lmarena/storage_state.json",  # 缺 scheme
        "profiles://",  # 空相对路径
        "profiles:///abs/path",  # 绝对路径
        "profiles://../escape",  # 越界
        "profiles://a/../../b",  # 越界
    ],
)
def test_resolve_ref_rejects_invalid(ref: str):
    with pytest.raises(ConfigError):
        resolve_profile_ref(ref)


# --- parse_browser_session ---


def test_parse_session_absent():
    assert parse_browser_session({}, site_key="s") is None


def test_parse_session_ok():
    spec = parse_browser_session(
        {"browser_session": {"storage_state": "profiles://s/storage_state.json", "session_ttl_days": 7}},
        site_key="s",
    )
    assert spec == BrowserSessionSpec(storage_state="profiles://s/storage_state.json", session_ttl_days=7)


def test_parse_session_default_ttl():
    spec = parse_browser_session(
        {"browser_session": {"storage_state": "profiles://s/storage_state.json"}}, site_key="s"
    )
    assert spec.session_ttl_days == 30


@pytest.mark.parametrize(
    "raw",
    [
        {"browser_session": "not-a-dict"},
        {"browser_session": {"storage_state": 123}},
        {"browser_session": {"storage_state": "profiles://s/x.json", "session_ttl_days": 0}},
        {"browser_session": {"storage_state": "profiles://s/x.json", "session_ttl_days": -1}},
        {"browser_session": {"storage_state": "profiles://s/x.json", "session_ttl_days": True}},
        {"browser_session": {"storage_state": "profiles://s/x.json", "session_ttl_days": "30"}},
    ],
)
def test_parse_session_rejects_invalid(raw: dict):
    with pytest.raises(ConfigError):
        parse_browser_session(raw, site_key="s")


# --- browser_session_available ---


def test_session_missing(tmp_path: Path):
    ok, reason = browser_session_available(SPEC, base_dir=tmp_path)
    assert ok is False
    assert reason is not None and "缺失" in reason


def test_session_fresh(tmp_path: Path):
    state = tmp_path / "lmarena" / "storage_state.json"
    state.parent.mkdir(parents=True)
    state.write_text("{}")
    ok, reason = browser_session_available(SPEC, base_dir=tmp_path)
    assert ok is True
    assert reason is None


def test_session_expired(tmp_path: Path):
    state = tmp_path / "lmarena" / "storage_state.json"
    state.parent.mkdir(parents=True)
    state.write_text("{}")
    old = time.time() - 31 * 86400
    os.utime(state, (old, old))
    ok, reason = browser_session_available(SPEC, base_dir=tmp_path)
    assert ok is False
    assert reason is not None and "过期" in reason


def test_session_ttl_boundary(tmp_path: Path):
    state = tmp_path / "lmarena" / "storage_state.json"
    state.parent.mkdir(parents=True)
    state.write_text("{}")
    mtime = state.stat().st_mtime
    ok, _ = browser_session_available(SPEC, base_dir=tmp_path, now=mtime + 29 * 86400)
    assert ok is True
    ok, _ = browser_session_available(SPEC, base_dir=tmp_path, now=mtime + 31 * 86400)
    assert ok is False


def test_session_invalid_ref_reason(tmp_path: Path):
    bad = BrowserSessionSpec(storage_state="not-a-ref")
    ok, reason = browser_session_available(bad, base_dir=tmp_path)
    assert ok is False
    assert reason is not None and "非法" in reason


# --- BaseFetcher.require_browser_session ---


class _DummyFetcher(BaseFetcher):
    strategy = "playwright"

    def fetch(self):  # pragma: no cover - 不调用
        return []


def test_require_session_not_configured():
    fetcher = _DummyFetcher({"key": "s"})
    assert fetcher.require_browser_session() is False
    assert fetcher.unavailable_reason is not None and "未配置" in fetcher.unavailable_reason


def test_require_session_config_error():
    fetcher = _DummyFetcher({"key": "s", "browser_session": {"session_ttl_days": 0}})
    assert fetcher.require_browser_session() is False
    assert fetcher.unavailable_reason is not None


def test_require_session_ok(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    state = tmp_path / "s" / "storage_state.json"
    state.parent.mkdir(parents=True)
    state.write_text("{}")
    monkeypatch.setenv("PROFILES_DIR", str(tmp_path))
    cfg = {"key": "s", "browser_session": {"storage_state": "profiles://s/storage_state.json"}}
    fetcher = _DummyFetcher(cfg)
    assert fetcher.require_browser_session() is True
    assert fetcher.unavailable_reason is None


# --- new_context_kwargs ---


def test_context_kwargs_without_session():
    assert new_context_kwargs({}, site_key="s") == {}


def test_context_kwargs_with_session(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PROFILES_DIR", str(tmp_path))
    cfg = {"browser_session": {"storage_state": "profiles://s/storage_state.json"}}
    kwargs = new_context_kwargs(cfg, site_key="s")
    assert kwargs["storage_state"] == str(tmp_path / "s" / "storage_state.json")


# --- config_loader schema 校验 ---

_FETCHER_STUB = '''from app.fetchers.base import BaseFetcher


class Fetcher(BaseFetcher):
    strategy = "playwright"

    def fetch(self):
        return []
'''


def _make_site(root: Path, key: str, config: str) -> Path:
    site_dir = root / key
    site_dir.mkdir(parents=True)
    (site_dir / "config.yaml").write_text(config, encoding="utf-8")
    (site_dir / "playwright.py").write_text(_FETCHER_STUB, encoding="utf-8")
    return site_dir


def test_load_site_session_auth_requires_storage_state(tmp_path: Path):
    _make_site(
        tmp_path,
        "lmarena",
        "key: lmarena\n"
        "data_type: model_metrics\n"
        "auth_required: browser_session\n"
        "strategies: [playwright]",
    )
    with pytest.raises(ConfigError, match="storage_state"):
        load_site(tmp_path, "lmarena")


def test_load_site_session_auth_ok(tmp_path: Path):
    _make_site(
        tmp_path,
        "lmarena",
        "key: lmarena\n"
        "data_type: model_metrics\n"
        "auth_required: browser_session\n"
        "strategies: [playwright]\n"
        "browser_session:\n"
        "  storage_state: profiles://lmarena/storage_state.json\n"
        "  session_ttl_days: 14",
    )
    site = load_site(tmp_path, "lmarena")
    assert site.key == "lmarena"
    assert len(site.fetchers) == 1
