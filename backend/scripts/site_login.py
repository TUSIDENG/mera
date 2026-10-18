"""管理员一次性站点登录工具：写入浏览器登录态（storage_state）到 profiles 目录。

用法（本机装有 playwright 的环境，headed 模式需要桌面会话）：

    python scripts/site_login.py <site_key> [--url URL] [--dir DIR]

流程：headed Chromium 打开站点页面 -> 管理员在窗口内人工完成登录 ->
回到终端按回车 -> storage_state.json 写入 <dir>/<site_key>/storage_state.json（0600）。

注意：
- 本脚本仅供管理员低频手动执行，不进入 Celery 高频抓取链路；
- 登录态等同密钥：文件 0600、命名卷只读挂载、禁止提交仓库；
- 会话过期由 is_available() 判定（TTL 见站点 config.yaml browser_session.session_ttl_days），
  过期后 M10 告警，管理员重跑本脚本刷新；不做自动续期/密码代登录。
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import yaml

from app.fetchers.config_loader import SITES_DIR
from app.fetchers.profiles import DEFAULT_PROFILES_DIR, profiles_dir


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="站点一次性登录，写入 storage_state")
    parser.add_argument("site_key", help="站点 key（app/fetchers/sites/ 下目录名）")
    parser.add_argument("--url", default=None, help="登录起始 URL（缺省取 config.yaml playwright.url）")
    parser.add_argument(
        "--dir",
        default=None,
        help=f"profiles 根目录（缺省 PROFILES_DIR 环境变量或 {DEFAULT_PROFILES_DIR}）",
    )
    return parser.parse_args(argv)


def resolve_start_url(site_key: str, override: str | None) -> str:
    if override:
        return override
    config_path = SITES_DIR / site_key / "config.yaml"
    if not config_path.is_file():
        raise SystemExit(f"站点配置不存在: {site_key}（--url 可绕过配置读取）")
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    url = ((cfg or {}).get("playwright") or {}).get("url")
    if not url:
        raise SystemExit(f"站点 {site_key} config.yaml 未配置 playwright.url，请用 --url 指定")
    return str(url)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    url = resolve_start_url(args.site_key, args.url)
    root = Path(args.dir) if args.dir else profiles_dir()
    target = root / args.site_key / "storage_state.json"

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise SystemExit("未安装 playwright：pip install playwright && playwright install chromium") from None

    target.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()
        page.goto(url)
        input("请在浏览器窗口中完成登录，完成后回到终端按回车保存登录态...")
        context.storage_state(path=str(target))
        browser.close()

    os.chmod(target, 0o600)
    print(f"登录态已写入: {target}（权限 0600，勿提交仓库）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
