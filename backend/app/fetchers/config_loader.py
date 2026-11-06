"""M05 站点配置发现与加载。

只注册站点已实现（方案文件存在）且在 config.yaml.strategies 中声明的方案；
声明了但文件缺失的方案记录为 skipped（不视为异常）；引用非法方案名/缺必需键抛 ConfigError。
"""

from __future__ import annotations

import importlib.util
import sys
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from app.core.exceptions import ConfigError
from app.fetchers.base import BaseFetcher
from app.fetchers.normalize import DATA_TYPES, _clean_str

SITES_DIR = Path(__file__).parent / "sites"

# 策略名 -> 站点目录内方案文件名
STRATEGY_MODULE = {
    "api": "api",
    "reverse_api": "reverse_api",
    "playwright": "playwright",
}

# 登录要求枚举（M06.2）：false=公开页，其余为各类授权凭据
AUTH_REQUIRED_VALUES = {False, "api_key", "oauth_token", "browser_session"}


@dataclass
class SiteMeta:
    """站点元数据（不实例化方案，供前端站点列表/任务类型联动使用）。"""

    key: str
    label: str
    domain: str | None
    data_type: str
    data_types: tuple[str, ...]
    # 站点说明与官网地址（可选，供前端展示来源背景）
    description: str | None = None
    homepage: str | None = None


@dataclass
class SiteConfig:
    """一个站点的已校验配置与按声明顺序实例化的方案链。"""

    key: str
    path: Path
    cfg: dict[str, Any]
    data_type: str
    data_types: tuple[str, ...]
    domain: str | None
    strategies: list[str]
    fetchers: list[tuple[str, BaseFetcher]] = field(default_factory=list)
    # (strategy, reason)：声明了但方案文件缺失，编排层记录 skipped 后继续
    skipped: list[tuple[str, str]] = field(default_factory=list)

    def __iter__(self) -> Iterator[tuple[str, BaseFetcher]]:
        return iter(self.fetchers)


def discover_sites(sites_dir: str | Path = SITES_DIR) -> list[str]:
    """扫描站点目录，返回全部含 config.yaml 的站点 key（按字母序）。"""
    root = Path(sites_dir)
    if not root.is_dir():
        return []
    return sorted(
        child.name
        for child in root.iterdir()
        if child.is_dir() and (child / "config.yaml").is_file()
    )


def load_site(sites_dir: str | Path, key: str) -> SiteConfig:
    """加载并校验单个站点配置，实例化声明且已实现的方案。"""
    cfg = read_site_cfg(sites_dir, key)
    site_dir = Path(sites_dir) / key

    site = SiteConfig(
        key=key,
        path=site_dir,
        cfg=cfg,
        data_type=cfg["data_type"],
        data_types=_resolve_data_types(cfg, key),
        domain=cfg.get("domain"),
        strategies=list(cfg["strategies"]),
    )
    for strategy in site.strategies:
        module_file = site_dir / f"{STRATEGY_MODULE[strategy]}.py"
        if not module_file.is_file():
            site.skipped.append((strategy, f"方案文件缺失: {module_file.name}"))
            continue
        fetcher = _instantiate_fetcher(module_file, key, strategy, cfg)
        site.fetchers.append((strategy, fetcher))
    return site


def read_site_cfg(sites_dir: str | Path, key: str) -> dict[str, Any]:
    """读取并校验单个站点的 config.yaml（不实例化方案，供 API 层轻量校验用）。"""
    config_path = Path(sites_dir) / key / "config.yaml"
    if not config_path.is_file():
        raise ConfigError(f"站点配置不存在: {key}")
    try:
        cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except yaml.YAMLError as exc:
        raise ConfigError(f"站点配置 YAML 解析失败: {key}") from exc
    if not isinstance(cfg, dict):
        raise ConfigError(f"站点配置必须是映射结构: {key}")
    _validate_config(cfg, key)
    return cfg


def site_data_types(sites_dir: str | Path, key: str) -> tuple[str, ...]:
    """站点声明支持的数据类型集合（任务类型校验用）。"""
    cfg = read_site_cfg(sites_dir, key)
    return _resolve_data_types(cfg, key)


def list_sites(sites_dir: str | Path) -> list[SiteMeta]:
    """枚举 sites 目录下所有合法站点的元数据，按 key 排序。"""
    root = Path(sites_dir)
    if not root.is_dir():
        return []
    sites: list[SiteMeta] = []
    for entry in sorted(root.iterdir()):
        if not entry.is_dir() or entry.name.startswith("_") or entry.name.startswith("."):
            continue
        config_path = entry / "config.yaml"
        if not config_path.is_file():
            continue
        try:
            cfg = read_site_cfg(root, entry.name)
        except ConfigError:
            # 配置非法的站点在列表中直接跳过（不影响其它站点）
            continue
        label = _clean_str(cfg.get("label")) or entry.name.replace("_", " ").title()
        sites.append(
            SiteMeta(
                key=entry.name,
                label=label,
                domain=cfg.get("domain"),
                data_type=cfg["data_type"],
                data_types=_resolve_data_types(cfg, entry.name),
                description=_clean_str(cfg.get("description")),
                homepage=_clean_str(cfg.get("homepage")),
            )
        )
    return sites


def _resolve_data_types(cfg: dict, key: str) -> tuple[str, ...]:
    """data_types 缺省为 [data_type]；显式声明时必须包含 data_type 且全部合法。"""
    declared = cfg.get("data_types")
    if declared is None:
        return (cfg["data_type"],)
    if not isinstance(declared, list) or not declared:
        raise ConfigError(f"站点 {key} data_types 必须是非空列表")
    invalid = [item for item in declared if item not in DATA_TYPES]
    if invalid:
        raise ConfigError(f"站点 {key} data_types 含非法类型: {invalid}")
    if cfg["data_type"] not in declared:
        raise ConfigError(f"站点 {key} data_types 必须包含 data_type: {cfg['data_type']!r}")
    if len(set(declared)) != len(declared):
        raise ConfigError(f"站点 {key} data_types 存在重复声明")
    return tuple(declared)


def _validate_config(cfg: dict, key: str) -> None:
    if not isinstance(cfg.get("key"), str) or not cfg["key"].strip():
        raise ConfigError(f"站点 {key} 配置缺 key")
    if cfg["key"] != key:
        raise ConfigError(f"站点 {key} 配置 key 与目录名不一致: {cfg['key']!r}")
    if cfg.get("data_type") not in DATA_TYPES:
        raise ConfigError(f"站点 {key} 数据类型非法: {cfg.get('data_type')!r}")
    if cfg.get("auth_required", None) not in AUTH_REQUIRED_VALUES:
        raise ConfigError(
            f"站点 {key} 登录要求非法（须为 false/api_key/oauth_token/browser_session）"
        )
    if cfg.get("auth_required") == "browser_session":
        session = cfg.get("browser_session")
        if not isinstance(session, dict) or not isinstance(session.get("storage_state"), str):
            raise ConfigError(
                f"站点 {key} 声明 browser_session 登录但缺 browser_session.storage_state"
            )
    strategies = cfg.get("strategies")
    if not isinstance(strategies, list) or not strategies:
        raise ConfigError(f"站点 {key} strategies 必须是非空列表")
    invalid = [name for name in strategies if name not in STRATEGY_MODULE]
    if invalid:
        raise ConfigError(f"站点 {key} 引用了不存在的方案: {invalid}")
    if len(set(strategies)) != len(strategies):
        raise ConfigError(f"站点 {key} strategies 存在重复声明")


def _instantiate_fetcher(
    module_file: Path, key: str, strategy: str, cfg: dict
) -> BaseFetcher:
    module_name = f"mera_fetch_site_{key}_{strategy}"
    spec = importlib.util.spec_from_file_location(module_name, module_file)
    if spec is None or spec.loader is None:
        raise ConfigError(f"站点 {key} 方案无法加载: {strategy}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        sys.modules.pop(module_name, None)
        raise ConfigError(f"站点 {key} 方案 {strategy} 加载失败: {exc.__class__.__name__}") from exc
    fetcher_cls = getattr(module, "Fetcher", None)
    if fetcher_cls is None or not issubclass(fetcher_cls, BaseFetcher):
        sys.modules.pop(module_name, None)
        raise ConfigError(f"站点 {key} 方案 {strategy} 缺少 BaseFetcher 子类 Fetcher")
    try:
        return fetcher_cls(cfg)
    except Exception as exc:
        raise ConfigError(f"站点 {key} 方案 {strategy} 初始化失败: {exc.__class__.__name__}") from exc
