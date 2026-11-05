"""Artificial Analysis 结构化解析方案：抓公开榜单页，提取 RSC 内嵌的模型数组。

页面为 Next.js 服务端渲染，榜单数据以 self.__next_f.push([...]) 形式内嵌在 HTML 中，
无需任何密钥/签名。extract_rsc_payload/extract_named_array/map_records 为纯函数，
可脱离网络单测；仅访问公开页面，合规边界与 playwright 兜底一致。
"""

from __future__ import annotations

import json
import re
from typing import Any

import requests

from app.core.exceptions import FetchFailed
from app.fetchers.base import BaseFetcher, RequestSpec

_PUSH_RE = re.compile(r"self\.__next_f\.push\((\[.*?\])\)</script>", re.DOTALL)

_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def build_request(cfg: dict) -> RequestSpec:
    """构造页面请求（纯函数）：公开 HTML 页，无签名/密钥参数。"""
    return RequestSpec(
        method="GET",
        url=cfg["reverse_api"]["url"],
        headers={"User-Agent": _UA, "Accept": "text/html"},
    )


def extract_rsc_payload(html: str) -> str:
    """提取并拼接 self.__next_f.push 的字符串负载（纯函数）。"""
    parts: list[str] = []
    for match in _PUSH_RE.finditer(html):
        try:
            frame = json.loads(match.group(1))
        except ValueError:
            continue
        if isinstance(frame, list) and len(frame) >= 2 and isinstance(frame[1], str):
            parts.append(frame[1])
    return "".join(parts)


def extract_named_array(blob: str, key: str) -> list[Any]:
    """从 RSC 文本中按 "key":[...] 提取 JSON 数组（纯函数，括号配平扫描）。"""
    anchor = blob.find(f'"{key}":')
    if anchor < 0:
        return []
    start = blob.find("[", anchor)
    if start < 0:
        return []
    depth = 0
    in_str = False
    esc = False
    for j in range(start, len(blob)):
        ch = blob[j]
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == "[":
            depth += 1
        elif ch == "]":
            depth -= 1
            if depth == 0:
                try:
                    arr = json.loads(blob[start : j + 1])
                except ValueError:
                    return []
                return arr if isinstance(arr, list) else []
    return []


def map_records(items: list[Any], fields: dict[str, str]) -> list[dict]:
    """按 config 字段映射裁剪记录（纯函数）；缺 model 名的记录丢弃。"""
    records: list[dict] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        row = {name: item.get(path) for name, path in fields.items()}
        if not row.get("model"):
            continue
        records.append(row)
    return records


class Fetcher(BaseFetcher):
    strategy = "reverse_api"

    def __init__(
        self,
        site_config: dict,
        *,
        session: requests.Session | None = None,
    ) -> None:
        super().__init__(site_config)
        self.session = session or requests.Session()

    def fetch(self) -> list[dict]:
        spec = build_request(self.cfg)
        try:
            resp = self.session.request(
                spec.method, spec.url, headers=spec.headers, timeout=30
            )
        except requests.RequestException as exc:
            raise FetchFailed(f"请求失败: {exc.__class__.__name__}") from exc
        if resp.status_code >= 400:
            raise FetchFailed(f"HTTP {resp.status_code}")
        api_cfg = self.cfg["reverse_api"]
        blob = extract_rsc_payload(resp.text)
        items = extract_named_array(blob, api_cfg.get("array_key", "initialModels"))
        return map_records(items, api_cfg.get("fields") or {})
