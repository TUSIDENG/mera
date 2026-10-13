# MERA 数据采集实现方案说明书
## 接口逆向 / Playwright / 指纹浏览器 / 开源 RPA(Windows/Ubuntu + 云手机) / 官方 API 多策略采集落地指南 (v1.2)

> 本文是 [`mera_architecture_document.md`](./mera_architecture_document.md) 第 3.5、3.6 节的实现细化文档，描述各采集策略的技术选型、工程结构与关键代码。
> **合规前提**：所有方案仅用于采集公开可访问的事实性数据（模型榜单分数、公开定价等），须遵守目标站点 `robots.txt`、服务条款与相关法律法规；不得绕过付费/鉴权墙、不得抓取个人隐私数据。

---

## 1. 总体设计 (Unified Fetcher Abstraction)

### 1.1 策略链与优先级

```text
app/fetchers/sites/<站点>/
   config.yaml 声明的 strategies 按序降级:
   api (官方/开源 API)  ──失败──>  reverse_api (接口逆向)  ──失败──>  playwright (浏览器自动化)
                                                                          │
                                              网页可完成 ──> 成功           └── 需桌面/手机 App ──> sites/<站点>/rpa/ (Robot Framework + RPA)
```

所有采集器实现统一接口，由 Celery 任务按优先级编排（与架构文档 3.5 节的降级链一致）：

```python
# app/fetchers/base.py
from abc import ABC, abstractmethod
from typing import Any

class BaseFetcher(ABC):
    strategy: str  # api / reverse_api / playwright_rpa

    def __init__(self, site_config: dict):
        self.cfg = site_config          # 来自 sites/<site>/config.yaml
        self.site_key = site_config["key"]

    @abstractmethod
    def fetch(self) -> list[dict[str, Any]]:
        """采集本站点，返回标准化前的原始记录列表；失败抛出可识别异常。"""

    def normalize(self, raw: list[dict]) -> list[dict]:
        """默认回退到通用 normalize；站点可在自己的 normalize.py 中覆盖。"""
        from app.fetchers.normalize import normalize_records
        return normalize_records(raw, self.cfg)
```

### 1.2 以站点为中心的组织约定 (Site-First Layout)

采集代码与配置**按“站点”组织**：`sites/` 是站点目录，其下一级是每个具体站点（一个子目录），站点目录内部才是该站点可用的各套具体采集方案（`api.py` / `reverse_api.py` / `playwright.py`）与站点配置。新增数据源 = 新增一个站点目录，不改动通用框架。

每个站点目录包含：
* `config.yaml`：该站点的策略声明、URL/接口/选择器、限频、合规开关；
* 一个或多个方案文件：按优先级命名，Orchestrator 自动发现并按声明顺序降级；
* `normalize.py`（可选）：该站点原始数据到标准结构的映射；
* `vendor/`（可选）：逆向提取的 JS、证书等辅助资产。

```yaml
# app/fetchers/sites/example_leaderboard/config.yaml
key: example_leaderboard
domain: coding
strategies: [reverse_api, playwright_rpa]   # 降级顺序
rate_limit_per_min: 5
reverse_api:
  endpoint: https://example.com/api/list
  sign: { algo: hmac_md5, secret_ref: env:EXAMPLE_SECRET }
playwright:
  url: https://example.com/leaderboard
  rows_selector: "table tr.row"
  fields:
    model: "td:nth-child(1)"
    score: "td:nth-child(2)"
```

### 1.3 工程目录结构

```text
app/fetchers/
├── base.py                 # BaseFetcher / 异常定义（通用框架）
├── captcha.py              # 验证码统一处理（见第 6 节）
├── normalize.py            # 通用标准化：原始数据 -> model_snapshots / infrastructure_costs / subscription_plans
├── orchestrator.py         # 站点发现 + 策略链编排、降级、重试、落库
└── sites/                  # ★ 站点目录：一级 = 具体站点，二级 = 具体方案
    ├── openrouter/                 # 站点 A：OpenRouter
    │   ├── config.yaml             #   站点配置（strategies:[api]）
    │   ├── api.py                  #   方案：官方 API
    │   └── normalize.py
    ├── example_leaderboard/        # 站点 B：某榜单（多方案降级）
    │   ├── config.yaml             #   strategies:[reverse_api, playwright_rpa]
    │   ├── reverse_api.py          #   方案 1：接口逆向
    │   ├── playwright.py           #   方案 2：Playwright 兜底
    │   ├── normalize.py
    │   └── vendor/
    │       └── sign.js             #   逆向提取的签名 JS
    └── gpu_vendor_pricing/         # 站点 C：云厂商定价（API + 浏览器 + 桌面/App RPA）
        ├── config.yaml             #   strategies:[api, playwright_rpa]
        ├── api.py
        ├── playwright.py
        └── rpa/                    #   该站点专属的 Robot Framework + RPA 工程（见第 5 节）
            ├── pricing_web_desktop_mobile.robot
            └── resources/
```

> **为什么 RPA 不单独拆顶层目录**：RPA 与 `api.py`/`playwright.py` 一样，只是某站点的一种采集手段，放进 `sites/<站点>/rpa/` 能保持“站点为一级、方案为二级”的内聚。Robot Framework 的运行时依赖（桌面 Windows + Appium）与普通 Python fetcher 不同，这部分通过**独立的依赖清单/部署节点**隔离，而不是用目录隔离：

```text
requirements/
└── rpa.txt        # rpaframework / robotframework-appiumlibrary / playwright，仅 RPA 节点安装
```

**站点注册约定**：每个站点目录用 `key` 唯一标识，Orchestrator 扫描 `sites/*/config.yaml` 自动注册；运行时按 `key` 加载站点，并在该站点声明的 `strategies` 内依次实例化同名方案文件完成降级。`fetch_tasks.fetch_strategy` 记录命中的站点 + 方案（如 `example_leaderboard/reverse_api`）。当方案需要桌面/手机 App 时，执行该站点目录下的 `rpa/*.robot`（由独立 RPA 节点运行），对编排层仍是同一个 `playwright_rpa` 策略。

---

## 2. 方案一：官方 / 开源 API（首选）

优先寻找官方 REST/GraphQL 接口或可下载的 JSON/CSV 数据集（如 OpenRouter、云厂商价格表）。

```python
# app/fetchers/sites/openrouter/api.py  （站点目录 openrouter 下的“官方 API”方案）
import csv
import io
import requests

class Fetcher(BaseFetcher):
    strategy = "api"

    def __init__(self, site_config):
        super().__init__(site_config)
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": "MERA-Fetcher/1.0 (+contact@example.com)"})

    def fetch(self) -> list[dict]:
        api = self.cfg["api"]
        resp = self.session.get(api["url"], timeout=30)
        resp.raise_for_status()

        if api["type"] == "json":
            return resp.json().get("data", [])
        if api["type"] == "csv":
            return list(csv.DictReader(io.StringIO(resp.text)))
        raise ValueError(f"unsupported api type: {api['type']}")
```

**要点：** 显式 UA 与联系方式、读取 `Retry-After`、遵守限频；分页用游标/`page` 参数循环；密钥从环境变量注入，不写死、不落库。

---

## 3. 方案二：接口逆向 (Reverse-Engineered API)

目标站点无公开 API，但其前端通过 XHR/fetch 返回结构化 JSON 时，逆向其接口比浏览器自动化更快、更省资源。

### 3.1 分析步骤

1. **抓包**：浏览器 DevTools → Network（Fetch/XHR 过滤），或使用 Fiddler / Charles / mitmproxy 代理抓包（含移动端 App 抓包需配置证书）。
2. **定位数据接口**：翻页/筛选时观察请求，找到返回榜单/价格 JSON 的请求。
3. **识别防护参数**：常见形式——
   * 请求头签名：`X-Sign`、`Authorization` 临时 token、`nonce` + `timestamp`；
   * Query/Body 签名：`sign = md5(sorted_params + secret)`、HMAC-SHA256；
   * 请求体加密：AES（ECB/CBC）、RSA 包裹的对称密钥；
   * 反爬 cookie：如 `__ac_signature`、设备指纹、obfuscated JS 生成的 token。
4. **逆向 JS**：在 DevTools Sources 中对签名参数名发起搜索 / XHR 断点，定位生成函数；混淆代码可借助反混淆工具与 `console.log` 验证输入输出。
5. **两种落地方式**（任选）：
   * **纯 Python 重写算法**（推荐，性能好、无浏览器依赖）；
   * **直接执行站点 JS 片段**（快速验证/更新频繁时）：用 `PyMiniRacer` / `quickjs` / Node 子进程加载提取的签名函数。

### 3.2 Python 重写签名示例

```python
# app/fetchers/sites/example_leaderboard/reverse_api.py  （站点目录下的“接口逆向”方案）
import hashlib
import hmac
import time
import requests

class Fetcher(BaseFetcher):
    strategy = "reverse_api"

    def _sign(self, params: dict, secret: str) -> str:
        # 还原站点: sign = HMAC_MD5(sorted(kv) + timestamp)
        raw = "&".join(f"{k}={params[k]}" for k in sorted(params)) + str(int(time.time()))
        return hmac.new(secret.encode(), raw.encode(), hashlib.md5).hexdigest()

    def fetch(self) -> list[dict]:
        cfg = self.cfg["reverse_api"]
        secret = _read_secret(cfg["sign"]["secret_ref"])   # 从环境变量读取
        params = {"page": 1, "size": 50}
        params["sign"] = self._sign(params, secret)

        resp = requests.get(cfg["endpoint"], params=params, timeout=30,
                            headers={"Referer": self.cfg["playwright"]["url"]})
        resp.raise_for_status()
        data = resp.json()
        if data.get("code") == "CAPTCHA_REQUIRED":
            raise CaptchaRequired(self.site_key)
        return data["data"]["list"]
```

### 3.3 直接执行 JS（备选）

```python
from py_mini_racer import MiniRacer

ctx = MiniRacer()
ctx.eval(open("app/fetchers/sites/example_leaderboard/vendor/sign.js").read())  # 从站点提取的签名函数
sign = ctx.call("window.getSign", params)                     # 调用并比对真实请求验证
```

### 3.4 维护性与失效检测

* 签名函数与密钥**按数据源版本化**存放；接口返回 403/签名错误时自动降级到 Playwright，并写入 `fetch_tasks.error_message` 告警；
* 站点改版会导致逆向失效——这是该策略固有成本，需配合监控及时更新。

---

## 4. 方案三：Playwright 浏览器自动化

接口强依赖运行时 JS、签名无法稳定还原时，驱动真实浏览器渲染页面并模拟用户行为。

```python
# app/fetchers/sites/example_leaderboard/playwright.py  （站点目录下的 Playwright 兜底方案）
from playwright.sync_api import sync_playwright, TimeoutError as PWTimeout

class Fetcher(BaseFetcher):
    strategy = "playwright_rpa"

    def fetch(self) -> list[dict]:
        cfg = self.cfg["playwright"]
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=_REALISTIC_UA, locale="zh-CN", viewport={"width": 1366, "height": 900},
            )
            page = context.new_page()
            page.goto(cfg["url"], wait_until="networkidle")

            if _detect_captcha(page):
                from app.fetchers.captcha import handle_captcha
                if not handle_captcha(page, self.site_key):
                    raise CaptchaRequired(self.site_key)   # 强验证转人工 (captcha_pending)

            results = []
            while True:
                for row in page.query_selector_all(cfg["rows_selector"]):
                    results.append({
                        name: row.query_selector(sel).inner_text().strip()
                        for name, sel in cfg["fields"].items()
                    })
                # 模拟真人停顿后点击下一页
                if not page.query_selector_or_none(cfg.get("next_selector")):
                    break
                page.locator(cfg["next_selector"]).click()
                page.wait_for_timeout(1500)

            browser.close()
            return results
```

**反检测要点：** 随机鼠标轨迹与停顿、`headless=False` 或 `playwright-stealth` 降低无头特征、持久化 Cookie/登录态（`storage_state`）、单 IP 低并发、错峰执行。

### 4.1 指纹浏览器接入（强风控站点的浏览器策略）

对 Canvas/WebGL/Audio 指纹、字体、WebRTC、UA-CH 等做深度检测的站点，纯 stealth 补丁仍可能被识别。此时浏览器策略改为驱动**指纹浏览器**：由专门的浏览器（或浏览器指纹管理层）生成一致的指纹与代理绑定，Playwright 通过 CDP（Chrome DevTools Protocol）或其兼容 API 接管，页面操作方式与普通 Playwright 完全一致。

#### 4.1.1 选型对比（商用产品 + 开源候选）

| 方案 | 类型 | 部署形态 | Docker / 无头 | 自动化接口 | 定位 |
|---|---|---|---|---|---|
| AdsPower | 商用 | Win/macOS/Linux **桌面客户端** | ✗ 需桌面会话（Xvfb 仅实验性） | Local HTTP API 启动 profile → 返回 CDP ws | 商用首选：profile/代理/团队管理成熟 |
| BitBrowser / 比特浏览器 | 商用 | Win **桌面客户端** | ✗ 需桌面会话 | 同上（Local HTTP API + CDP） | 商用备选，国内代理/账号生态 |
| Hubstudio | 商用 | Win **桌面客户端** | ✗ 需桌面会话 | 同上 | 商用备选 |
| **Camoufox** | 开源（Firefox 内核指纹浏览器） | 跨平台纯二进制 + Python 包 | ✅ **原生无头，Docker 友好** | `camoufox` Python 包直接驱动（Playwright 兼容 API），无需外部客户端 | **待采纳：容器化/云原生首选** |
| **DonutBrowser** | 开源（多 profile 浏览器管理器） | macOS/Win/Linux **桌面 GUI** | ✗ 桌面应用 | 启动真实浏览器（Chrome/Firefox/Brave/Tor 等）+ 独立代理；CDP 调试端口开放能力需按版本实测 | **待采纳：本地多 profile 管理，候选观察**，暂不进自动化主链路 |

**能否部署到 Docker / 云服务器？——结论：**

1. **商用指纹浏览器（AdsPower/BitBrowser/Hubstudio）不能容器化**：它们是 Electron/桌面 GUI 应用，官方仅支持带桌面会话的操作系统，没有 headless/Docker 交付形态。正确做法是部署在**带桌面环境的云主机**——Windows 10/11 专业版云桌面（兼容性最好），或厂商提供 Linux 客户端时用 Linux 桌面 + Xvfb 虚拟显示（实验性：升级易碎、指纹一致性需回归自测，不建议作为生产形态）。
2. **Camoufox 天然可以放进 Docker**：纯浏览器二进制 + Python 驱动，无 GUI 依赖，可直接装进 worker 容器，与 docker-compose 的 `worker-2` 一体化——这是容器化部署指纹能力的推荐路线（见 4.1.2 形态 C）。
3. **DonutBrowser 是桌面 GUI 工具**：面向本地人工/半自动的多 profile 管理，服务器化不是其目标场景，作为候选观察。

**工作机制：**

```text
Playwright (connect_over_cdp)
      │  ws://127.0.0.1:50325/devtool/browser/{profile_id}/...
      ▼
指纹浏览器客户端（按 profile 隔离: UA / Canvas / WebGL / 时区 / 语言 / WebRTC / Cookie / 代理）
      │  出站流量
      ▼
该 profile 绑定的住宅/机房代理 ──> 目标站点
```

* 每个站点（或每个账号）使用一个独立 profile，**profile 与代理 IP 一一绑定**，保证“IP 归属地 = 指纹时区/语言”一致，避免出现美国 IP + UTC+8 的矛盾指纹；
* profile 的 cookie/localStorage 由指纹浏览器持久化，等价于自动维护 `storage_state`，登录态可跨任务复用；
* 商用客户端必须运行在**带桌面会话的系统**上（本地宿主机或云端带桌面节点），其 Local API 只监听本地/内网地址，**禁止把 Local API 暴露公网**；Camoufox 无外部客户端、由 fetcher 进程内直接驱动。部署形态见 4.1.2。

#### 4.1.2 部署形态与和其他服务的交互

按“指纹浏览器运行在哪”分三种形态，fetcher 端仅需改 `config.yaml` 的 `fingerprint_browser` 块，代码不变。

**形态 A：本地 docker-compose，商用客户端装在宿主机**

```text
┌─ Docker (mera-net) ────────────┐          ┌─ 宿主机（开发机/办公机，有桌面）──────────┐
│ worker-2 (Fetcher+Playwright)  │ Local API│ 指纹浏览器客户端 (AdsPower/BitBrowser)    │
│   1. GET /browser/start ───────┼─────────>│   2. 启动 profile，绑定代理               │
│   3. connect_over_cdp(ws) ─────┼─────────>│   4. 返回 CDP ws，页面流量经代理 → 目标站 │
└────────────────────────────────┘          └─────────────────────────────────────────┘
        容器→宿主: host.docker.internal:50325（Docker Desktop 内置 DNS；
        Linux 宿主用 172.17.0.1 或 compose 加 extra_hosts: host.docker.internal:host-gateway）
```

* 交互链路只有两条，**均由容器内的 worker 主动发起**：① HTTP Local API（启动/停止 profile）；② CDP WebSocket（回连接管页面）。宿主机无需对容器开放其他端口；
* 客户端 Local API 保持默认 `127.0.0.1` 监听即可（Docker Desktop 会做转发），不要为了省事绑 `0.0.0.0`。

**形态 B：云端指纹浏览器节点，商用客户端装在云主机**

```text
┌─ MERA 主系统 (云 VPC) ───────────┐        ┌─ 指纹浏览器节点（同 VPC / WireGuard 组网）─┐
│ worker-2                         │ 内网HTTP│ Windows 10/11 Pro 云桌面（或 Linux 桌面） │
│   1. GET /browser/start ─────────┼────────>│ 客户端 + Local API :50325                 │
│   2. connect_over_cdp(ws) ───────┼────────>│ profile → 绑定的住宅代理出口 → 目标站     │
└──────────────────────────────────┘         └───────────────────────────────────────────┘
```

* 节点放在**同一 VPC 内网**，Local API 端口仅对 MERA worker 子网开放安全组；跨云/本地混合时用 WireGuard/Tailscale 组网或 SSH 反向隧道（`ssh -R 50325:127.0.0.1:50325`），严禁公网暴露——Local API 无鉴权即可操控全部 profile；
* CDP 同样是 worker 回连节点，节点除 Local API 外无其他入站需求；
* profile 代理出口尽量与节点同地域；单节点内存决定同开 profile 数（300~800MB/个），多站点按 profile 分片到多节点，`local_api` 按站点配置不同节点地址。

**形态 C：Camoufox 随 worker 容器一体化（开源路线，推荐）**

```text
┌─ worker-2 容器 ──────────────────────────────────────┐
│ Fetcher → camoufox(Python 进程内调用) → Firefox 内核  │──> 任务注入的代理出口 ──> 目标站
│ profile 持久化卷: /data/fp_profiles/<site_key>/       │
└──────────────────────────────────────────────────────┘
```

* 无外部交互：浏览器与 fetcher 同容器同进程，切换形态 A/B 的 HTTP+CDP 两次网络调用为进程内函数调用，链路最短、无端口暴露面；
* 代理按任务从环境变量注入；cookie/登录态通过持久化卷逐站点保存；
* backend 镜像增加指纹浏览器能力（`backend/Dockerfile` 在 `INSTALL_PLAYWRIGHT=true` 分支追加）：

```dockerfile
RUN pip install "camoufox[geoip]" && python -m camoufox fetch
# 可选：Xvfb 虚拟显示，以 headless=False 形态运行可进一步提升真实度
RUN apt-get update && apt-get install -y --no-install-recommends xvfb \
    && rm -rf /var/lib/apt/lists/*
```

* DonutBrowser（候选观察）：桌面 GUI，适合运营在本地管理多 profile/代理；若后续验证其能以 `--remote-debugging-port` 启动浏览器，则走与形态 A 相同的 `connect_over_cdp` 路径接入，无需改框架。

**任务交互时序（三种形态统一）：**

```text
Celery beat/手动触发 fetch_task(source_key)
  → worker-2 领取任务，读 sites/<站点>/config.yaml
  → fingerprint_browser.enabled?
      ├─ provider=adspower/bitbrowser: HTTP Local API 启动 profile → 得 CDP ws → connect_over_cdp（形态 A/B）
      ├─ provider=camoufox: 进程内 Camoufox(persistent profile + 代理)（形态 C）
      └─ 未启用: 普通 headless Chromium 兜底
  → 采集/翻页/验证码（第 6 节）→ normalize → UPSERT → fetch_tasks 状态机 → 通知/自动分析
```

**站点 config.yaml 增量配置：**

```yaml
playwright:
  url: https://example.com/leaderboard
  rows_selector: "table tr.row"
  fields:
    model: "td:nth-child(1)"
    score: "td:nth-child(2)"
  fingerprint_browser:
    enabled: true
    provider: camoufox            # adspower / bitbrowser / hubstudio / camoufox / donutbrowser(观察)
    # ── 商用客户端（形态 A/B）──
    local_api: http://host.docker.internal:50325   # 形态 A 本地宿主；形态 B 填内网地址 http://fp-node.internal:50325
    profile_id: "mera_coding_01"  # 站点专属 profile（指纹+代理+登录态）
    startup_wait_sec: 30
    # ── Camoufox（形态 C）──
    profile_dir: /data/fp_profiles/example_leaderboard
    proxy_ref: env:PROXY_EXAMPLE_LEADERBOARD       # 代理从环境变量注入，不入库
    headless: true                                 # 有 xvfb 时可设 false 提升真实度
```

**形态 A/B：Playwright 通过 CDP 接管商用指纹浏览器（AdsPower 风格 API，其他厂商仅 HTTP 接口字段不同）：**

```python
# app/fetchers/sites/example_leaderboard/playwright.py（指纹浏览器模式）
import requests
from playwright.sync_api import sync_playwright

class Fetcher(BaseFetcher):
    strategy = "playwright_rpa"

    def _connect_fp_browser(self, fp: dict):
        # 1. 调指纹浏览器本地 API 启动指定 profile，返回 CDP 调试地址
        resp = requests.get(
            f"{fp['local_api']}/api/v1/browser/start",
            params={"user_id": fp["profile_id"], "open_tabs": 1},
            timeout=fp.get("startup_wait_sec", 30),
        ).json()
        if resp.get("code") != 0:
            raise RuntimeError(f"fingerprint browser start failed: {resp}")
        return resp["data"]["ws"]["selenium"]   # Playwright 用 puppeteer/selenium 的 ws 端点均可

    def fetch(self) -> list[dict]:
        cfg = self.cfg["playwright"]
        fp = cfg.get("fingerprint_browser", {})
        with sync_playwright() as p:
            if fp.get("enabled"):
                ws_endpoint = self._connect_fp_browser(fp)
                browser = p.chromium.connect_over_cdp(ws_endpoint)   # 接管指纹浏览器
                context = browser.contexts[0]                        # profile 自带隔离上下文
                page = context.new_page()
            else:
                browser = p.chromium.launch(headless=True)           # 普通无头兜底
                context = browser.new_context(locale="zh-CN")
                page = context.new_page()

            page.goto(cfg["url"], wait_until="networkidle")
            results = self._parse_all_pages(page, cfg)              # 解析/翻页/验证码逻辑同 4.0

            if fp.get("enabled"):
                requests.get(f"{fp['local_api']}/api/v1/browser/stop",
                             params={"user_id": fp["profile_id"]}, timeout=10)
            else:
                browser.close()
            return results
```

**形态 C：Camoufox 进程内驱动（容器一体化，无需外部客户端）：**

```python
# app/fetchers/sites/example_leaderboard/playwright.py（Camoufox 模式，页面 API 与 Playwright 一致）
import os
from camoufox.sync_api import Camoufox

class Fetcher(BaseFetcher):
    strategy = "playwright_rpa"

    def fetch(self) -> list[dict]:
        cfg = self.cfg["playwright"]
        fp = cfg["fingerprint_browser"]
        with Camoufox(
            headless=fp.get("headless", True),
            persistent_context=True,                     # 持久化 profile，等价于 storage_state
            user_data_dir=fp["profile_dir"],
            proxy={"server": os.environ[fp["proxy_ref"].removeprefix("env:")]},
        ) as browser:
            page = browser.new_page()
            page.goto(cfg["url"], wait_until="networkidle")
            results = self._parse_all_pages(page, cfg)   # 解析/翻页/验证码逻辑与形态 A/B 完全复用
        return results
```

> 三个 provider 的页面操作层共用同一套 `_parse_all_pages`：商用 CDP、Camoufox、普通 headless 仅“浏览器如何启动”不同，站点解析代码零改动。

**运维要点：**

1. **指纹环境预热**：新 profile 先人工或半自动访问正常站点“养号”（建立历史、Cookie 行为），再用于采集；新环境立刻高频访问最易触发风控；
2. **代理质量优先于指纹**：脏 IP/数据中心 IP 上再完美的指纹也容易被封；住宅代理 + 低并发 + 错峰的收益最大；
3. **并发上限**：一台机器同时运行的指纹浏览器 profile 数受内存限制（单 profile 约 300~800MB），浏览器 worker 节点按 `--concurrency` 控制同开数量，超额任务排队；
4. **合规边界不变**：指纹浏览器仅用于以“正常用户”形态访问公开数据，不得用于绕过登录/付费墙或大规模高频抓取；目标站点明确禁止自动化时仍按第 8 节改用授权 API / 数据采购 / 人工导入。

---

## 5. 方案四：Robot Framework + RPA Framework（复杂企业级场景）

当采集对象超出浏览器范畴——需要操控 **Windows 桌面软件**，或在 **Android/iOS App** 内取数——采用 Python 生态中通用性最强的开源 RPA 组合：**Robot Framework + RPA Framework**。其执行环境按操作系统分为三类节点：

* **Windows 桌面 RPA 节点**（首选 **Windows 10/11 专业版**云桌面/云主机）：承载 `RPA.Windows` 桌面软件自动化，一节点一任务，横向扩容 = 加节点；
* **Ubuntu RPA 节点**（无 Windows GUI 依赖的 robot 任务）：Web/Excel/文件处理/经网络 ADB 操作云手机等任务直接 Docker 化运行，成本最低；
* **云手机节点**：云上 Android 实例集群（ARM 云手机/Android 虚拟机），通过网络 ADB 与 Appium 接入，实现移动端 App 采集的多实例并行。

### 5.1 能力矩阵

| 目标 | 使用库 | 运行节点 | 说明 |
|---|---|---|---|
| Web 网页 | `RPA.Browser.Selenium` / Playwright | Ubuntu / Windows 桌面节点 | 关键字驱动浏览器，可与第 4 节脚本混用 |
| Windows 桌面应用 | **`RPA.Windows`**（UIA） | **Windows 桌面节点（Pro 优先）** | 基于 UIA 控件树操控原生桌面软件（点击、读取表格、导出文件） |
| 文件/Excel/PDF/邮件 | `RPA.Excel.Files`、`RPA.FileSystem`、`RPA.Email` | Ubuntu / Windows 桌面节点 | 处理导出的报表与附件（纯文件处理优先 Ubuntu） |
| Android App | **AppiumLibrary** + UiAutomator2 | Ubuntu Runner + **云手机集群** | 经 ADB over network 驱动云手机，控件定位、滑动、截屏、多实例并行 |
| iOS App | AppiumLibrary + XCUITest | macOS 节点（必需） | XCUITest 仅能在 macOS 运行；无 macOS 时 iOS 场景降级为人工导入 |
| 云手机实例管理 | 云厂商 OpenAPI（华为/红手指/阿里云等） | Ubuntu Runner | 批量开机/重启/重置环境/查询 ADB 地址 |
| 流程编排 | Robot Framework 原生 Task 语法 | 任一节点的 Runner | 一套工程内串联 Web + PC + Mobile |

### 5.2 RPA 节点操作系统选型（Windows Server 不是默认答案）

**结论：桌面软件自动化首选 Windows 10/11 专业版，而非 Windows Server；无 Windows GUI 依赖的任务首选 Ubuntu + Docker。**

| 系统 | 桌面软件兼容性 | 授权成本 | 交互会话 | 容器化 | 结论 |
|---|---|---|---|---|---|
| **Windows 10/11 专业版** | 最佳：厂商客户端按消费级 Windows 开发，组件齐全（媒体功能/商店/UAC 行为一致） | 低（云桌面按量/包月，含系统授权） | 单交互会话，自动登录即可；**无 RDS 会话限制问题** | ✗ 整 VM/云桌面交付 | **桌面自动化首选**：兼容性最好、成本最低、运维最简单 |
| Windows Server 2019/2022 | 一般：缺消费级组件，个别客户端异常（媒体特性/ SmartScreen/中文客户端兼容） | 高（License 贵；多会话需 RDS CAL） | RDP 断开会话被锁定，需 `tscon`/组策略保活 | ✗ | 仅当**需要 RDS 多会话并行桌面自动化**（一机多任务）或企业合规强制时采用 |
| Ubuntu 22.04/24.04 LTS | ✗：`RPA.Windows`/UIA 为 Windows 专有；Wine 跑客户端脆弱，**生产禁用** | 最低 | 无 GUI 需求 | ✅ 镜像化，可纳入 CI/CD | 无 Windows GUI 依赖的 robot 任务（Web/Excel/云手机 ADB）**首选** |

**选型决策：**

```text
robot 任务是否调用 RPA.Windows / 需要厂商桌面客户端？
 ├─ 是 ──> 是否需要单机多会话并行？
 │          ├─ 否（默认，一节点一任务）──> Windows 10/11 专业版云桌面 ★推荐
 │          └─ 是（预算充足、合规允许）──> Windows Server + RDS（保留 tscon/组策略保活要点）
 └─ 否（Web/Selenium、Excel 文件、网络 ADB 云手机）──> Ubuntu LTS + Docker ★推荐
```

### 5.3 Windows 桌面节点部署（专业版优先，Server 差异标注）

桌面自动化依赖**交互式桌面会话**：会话被锁定/注销时 UIA 无法操作窗口。节点部署要点：

1. **基础环境**

```powershell
# Windows 10/11 专业版云桌面/云主机（建议 4 vCPU / 8GB 起，每并行一个桌面客户端 +1~2GB）
# 1) 安装 Python 3.12（勾选 Add to PATH），建虚拟环境
py -m venv C:\mera\venv
C:\mera\venv\Scripts\pip.exe install -r requirements\rpa.txt
# 2) 安装目标桌面软件（厂商客户端/Office/导出控件等），固定版本
# 3) 安装 Chrome/Edge 与对应 chromedriver（RPA.Browser.Selenium 用）
```

```text
# requirements/rpa.txt（仅部署在 RPA 节点，不与普通 fetcher 依赖混装）
rpaframework
robotframework-appiumlibrary
playwright
```

2. **保持可交互的桌面会话不断线（关键）**

* **专业版**：云桌面通常保持控制台会话存活，配置简单——`netplwiz` 设自动登录（专用服务账号）；电源策略禁止睡眠；关闭锁屏（组策略“不显示锁屏”/注册表 `DisableLockWorkstation`）与屏幕保护；锁屏 = UIA 失明，这是专业版上最常见的任务失败原因；
* **Server 专用**：RDP 维护退出时**不要直接关闭窗口**（会锁定会话），改用 `tscon` 把会话重定向到控制台，保持桌面可被 UIA 访问：

```powershell
# 将当前 RDP 会话（如 ID 1）转接到 console，断开 RDP 后桌面会话仍存活
tscon 1 /dest:console
```

* **Server 专用**：组策略 `计算机配置 → 管理模板 → Windows 组件 → 远程桌面服务 → 会话时间限制` 中“设置断开连接会话的时间限制”为从不；
* **不要在 Session 0 的普通 Windows 服务里直接跑 Robot**（Session 0 无桌面，`RPA.Windows` 无法操作 UI）。专业版用**任务计划程序“仅在用户登录时运行”**的开机任务启动 Runner 即可；Server 可用 **NSSM** 注册 Runner 轮询服务，由其在登录用户会话内拉起 Robot 子进程。

3. **Runner 常驻与任务隔离**

```powershell
# Server 上用 NSSM 注册 RPA Runner（拉取任务、在交互会话启动 robot 进程、回调结果）
nssm install MERA-RPA-Runner C:\mera\venv\Scripts\python.exe C:\mera\runner\rpa_runner.py
nssm set MERA-RPA-Runner AppDirectory C:\mera
nssm set MERA-RPA-Runner AppEnvironmentExtra MERA_ENV=prod
nssm start MERA-RPA-Runner
```

* 每次任务在**独立工作目录与独立用户数据目录**中运行，结束后清理导出的临时文件；同一桌面软件同一时刻只允许一个任务操作（节点级互斥锁），避免多任务抢同一窗口；
* 节点打**虚拟机/云桌面快照**（安装并登录好客户端的干净态），任务异常或客户端状态污染时一键回滚；`RPA.Windows` 操作前先 `Control Window` 激活窗口，操作失败自动重启客户端再重试一次。

### 5.4 Ubuntu RPA 节点部署（无 Windows GUI 依赖的任务）

```dockerfile
# deploy/rpa-ubuntu/Dockerfile：承载 Web/Excel/云手机类 robot 任务
FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends \
        nodejs npm xvfb \
    && npm i -g appium && appium driver install uiautomator2 \
    && rm -rf /var/lib/apt/lists/*
COPY requirements/rpa.txt /tmp/rpa.txt
RUN pip install -r /tmp/rpa.txt && python -m playwright install --with-deps chromium
WORKDIR /app
ENTRYPOINT ["python", "runner/rpa_runner.py"]   # 轮询认领 web/android 标签任务
```

```bash
docker run -d --name mera-rpa-ubuntu --restart unless-stopped \
  -v /srv/mera/sites:/app/app/fetchers/sites:ro \
  -v /srv/mera/rpa-output:/app/output \
  -e MERA_CALLBACK_URL=http://backend-app:8000/internal/fetch/callback \
  mera/rpa-ubuntu:latest
```

* 适用：Web 采集（Selenium/Playwright）、Excel/CSV/PDF 处理、经**网络 ADB** 操作云手机（Appium Server 同容器运行）；
* 不适用：`RPA.Windows`/UIA、需要登录态桌面客户端的任务——这些路由到 Windows 桌面节点；
* 优点：镜像化交付、随 docker-compose/CI 管理、单任务容器隔离、成本最低；可作为 compose 的 `rpa-ubuntu` profile 与主系统同机或独立节点运行。

### 5.5 RPA 节点部署：云手机集群（Android App）

移动端不采购实体手机墙，而是租用**云手机**（华为云手机 CPH、阿里云无影移动、红手指/多多云等）或自建 Android-x86/雷电云模拟器集群，以网络 ADB 接入 Appium：

1. **三种接入方式（按云厂商能力选择）**

| 方式 | 说明 | 适用 |
|---|---|---|
| ADB over network | 云手机提供 `ip:port` 的 ADB 地址，`adb connect <ip:port>` 后等同真机 | 最通用，Appium UiAutomator2 标准方式 |
| 厂商 OpenAPI 管控 | API 批量开机/关机/重启/恢复出厂/重置设备环境/查询 ADB 映射地址 | 集群弹性调度、任务间清环境 |
| 厂商投屏/输入 API | 部分云手机仅提供 H5 画面流 + HTTP 点击坐标接口 | 无法跑 UiAutomator 时的兜底（坐标驱动，脆弱） |

2. **Appium 多实例连接云手机**

```bash
# 1) 网络 ADB 连接每台云手机（地址由云厂商控制台/OpenAPI 获取）
adb connect 10.0.0.11:5555
adb connect 10.0.0.12:5555

# 2) 每台设备启动独立端口的 Appium Server（--relaxed-security 供截图/文件管理）
appium -p 4723 -pa /device11 --default-capabilities '{"udid":"10.0.0.11:5555"}'
appium -p 4724 -pa /device12 --default-capabilities '{"udid":"10.0.0.12:5555"}'
```

Robot 任务按 `udid`/Appium 地址选择设备实例（也可单 Appium Server 靠 `Open Application` 传不同 `udid` 复用）：

```robotframework
*** Keywords ***
连接云手机执行采集
    [Arguments]    ${APPIUM_URL}    ${UDID}
    Open Application    ${APPIUM_URL}    platformName=Android
    ...    automationName=UiAutomator2    udid=${UDID}
    ...    noReset=${True}    newCommandTimeout=120
    Click Element    id=btn_gpu_price
    ${app_price}=    Get Text    id=price_text
    # 无法定位控件时（投屏兜底）改用坐标点击 + 截图 OCR
    ${screenshot}=    Capture Page Screenshot
    Quit Application
```

3. **集群调度要点**

* **一设备一任务**：Runner 维护云手机池（`udid` + Appium 端口 + 占用状态），任务借还设备；设备数 = 目标并行度；
* **任务间重置环境**：每完成一个任务调用厂商 API 恢复实例/清除 App 数据（`adb shell pm clear <pkg>`），防止上一个账号的登录态串号；
* **账号与代理隔离**：每台云手机绑定固定 App 账号与出口代理（多数云手机支持按实例配独立出口 IP），保持设备-账号-IP 三者长期一致；
* **设备状态自愈**：心跳检测 ADB 连通性，掉线则 `adb disconnect && adb connect`，仍失败调 API 重启实例；
* **iOS 限制**：云手机主流只有 Android；iOS App 自动化必须使用 macOS + XCUITest，无 macOS 资源时该数据源标记为**人工导入**，不阻塞主链路。

### 5.6 示例任务：网页取数 → 桌面软件导出 → 云手机 App 校验

```robotframework
# app/fetchers/sites/gpu_vendor_pricing/rpa/pricing_web_desktop_mobile.robot
*** Settings ***
Library    RPA.Browser.Selenium
Library    RPA.Windows
Library    AppiumLibrary
Library    RPA.Excel.Files

*** Tasks ***
采集云厂商定价并跨端校验
    # 1) Web：打开定价页，处理可能的滑块
    Open Available Browser    https://example.com/pricing    headless=True
    Run Keyword If    ${captcha_visible}    Handle Slider Captcha
    ${rows}=    Get WebElements    css:table tr.row
    # 2) Windows 桌面（专业版节点）：打开厂商客户端导出官方报价单（交互会话保活见 5.3）
    Control Window    name:定价客户端
    Click    name:导出Excel
    Wait For Element    name:导出成功
    ${price}=    Read Worksheet Cell    ${OUTPUT_DIR}${/}quote.xlsx    B12
    # 3) 云手机 Mobile：经网络 ADB + Appium 在云手机 App 内核对同型号 GPU 月租价格
    Open Application    http://appium-pool:4723/wd/hub    udid=${CLOUD_PHONE_UDID}    ...
    Click Element    id=btn_gpu_price
    ${app_price}=    Get Text    id=price_text
    # 4) 结构化结果交由 Celery/API 落库
    Log Many    web=${rows}    desktop=${price}    mobile=${app_price}
```

### 5.7 与 MERA 主系统的集成方式

Robot 任务是**独立的外部执行器**，与 FastAPI/Celery 解耦；三类节点（Windows 桌面、Ubuntu、云手机池）分别由对应的 RPA Runner 管理：

```text
Celery fetch_task (source_key=<站点>, strategy=playwright_rpa 且 requires_desktop/mobile)
        │  下发（消息携带站点 key、fetch_task_id、能力标签 desktop / web / android）
        ▼
 ┌──────────────────────────────────────────────────────────────────────────┐
 │ RPA 调度层                                                                 │
 │  ┌────────────────────────┐ ┌──────────────────────┐ ┌───────────────────┐ │
 │ │ Windows 桌面 Runner     │ │ Ubuntu Runner(Docker)│ │ Cloud-Phone Runner │ │
 │ │ (Pro:任务计划/Server:NSSM)│ │ Web/Excel/网络ADB     │ │ 云厂商OpenAPI管实例│ │
 │ │ 交互会话保活             │ │ 容器隔离、镜像交付     │ │ ADB池+Appium多端口 │ │
 │ │ RPA.Windows 操作桌面软件 │ │                      │ │ 一设备一任务清环境 │ │
 │ │ 快照回滚、节点级互斥锁   │ │                      │ │                   │ │
 │ └────────────────────────┘ └──────────────────────┘ └───────────────────┘ │
 └──────────────────────────────────────────────────────────────────────────┘
        │  输出标准化 JSON 到约定目录或回调 Webhook
        ▼
回调 POST /internal/fetch/callback/{fetch_task_id}  ──> 校验、落库、通知/自动分析
```

* 用 `robot --outputdir ... app/fetchers/sites/<站点>/rpa/xxx.robot` 命令行按站点触发，由各侧常驻 Runner 按能力标签认领任务（desktop→Windows 节点，web/excel→Ubuntu 节点，android→云手机池）；
* Windows 桌面节点必须保证**交互桌面会话存活**（见 5.3）；云手机经网络 ADB + Appium 接入，设备地址与占用状态由 Cloud-Phone Runner 维护（见 5.5）；
* 三类节点均在主系统之外独立伸缩：桌面任务受 Windows 会话数限制（通常单机单任务），Ubuntu 节点按容器副本扩容，移动任务并行度 = 云手机实例数；
* 结果统一回调，复用主系统的 `fetch_tasks` 状态机（`captcha_pending` / `succeeded` / `partial_succeeded` / `failed_exhausted`，终态分流规则见第 7 节）。

---

## 6. 验证码 (CAPTCHA) 工程实现

```python
# app/fetchers/captcha.py
class CaptchaRequired(Exception): ...

def handle_captcha(page, site_key: str) -> bool:
    """返回 True 表示已自动通过；False 表示需转人工。"""
    if _is_slider(page):
        return _solve_slider(page)               # 轨迹模拟 + 缺口识别
    if _is_click_captcha(page):
        coords = _third_party_solver(page.screenshot())  # 打码平台/自训练检测模型
        for x, y in coords:
            page.mouse.click(x, y, delay=random.randint(50, 150))
        return True
    return False  # reCAPTCHA/hCaptcha 等强验证不在此绕过
```

| 类型 | 实现 |
|---|---|
| 滑块 | OpenCV 识别缺口位置 (`cv2.matchTemplate`)，用带加速/减速/抖动的贝塞尔轨迹拖拽，`mouse.up` 前微抖 |
| 点选/旋转 | 第三方打码平台 API 或自训练 YOLO 检测目标坐标；API Key 走环境变量 |
| reCAPTCHA/hCaptcha | **不做技术绕过**：任务置 `captcha_pending`，通知管理员在有头浏览器 (`headless=False`) 人工完成，复用 `storage_state` 会话后由回调续跑 |
| 预防 | stealth 指纹、真人行为节奏、干净/住宅 IP、限频错峰、登录态复用 |

---

## 7. 统一编排：降级、重试与落库

```python
# app/fetchers/orchestrator.py（站点发现 + 站点内策略链降级）
import importlib
from pathlib import Path

SITES_DIR = Path(__file__).parent / "sites"

# 策略名 -> 站点目录内方案文件名
STRATEGY_MODULE = {
    "api": "api",
    "reverse_api": "reverse_api",
    "playwright_rpa": "playwright",
}

def load_site_strategies(site_key: str):
    """读取 sites/<site_key>/config.yaml，按声明顺序加载该站点的方案类。"""
    import yaml
    site_dir = SITES_DIR / site_key
    cfg = yaml.safe_load((site_dir / "config.yaml").read_text(encoding="utf-8"))
    strategies = []
    for name in cfg["strategies"]:
        mod = importlib.import_module(
            f"app.fetchers.sites.{site_key}.{STRATEGY_MODULE[name]}"
        )
        strategies.append((name, mod.Fetcher(cfg)))   # 每个站点方案类统一命名为 Fetcher
    return strategies

def run_fetch(task) -> None:
    site_key = task.source_key
    cfg_strategies = load_site_strategies(site_key)

    records, hit_strategy, truncated = [], None, False
    for name, fetcher in cfg_strategies:
        try:
            raw = fetcher.fetch()                        # 站点方案读取自身 config
            records, truncated = fetcher.normalize(raw) # 返回 (records, truncated)：翻页中断时 truncated=True
            hit_strategy = f"{site_key}/{name}"
            break
        except CaptchaRequired:
            task.mark_captcha_pending(); return
        except Exception as exc:
            task.log_attempt(name, exc)                  # 记录失败，降级该站点下一方案
            continue

    # 按 task_type UPSERT：model_metrics -> model_snapshots；infrastructure_cost -> infrastructure_costs
    # 注意：订阅套餐落 subscription_plans（见架构文档 4.1），不入 model_snapshots
    hit_count = upsert_records(task.task_type, records)
    reached_max = task.attempt_count + 1 >= MAX_FETCH_ATTEMPTS   # 默认 3

    # 终态以 hit_count（实际 UPSERT 的模型/资产条数）为准，而非“是否抛过异常”：
    if hit_count >= MIN_FETCH_HITS and not truncated:            # 完整命中 → 成功
        task.mark_succeeded(strategy=hit_strategy, hit_count=hit_count)
    elif hit_count >= 1 and (truncated or reached_max):
        # 达到最大尝试次数但有 ≥1 条数据（或数据被截断）→ 部分成功，降级接受、不丢弃有效数据
        task.mark_partial_succeeded(strategy=hit_strategy, hit_count=hit_count)
    elif hit_count >= 1:
        task.mark_succeeded(strategy=hit_strategy, hit_count=hit_count)
    else:
        task.bump_attempt()                              # 一条有效数据都没有
        if task.attempt_count >= MAX_FETCH_ATTEMPTS:     # 指数退避后仍为 0 → 熔断停止并告警
            task.mark_failed_exhausted()
            return

    task.notify_and_maybe_auto_start()                   # succeeded/partial_succeeded 均通知；auto_start 则接续分析
```

* 各策略结果均经 `normalize.py` 转成统一结构，核心字段建列、其余写入 `data` JSONB；
* **终态判定以 `hit_count` 为准**（详见架构文档 3.3 规则 3）：达到最大尝试次数时，只要 UPSERT 了 ≥1 条模型/资产即置 `partial_succeeded`（数据可能不完整，通知标注、`auto_start` 照常接续），仅 `hit_count=0` 才置 `failed_exhausted`；
* 实际采用的策略、每次尝试、`hit_count`/缺失范围与验证码处理记录持久化到 `fetch_tasks`，与架构文档第 4.1 节表结构对应。

---

## 8. 合规与风险边界 (再次强调)

1. 仅采集公开事实数据，遵守 `robots.txt`、服务条款、版权与数据保护法规；
2. 逆向仅限理解公开接口的参数格式，**不破解鉴权、不绕过付费、不获取非公开数据**；
3. 验证码自动化以“正常访问公开内容”为限；明确禁止自动化或要求登录授权的站点，应改用官方授权 API、采购数据服务或管理员人工导入；
4. 控制采集频率与并发，避免对目标站点造成负担；凭据统一由环境变量/密钥管理服务注入，禁止入库。
