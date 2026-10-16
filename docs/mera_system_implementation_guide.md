# MERA 系统实现文档
## 按模块开发与测试指南 (v2.0)

> **文档定位**：开发执行手册。把系统拆成 **12 张模块卡片**，每张卡片独立可开发、可测试，团队可按卡片并行领任务。
> 配套阅读：总体设计见 [`mera_architecture_document.md`](./mera_architecture_document.md)；采集策略细节见 [`mera_data_fetch_implementation_guide.md`](./mera_data_fetch_implementation_guide.md)；本地环境见架构文档第 7 节（docker-compose 已就绪）。

---

## 1. 使用方式

每个模块一张卡片，固定七段结构：

| 段落 | 内容 |
|---|---|
| 目标与边界 | 这个模块做什么、明确不做什么 |
| 代码位置 | 文件/目录路径 |
| 对外接口 | 数据结构与函数签名（**模块间只允许通过这些接口交互**） |
| 实现要点 | 关键设计决策与坑 |
| 依赖 | 上游（需要谁先完成）/ 下游（谁在等它） |
| 测试方案 | 单测怎么写、mock 什么、核心用例 |
| 验收清单 | 自检 DoD，全部勾选才算完成 |

**开发流程**：领卡片 → 读依赖模块的"对外接口"（接口冻结后无需看对方实现）→ 写接口骨架与单测 → 实现 → 单测绿 → 对照验收清单 → 交付。上游接口未完成时，可用其签名写 stub 开发，不阻塞。

---

## 2. 系统全景与模块地图

### 2.1 技术栈速览（与架构文档一致）

| 层 | 技术 |
|---|---|
| 后端 | Python 3.12 + FastAPI + SQLAlchemy 2 + Alembic |
| 任务 | Celery 5（Redis broker，队列 default / fetch_api / fetch_browser） |
| 前端 | React 18 + Vite + TypeScript + **shadcn/ui + Tailwind CSS**（组件层：代码拷贝进项目，轻量可定制）+ **TanStack Table**（榜单/表格逻辑）+ **react-hook-form + zod**（表单）+ **Recharts**（图表，与 shadcn/charts 同源） |
| 数据 | PostgreSQL 18（UUIDv7 主键 + RLS 按组织隔离）+ Redis 7 |
| 认证 | Casdoor（OIDC 授权码 + JWT 验签） |
| 采集 | requests/httpx、Playwright、指纹浏览器（商用 CDP / Camoufox） |
| 部署 | docker-compose：backend-app、frontend-app、worker-1、worker-2、beat、postgres、redis、casdoor(+独立PG)、flower |

### 2.2 模块地图与依赖关系

```text
M01 骨架与基础设施 ──> M02 数据模型与仓储 ──> M04 REST API <── M03 认证与RLS
        │                     │                    ▲
        │                     ├──> M09 选型分析引擎 ┘
        │                     └──> M10 通知服务 ──> M04
        ├──> M05 采集框架核心 ──> M06 站点采集实现
        │         │                 ▲
        │         └── M07 验证码 ───┘
        └──> M08 Celery 任务与调度（触发 M05/M06，落库走 M02）
M11 前端应用（消费 M04 的 API）
M12 部署与 CI（贯穿全程）
```

### 2.3 开发阶段（P0 可先于 P1/P2/P3 并行）

| 阶段 | 模块 | 里程碑 |
|---|---|---|
| P0 骨架可用 | M01 M02 M03 M04 M12 | 起服务、建表、登录、API 可查空数据 |
| P1 数据能进来 | M05 M06 M07 M08 | beat 定时采集 → 落库 → API 查到榜单 |
| P2 能出结论 | M09 M10 | 评分排名、任务完成通知 |
| P3 可视化 | M11 | 榜单/对比/成本页面 |

### 2.4 后端目录结构（最终形态）

```text
backend/
├── app/
│   ├── main.py                  # M01 create_app()
│   ├── core/                    # M01 settings/logging/exceptions + M03 security.py
│   ├── db/                      # M02 session.py、models/、alembic/
│   ├── repositories/            # M02 repository.py
│   ├── schemas/                 # M04 pydantic 请求/响应模型
│   ├── api/v1/                  # M04 routers: models.py / tasks.py / evaluations.py / analysis.py
│   ├── scoring/                 # M09 engine.py
│   ├── notify/                  # M10 service.py
│   ├── worker.py                # M08 celery app
│   └── fetchers/
│       ├── base.py              # M05 BaseFetcher + 异常
│       ├── config_loader.py     # M05 站点发现
│       ├── normalize.py         # M05 标准化
│       ├── signing.py           # M05 签名工具
│       ├── orchestrator.py      # M05 编排状态机
│       ├── captcha.py           # M07
│       └── sites/<site>/        # M06 每站点: config.yaml + api.py/reverse_api.py/playwright.py + normalize.py
├── tests/
│   ├── conftest.py
│   ├── unit/<module>/           # 单测：无网络无DB
│   └── integration/             # 集成：testcontainers PG/Redis
├── requirements.txt
└── scripts/start-backend.sh     # alembic upgrade head + uvicorn
```

---

## 3. 通用开发与测试约定（所有模块遵守）

### 3.1 异常体系

```python
# app/core/exceptions.py
class AppError(Exception):
    code: str; message: str          # API 层统一 handler 映射为 4xx/5xx

class ConfigError(AppError): ...      # M05 配置非法
class SecretError(AppError): ...      # M05 密钥缺失（消息不得含密钥值）
class FetchFailed(AppError): ...      # M06 采集失败（触发降级）
class CaptchaRequired(AppError): ...  # M07 强验证码（触发 captcha_pending）
class AuthError(AppError): ...        # M03 401
class InvalidTransition(AppError): ...# M02 任务状态机非法迁移
class InvalidWeights(AppError): ...   # M09 权重和≠1
```

### 3.2 配置管理
pydantic-settings 定义 `Settings`（数据库/Redis/Casdoor/SMTP/限频等，与 `.env`、docker-compose 环境变量一致）；**模块内禁止直接读 `os.environ`**，统一注入 Settings 或显式参数。

### 3.3 可测性四原则
1. **纯函数优先**：解析、标准化、评分、状态机判断 = 无副作用函数，I/O 只在外壳；
2. **依赖注入**：DB 会话、HTTP 客户端、时钟、随机数、下游服务一律构造参数注入；
3. **时间随机可注入**：涉及时间/随机的方法把 `now`/`rand` 作参数，测试用 freezegun/固定种子；
4. **边界归集成**：SQL 方言、RLS、真实浏览器行为不进单测，集成测试兜底。

### 3.4 测试分层与工具

| 层 | 目录 | 允许的依赖 | 工具 |
|---|---|---|---|
| 单元 | `tests/unit/` | 无网络、无 DB、无时间波动（单例 <50ms） | pytest、pytest-mock、freezegun、responses/respx |
| 集成 | `tests/integration/` | testcontainers 起 PG/Redis；外网仍 mock | pytest `-m integration`、Celery eager |

覆盖率门槛（`pyproject.toml` 强制）：`scoring/`、`fetchers/normalize.py`、`fetchers/orchestrator.py` ≥ 90%；其余 `app/` ≥ 80%。

### 3.5 模块通用验收项（各卡片不再重复）
- [ ] 对外接口与卡片签名一致，异常使用 3.1 体系；
- [ ] 单测全绿且不依赖网络/数据库；`pytest tests/unit -q` 通过；
- [ ] 有 golden/边界用例；CI 通过 `ruff + mypy + pytest`。

---

## 4. 模块卡片

### M01 项目骨架与基础设施

| 项 | 内容 |
|---|---|
| 目标与边界 | FastAPI app factory、Settings、结构化日志、异常 handler、`/healthz`；**不含任何业务路由** |
| 代码位置 | `app/main.py`、`app/core/{config,logging,exceptions}.py` |
| 对外接口 | `create_app(settings) -> FastAPI`；`get_settings() -> Settings`（lru_cache）；`get_logger(name)` |
| 实现要点 | app factory 模式（测试可多实例）；中间件顺序：CORS → 认证 → RLS 会话；路由 router 在 `api/v1/__init__.py` 汇总注册 |
| 依赖 | 无（起点模块） |
| 测试方案 | `create_app` 不连 DB 可构造（DB 引擎懒加载）；`/healthz` 返回 200；Settings 从 monkeypatch 的环境变量读取、缺必填项启动即报错 |
| 验收清单 | [ ] uvicorn 可启动 [ ] /healthz 200 [ ] 未知异常返回 500 且响应不含堆栈 |

### M02 数据模型与仓储层

| 项 | 内容 |
|---|---|
| 目标与边界 | ORM 模型、Alembic 迁移、`Repository` 数据访问；**不含业务规则，不含 RLS 策略本身（策略在迁移 SQL）** |
| 代码位置 | `app/db/models/`、`app/db/alembic/`、`app/repositories/repository.py` |
| 对外接口 | 表：`model_snapshots`（模型基准/按量单价）、`infrastructure_costs`、`subscription_plans`（订阅套餐，独立表）、`fetch_tasks`、`user_evaluations`（均含 `data` JSONB、UUIDv7 主键）。仓储：`upsert_snapshots(records)->int`、`upsert_costs(records)->int`、`upsert_subscription_plans(records)->int`、`create_task/mark_succeeded/mark_partial_succeeded/mark_failed_exhausted/mark_captcha_pending`、`latest_snapshots(domain)->list`、`cheapest_active_plan(provider)->SubscriptionPlan|None` |
| 实现要点 | UPSERT 幂等键：快照=(model_id, domain)，成本=(cost_type,name,region)，套餐=(provider,plan_key,billing_cycle)；`fetch_tasks` 增 `hit_count INT DEFAULT 0` 列与 CHECK（`failed_exhausted` 时 `hit_count=0`）；任务状态机 `pending→running→succeeded/partial_succeeded/captcha_pending→failed_exhausted`（`partial_succeeded`：达到最大尝试次数但 `hit_count≥1`，或数据被截断），非法迁移抛 `InvalidTransition`。订阅套餐不进 `model_snapshots`（粒度为厂商账号级、一个套餐覆盖多模型且带用量上限） |
| 依赖 | M01 |
| 下游 | M04 M05 M06 M08 M09 M10 |
| 测试方案 | 单测：SQLite/内存会话验证三类 UPSERT 幂等（重复键行数不变、值更新）、状态机全部合法/非法迁移（重点：`hit_count≥1` 到顶只能 `partial_succeeded` 不得 `failed_exhausted`；`hit_count=0` 到顶只能 `failed_exhausted`）、部分冲突批量、事务回滚；集成：真实 PG 验证 JSONB、RLS 隔离、UUIDv7、`ck_fetch_terminal_hit_count` 约束 |
| 验收清单 | [ ] alembic upgrade head 可从空库建全五表 [ ] 幂等用例通过 [ ] 部分成功终态分流用例通过 [ ] RLS 集成用例通过 |

### M03 认证与授权（Casdoor OIDC + RLS）

| 项 | 内容 |
|---|---|
| 目标与边界 | JWT 验签、身份提取、DB 会话 RLS 变量注入；**不做用户管理（Casdoor 负责）、不做菜单权限存储（Casdoor RBAC）** |
| 代码位置 | `app/core/security.py`、`app/api/depends.py` |
| 对外接口 | `decode_token(token, jwks, now) -> Identity(user_id, org_id, roles)`；FastAPI 依赖 `get_current_identity`、`get_db_session(identity)`（SET LOCAL rls 变量后返回会话） |
| 实现要点 | JWKS 启动时拉取并缓存（注入时钟做缓存过期）；`alg` 白名单防混淆；RLS 变量值做引号转义防注入 |
| 依赖 | M01；Casdoor 配置（架构文档 7.3） |
| 测试方案 | 单测：fixture 本地生成 RSA keypair 构造 token，覆盖合法/过期（now 注入推后）/篡改签名/错误 aud/无 org 各分支；`build_rls_vars` 转义用例 |
| 验收清单 | [ ] 全部非法 token 分支抛 `AuthError` 且 401 [ ] RLS 会话集成用例通过 |

### M04 REST API

| 项 | 内容 |
|---|---|
| 目标与边界 | 路由、pydantic 请求/响应模型、状态码、依赖装配；**业务计算委托 M09，数据访问委托 M02** |
| 代码位置 | `app/api/v1/`、`app/schemas/` |
| 对外接口（路由表） | `GET /api/v1/models?domain=`（榜单）、`GET /api/v1/models/{id}/snapshots`（历史）、`POST /api/v1/fetch-tasks`（手动触发采集，202）、`GET /api/v1/fetch-tasks`、`GET/POST /api/v1/evaluations`（用户评测 CRUD）、`GET /api/v1/subscription-plans?provider=`（活跃套餐，供前端比价展示）、`POST /api/v1/analysis/run`（触发评分，返回结果）、`POST /internal/fetch/callback/{task_id}`（RPA 回调，内网鉴权）；管理端（admin 角色）：`GET/PUT /api/v1/admin/subscription-plans`、`GET/PUT /api/v1/admin/infrastructure-costs`、手动重触发 `failed_exhausted` 任务 |
| 实现要点 | 分页参数统一；业务异常 → 3.1 映射；入队用 `send_task` 按队列名路由 |
| 依赖 | M02 M03（M09 完成前 analysis 路由可返回 501 占位） |
| 测试方案 | TestClient + `dependency_overrides` 替换 identity 与 repo（M02 未就绪时用 Mock）：参数校验 422、无 token 401、repo 业务异常 → 404/409、入队调用被记录 |
| 验收清单 | [ ] OpenAPI 文档可访问 [ ] 每条路由至少 正常/鉴权失败/参数非法 三个用例 |

### M05 采集框架核心（五件套，✅ 已实现）

| 项 | 内容 |
|---|---|
| 目标与边界 | 站点配置发现、标准化、签名工具、编排状态机、BaseFetcher 抽象；**不含具体站点实现（M06）** |
| 代码位置 | `app/fetchers/{base,config_loader,normalize,signing,orchestrator}.py` |
| 对外接口 | `discover_sites(dir)/load_site(dir,key)`（非法配置抛 `ConfigError`，只注册站点已实现且在 `config.yaml.strategies` 中声明的方案）；`is_strategy_available(fetcher)->bool`（可选前置检查，判断依赖、密钥、会话/浏览器 profile 是否就绪）；`normalize_records(raw,cfg)->(records, truncated)`、`parse_score/parse_price/canonical_model_name`（纯函数，脏值返回 None 不抛异常）；`sign_hmac_md5(params,secret,timestamp)`（时间戳显式传参）、`read_secret("env:X")`；`run_fetch(task, fetchers, repo, clock)`；`BaseFetcher{strategy, is_available()=True, fetch(), normalize(raw)}` |
| 实现要点 | **方案按站点可选**：不是每个站点都必须实现 api/reverse_api/playwright/指纹浏览器；目录中缺少方案文件、未在 `strategies` 声明，或 `is_available()=False`（如缺 API Key、无登录会话、未配置浏览器 profile）都记录为 `skipped` 后直接进入下一方案，不视为异常、不消耗网络重试。配置引用了不存在/非法方案名才抛 `ConfigError`；声明了方案但运行时密钥或会话缺失则跳过。run_fetch 状态机：遍历站点声明的已实现方案，任一方案返回并 normalize 出有效数据即止，记录 `fetch_strategy="site/方案"`；`FetchFailed` 降级下一方案；`CaptchaRequired` 立即短路置 `captcha_pending`；normalize 空结果视为该方案未命中并继续降级；所有可用方案均跳过或失败且 `hit_count=0` 时走指数退避重试，attempt≥3 → `failed_exhausted`。**终态按 hit_count 分流（架构 3.3 规则 3）**：`hit_count≥MIN_FETCH_HITS(默认1)` 即成功停止；达到最大尝试次数但 `hit_count≥1`（或 `truncated=True` 翻页截断）置 `partial_succeeded` 而非失败，通知标注不完整、auto_start 照常接续；最终没有任何有效数据（0 条）才算失败熔断。阈值 `MIN_FETCH_HITS/MAX_FETCH_ATTEMPTS` 由 Settings 注入 |
| 依赖 | M02（repo 接口）；M01 |
| 下游 | M06 M07 M08 |
| 测试方案 | 全部假体：FakeFetcher（构造时给 available、records 或 error 或 truncated）、FakeTask（记录状态迁移与 skipped 原因）、Mock repo（返回注入的 hit_count）、clock 注入。核心用例：①配置缺 key/strategies 非法/引用不存在方案→ConfigError，站点未实现未声明的方案不报错；②parse_score/price 脏值矩阵（"89.5 分"/"N/A"/"$3.00"/负数）；③签名 golden 值+参数顺序无关+secret 不出现在异常消息；④状态机分支（首方案成功/降级成功/缺文件跳过/**is_available=False 因缺密钥或会话跳过**/跳过与失败混合后继续/**全部跳过且 hit_count=0→failed_exhausted**/**到顶 hit_count=2→partial_succeeded 且不熔断**/**到顶 hit_count=0→failed_exhausted**/**truncated=True→partial_succeeded**/重试退避时间断言/验证码短路/空结果降级）；⑤normalize 幂等 |
| 实现状态 | **✅ 已实现（2026-10）**：五件套全部落地。`run_fetch` 复用 M02 `decide_run_result`，终态语义与仓储层完全一致；不可用方案的 skip 记录在一次运行内按方案名去重（失败日志仍每轮记录）；`RepoTaskHandle` 适配 M02 仓储任务方法族，skip/failure/empty 明细入 `event_log`。单测 `tests/unit/m05/`（config_loader/normalize/signing/orchestrator 四组 + fakes.py 假体），与 M06 合计 131 用例全绿、ruff 通过，无任何网络/DB 依赖 |
| 验收清单 | [x] 状态机分支覆盖 100%，含“未实现/不可用方案跳过”分支 [x] 所有可用方案结束仍 0 条时才 `failed_exhausted` [x] 单测无任何网络/DB 依赖 |

### M06 站点采集实现（api / reverse_api / playwright / 指纹浏览器，✅ 首批已实现）

| 项 | 内容 |
|---|---|
| 目标与边界 | 具体站点的 Fetcher 类，返回原始记录；**解析逻辑必须可脱离网络单测**。每个站点只实现可用且合规的一种或多种方案，不要求四种方案齐全；只要任一方案成功取得有效数据即可 |
| 代码位置 | `app/fetchers/sites/<site>/{config.yaml, api.py, reverse_api.py, playwright.py, normalize.py}`；新增站点=新增目录，框架零改动 |
| 对外接口 | 每方案类统一 `class Fetcher(BaseFetcher)`；**强制拆分**：`build_request(page)->RequestSpec`（纯函数：url/headers/签名）、`parse_response(payload)->list[dict]`（纯函数）、`parse_dom(rows)->list[dict]`（DOM 解析纯函数）；fetch() 本体只做“构造→请求→解析→异常分类”编排。`config.yaml` 必须声明 `strategies`、数据类型、登录要求（`auth_required/type/session_ref`）、限频与合规开关 |
| 实现要点 | 异常分类：HTTP 4xx/超时/坏 JSON → `FetchFailed`；响应体 `code=CAPTCHA_REQUIRED` → `CaptchaRequired`；限频 sleep 经注入；指纹浏览器按 config `provider`（adspower/bitbrowser 经 Local API + CDP；camoufox 进程内；详见采集指南 4.1）。**选择路线原则**：官方 API/公开 JSON/CSV > 前端逆向接口 > Playwright DOM > 指纹浏览器；后两者只在公开数据无法用前两种稳定获取时使用。需要登录的站点必须显式声明并复用授权会话；没有授权凭据时方案 `is_available()=False`，由 M05 跳过，不做账号破解、不绕过付费/隐私墙 |
| 依赖 | M05 |
| 测试方案 | `responses/respx` 注册 200/403/超时/坏 JSON/验证码响应 → 断言异常类型与 RequestSpec 内容（secret 不出现）；假 `page` 对象（Mock(spec=Page) 返回预制元素）测 parse_dom 与分页循环终止；指纹 Local API 用 responses mock start/stop；缺少 API Key/session/profile 时断言方案被标记为 skipped，而不是失败或发起网络请求 |
| 实现状态 | **✅ 首批已实现（2026-10）**：3 个站点覆盖三类路线——openrouter（官方 API）、artificial_analysis（逆向接口 + Playwright 兜底）、aider_leaderboard（Playwright 公开表格），明细见 M06.1 进度表。单测 `tests/unit/m06/`（站点配置冒烟 + 各站点方案共五组）：`responses` mock 全部 HTTP（200/403/超时/坏 JSON/验证码）、假 `page` 对象测 DOM 解析与翻页终止、指纹浏览器 Local API start/stop mock、密钥/会话缺失断言 skipped 且不发起请求 |
| 验收清单 | [x] 首批至少 3 个站点：1 个官方/公开数据、1 个逆向接口、1 个 Playwright/指纹兜底跑通 [x] 每站点单测覆盖请求构造+解析+异常分支+会话缺失跳过 [x] `config.yaml` 明确登录要求与实际采用路线 |

#### M06.1 首批站点/数据源目录（P1 建议实现，可按可访问性裁剪）

> 优先级表示建议落地顺序，不要求一次性全部实现。实际实施前需重新确认目标站点当前服务条款、robots 与页面结构；禁止采集非公开数据、个人私信或个人敏感信息。

**各站点数据获取实现进度（2026-10 更新）**

| 站点 | 类别 | 状态 | 数据获取实现说明 |
|---|---|---|---|
| OpenRouter | A 榜单 / B 聚合价格 | ✅ 已实现 | `strategies: [api]`：官方 Models API 公开 JSON（`GET /api/v1/models`，`records_path: data`），`auth_required: false`，可选 `env:OPENROUTER_API_KEY` 提高限额（缺失不影响可用性）；限频 30/min 经注入 sleep 控制；字段映射含 `pricing.prompt/completion` 点路径取价；`build_request/parse_response` 纯函数可单测 |
| Artificial Analysis | A 榜单 | ✅ 已实现 | `strategies: [reverse_api, playwright]`。reverse_api 为主：逆向前端结构化接口，HMAC-MD5 签名（sorted 参数 + timestamp），密钥 `env:AA_SECRET` 不进请求参数、缺失时 `is_available()=False` 由 M05 记 skipped 后自动降级；`parse_response` 返回 `(records, has_more, truncated)` 三元组区分服务端截断与翻页。playwright 兜底：公开榜单页表格解析 + 翻页，可选指纹浏览器（`fingerprint_browser.provider` 支持 camoufox/adspower/bitbrowser，默认关闭） |
| Aider Leaderboard | A 编程榜单 | ✅ 已实现 | `strategies: [playwright]`：公开页面 HTML 表格解析（`auth_required: false`），单页榜单无翻页（`next_selector: null`），`domain: coding`，provider 缺省回填 `aider`；`parse_dom` 纯函数 + 假 page 单测 |
| LiveCodeBench | A 编程榜单 | ⬜ 待实现 | 规划路线：HF/GitHub 公开数据集文件；新增站点目录即可，框架零改动 |
| LMArena / Chatbot Arena | A 榜单 | ⬜ 待实现 | 规划路线：前端 XHR 逆向 → Playwright/指纹兜底；触发验证码转 M07 |
| Vellum / OpenCompass / SuperCLUE / HF Open LLM | A 榜单 | ⬜ 待实现 | 规划路线见下表 A；优先公开发布的数据文件 |
| OpenAI / Anthropic / Google 定价页 | B 价格/套餐 | ⬜ 待实现 | 规划路线见下表 B；账号内合同价不自动采集 |
| 国内厂商（DeepSeek/Kimi/GLM/百炼/千帆等） | B 价格 | ⬜ 待实现 | 规划路线：官方价格页/公开 JSON → Playwright |
| 云厂商 GPU 价格（AWS/Azure/GCP 等） | B 基础设施成本 | ⬜ 待实现 | 规划路线：官方 Price List API（最小只读凭据） |
| 订阅套餐页（Plus/Pro/Max 等） | B 订阅套餐 | ⬜ 待实现 | 以管理员录入为主，采集仅作补充 |
| X / Reddit / HN / PH / YouTube | C 舆情信号 | ⬜ 待实现（P2 可选） | 仅官方 API 授权路线；未配置凭据时 `is_available()=False` 跳过 |

> 已实现的 3 个站点对应下表 A/B 中的 P0/P1 行；其余行保持规划口径不变，实施时按"新增站点目录 + config.yaml 声明"接入，`app/fetchers/` 框架代码零改动。

##### A. 模型与编程能力榜单

| 优先级 | 站点/数据源 | 需要的数据 | 首选获取方式 | 备选方式 | 登录/会话要求 |
|---|---|---|---|---|---|
| P0 | OpenRouter Rankings / Models | 模型名、排名、公开评分/标签、上下文、输入/输出价格、开源状态 | 官方 Models API / 公开 JSON | Playwright 渲染榜单兜底 | 通常不需要登录；若使用带额度的 API Key，从环境变量注入 |
| P0 | Aider Leaderboard（LLM code editing leaderboard） | 模型名、代码编辑通过率、版本、成本、榜单时间 | 公开页面 HTML；优先查找其生成榜单用的公开数据文件/仓库 | Playwright 解析表格 | 不需要登录会话 |
| P0 | LiveCodeBench | 模型编程评测结果、题目集、通过率/指标 | Hugging Face/GitHub 上的公开数据集、JSON/CSV 或代码中的数据文件 | Playwright 访问项目页 | 数据集公开读取通常不需要登录；私有/限流时使用只读 token |
| P1 | LMArena / Chatbot Arena | 竞技场 Elo/Chatability/编程榜单、模型显示名 | 优先查公开数据/API；无稳定公开 API 时逆向前端 XHR | Playwright；触发强风控时 Camoufox/指纹浏览器仅访问公开榜单 | 默认不登录；不得采集用户对话。触发验证码转 M07，reCAPTCHA/hCaptcha 不绕过 |
| P1 | Artificial Analysis | 综合质量、速度、价格、上下文、API 价格对比 | 逆向前端结构化接口 | Playwright 表格解析；必要时指纹浏览器 | 公开榜单页一般不登录；若站点明确限制自动化则停用，改人工/授权数据 |
| P1 | Vellum LLM Leaderboard | 模型能力、价格、上下文、延迟对比 | Playwright/公开页面接口逆向 | 指纹浏览器低频兜底 | 公开页通常不登录；遵守其条款与限频 |
| P2 | OpenCompass / SuperCLUE | 中文/综合能力榜单、模型名与分数 | 公开榜单页、GitHub/发布的结果文件 | Playwright 解析 | 不需要登录；优先使用公开发布的数据文件 |
| P2 | Hugging Face Open LLM Leaderboard（或其历史归档） | 开源模型综合分、榜单快照 | HF Hub/数据集公开 API 或归档数据 | 人工导入历史快照 | 公开数据无需登录；API 限流时配置只读 token |

##### B. API 价格、订阅套餐与基础设施成本

| 优先级 | 站点/数据源 | 需要的数据 | 首选获取方式 | 备选方式 | 登录/会话要求 |
|---|---|---|---|---|---|
| P0 | OpenAI Pricing / API docs / model docs | 模型名、输入/输出 token 单价、缓存/批处理价、上下文、订阅套餐公开价格 | 官方定价页面/文档结构化接口；若官方提供价格 API/文件则优先 | Playwright 解析定价表；管理员人工复核 | 公开定价页不登录；账号内专属折扣/合同价不自动采集，由管理员录入 |
| P0 | Anthropic Models / Pricing | Claude 模型价格、上下文、缓存读写价、Pro/Max 套餐公开价 | 官方文档/定价页逆向 XHR 或 Playwright | 管理员维护订阅套餐 | 公开页不登录；不采集账号私有计费数据 |
| P0 | Google Gemini API Pricing / AI Studio | Gemini 模型、免费/付费 token 价、上下文、订阅公开信息 | 官方文档/价格页 Playwright 或公开结构化数据 | 管理员录入 | 公开页不登录；Google Cloud 账号内价格不爬取 |
| P1 | DeepSeek / Moonshot Kimi / 智谱 GLM / 通义百炼 / 火山方舟 / 百度千帆 | 模型目录、token 单价、免费额度、套餐/企业价说明 | 官方价格页/开发者文档 API；优先找公开 JSON | Playwright；部分国内站点可用 Camoufox 降低风控 | 公开价格不登录；控制台内价格必须使用授权账号会话或改管理员录入，禁止绕过登录 |
| P1 | OpenRouter / DeepInfra / Together AI / Fireworks / Groq | 聚合模型目录、按量价格、上下文与支持状态 | 官方 Models/Pricing API 或公开 JSON | Playwright | 公开模型目录通常不登录；API Key 仅用于官方授权读取 |
| P1 | AWS / Azure / GCP / Oracle Cloud 价格目录 | GPU/计算实例、区域、小时/月价、存储/网络费用 | 官方 Price List API、价格 JSON/CSV | Playwright 读取公开价格页 | AWS Price List API 可能需要 IAM 凭据（最小只读权限，环境变量注入）；Azure/GCP 使用官方价格接口；不采集合同私有价 |
| P2 | CoreWeave / Lambda / RunPod / Vast.ai / 腾讯云/阿里云/华为云 GPU | GPU 型号、区域、现货/包月价、显存、CPU/内存/带宽 | 官方 API/公开价格 JSON 优先 | Playwright；动态风控站点使用指纹浏览器 | 公开报价不登录；现货价格和账号折扣需授权 API；云厂商控制台会话只能由管理员授权保存 |
| P2 | 订阅套餐页（ChatGPT Plus/Pro、Claude Pro/Max、Gemini AI Plus/Pro、Copilot Pro 等） | 厂商、套餐键、月费/年费、用量上限、覆盖模型、是否活跃 | 公开订阅页 Playwright/结构化解析 | **管理员后台录入为主**，采集仅作补充 | 公开价格不登录；账号实际权益、团队价、合同价不自动抓取 |

##### C. 社交/舆情信号（X 等，作为可选数据源）

| 优先级 | 站点 | 需要的数据 | 推荐获取方式 | 不采用/降级方式 | 登录/会话要求 |
|---|---|---|---|---|---|
| P2 | X（Twitter） | 官方模型厂商账号、官方发布链接、模型发布/降价公告、公开互动计数；仅作发布时间与舆情辅助信号 | **X API 官方授权**（Bearer Token/OAuth，只读取授权范围内公开推文）；无预算或无权限时禁用该站点 | 不做密码登录抓取、不绕过付费墙、不抓取私信/关注者隐私；强风控场景不作为 P1 任务 | 需要官方 API 凭据；未配置则 `is_available()=False` 并跳过。人工浏览登录态不得用于高频抓取 |
| P2 | Reddit | 模型发布讨论、公开帖子热度、公开评论的事实性链接 | Reddit 官方 API（OAuth 只读）或公开 JSON（严格限频） | Playwright 低频读取公开页 | API 需要 client_id/secret；公开页不登录，不采集用户隐私画像 |
| P2 | Hacker News | 模型/价格公告链接、分数、评论数、发布时间 | Firebase/Algolia 官方公开 API | 无需浏览器兜底 | 不需要登录 |
| P2 | Product Hunt | 新产品/AI 模型发布、公开投票数 | 官方 GraphQL API | 停用，不做登录态抓取 | 需要开发者 token |
| P2 | YouTube（官方频道/发布会） | 官方发布视频标题、发布时间、链接、字幕中的模型信息（可选） | YouTube Data API；字幕只取官方公开内容 | Playwright 仅读取公开视频页 | API Key；不采集个人观看记录/非公开字幕 |

> 社交数据只用于“官方发布信号/热度辅助”，不能直接等同于模型能力分数；在没有独立舆情表或评分口径前，只把来源 URL、发布时间、摘要写入快照 `data` JSONB，不参与 M09 硬性排名。微博、知乎、LinkedIn 等需要登录或条款限制较强的站点，首期不做自动抓取；确有需要时走官方 API、采购数据或管理员人工导入。

#### M06.2 站点实现与登录会话约定

1. **策略声明**：`config.yaml.strategies` 只列本站已实现且合规可用的方案，例如 `strategies: [api]` 或 `[reverse_api, playwright]`；未列方案由 M05 自然跳过。指纹浏览器不是第二种策略，而是 `playwright` 方案中的 `fingerprint_browser.provider` 配置。
2. **登录状态枚举**：`auth_required: false`（公开页）、`api_key`（官方只读密钥）、`oauth_token`（官方 OAuth）、`browser_session`（管理员授权的浏览器 storage state/profile）。凭据通过环境变量或密钥管理注入，登录态按站点 profile 持久化，不提交到仓库。
3. **会话缺失处理**：方案初始化时检查 key/token/session/profile；缺失即 `is_available()=False`，记录 skipped 原因（不得包含密钥值），继续下一方案；没有任何可用方案则本次 0 命中，按 M05 重试与熔断。
4. **指纹浏览器使用边界**：仅用于公开页面的强风控场景（如 LMArena、部分国内价格页），优先 Camoufox 容器化；AdsPower/BitBrowser 只在带桌面会话的专用节点启用。reCAPTCHA/hCaptcha、登录验证、付费墙一律转人工或停用该源。
5. **首批落地建议**：先做 OpenRouter（API）、LiveCodeBench 或 Aider（公开数据/页面）、Artificial Analysis 或 Anthropic 定价（逆向结构化接口 + Playwright 兜底）、OpenAI 定价（Playwright/页面解析），确保覆盖 API、公开数据集、逆向、浏览器解析和无登录公开数据；随后补 LMArena 与云厂商价格。

### M07 验证码处理

| 项 | 内容 |
|---|---|
| 目标与边界 | 验证码**分派与状态上报**；滑块/点选的图像识别算法用离线样本测试；**reCAPTCHA/hCaptcha 不绕过，直接转人工** |
| 代码位置 | `app/fetchers/captcha.py` |
| 对外接口 | `classify(page_view) -> CaptchaKind|None`（对页面特征快照做纯判断）；`handle_captcha(page, site_key, solver=注入)` |
| 实现要点 | `PageView` dataclass（html 片段/截图 bytes）解耦真实 page；solver 接口注入（打码平台/自训练模型） |
| 依赖 | M05 |
| 测试方案 | classify 四类特征用例；solve_slider 注入固定缺口坐标断言轨迹序列含加速/微抖；solver 超时 → 返回 False 不抛网络异常；recaptcha → 直接 False |
| 验收清单 | [ ] 强验证码路径必达 `captcha_pending` [ ] 无绕过 reCAPTCHA 的代码路径 |

### M08 Celery 任务与调度

| 项 | 内容 |
|---|---|
| 目标与边界 | 任务注册、队列路由、重试退避、beat 计划；**编排逻辑在 M05，这里只做触发与配置** |
| 代码位置 | `app/worker.py`、`app/tasks/fetch.py` |
| 对外接口 | `celery_app`；`run_fetch_task(task_id)`；beat_schedule 由站点配置生成 |
| 实现要点 | 路由：含浏览器策略 → `fetch_browser`（worker-2），API/逆向 → `fetch_api`（worker-1），两者都消费 `default` 互为冗余；autoretry max=3 指数退避（与 M05 熔断一致） |
| 依赖 | M05 M06 M02 |
| 测试方案 | `task_always_eager=True` + fakeredis：断言 routing_key、eager 执行触发注入的 orchestrator/repo、重试计数、beat 计划与站点配置一致 |
| 验收清单 | [ ] eager 全链路单测通过 [ ] 队列路由用例通过 |

### M09 选型分析引擎（业务核心，纯函数）

| 项 | 内容 |
|---|---|
| 目标与边界 | 榜单归一化、TCO 估算、加权排名；**零 I/O，全部输入输出为 dataclass** |
| 代码位置 | `app/scoring/engine.py`、`app/scoring/models.py` |
| 对外接口 | `normalize_benchmark(scores, method)->dict`；`estimate_tco(cost: InfraCost, tokens_per_month)->float`（租赁/采购折旧+电费+带宽）；`break_even_subscription(api_cost, plans: list[SubscriptionPlan])->SubscriptionPlan|None`（选覆盖候选模型厂商的最低可用套餐，套餐数据来自 `subscription_plans` 表、由调用方注入，引擎不读 `model_snapshots` 的价格键）；`rank_models(inputs: RankInputs, weights: Weights)->list[RankedModel]` |
| 实现要点 | 权重和≠1 抛 `InvalidWeights`；分数归一到 [0,1]；缺项模型不崩溃；同分字典序稳定排序；订阅档位（月费+用量上限）作为输入 dataclass 参与 API vs 订阅 vs 自部署三方案比对，引擎本身零 I/O |
| 依赖 | M02（只读其输出结构，不直接查询） |
| 下游 | M04 |
| 测试方案 | minmax 边界（全相同值→0.5）；TCO 各成本项公式断言；权重全打价格→最低价第一；break_even：无可用套餐→None / 多套餐取最低价 / 用量上限低于输入量级时标记“不够用”；性质测试（任意输入分值∈[0,1]、确定性）；golden case：5 模型预制输入→固定排序快照 |
| 验收清单 | [ ] 覆盖率 ≥90% [ ] golden case 入库存档 |

### M10 通知服务

| 项 | 内容 |
|---|---|
| 目标与边界 | 任务完成后的 WebSocket 推送 + 邮件通知 + auto_start 接续分析；**通知失败不影响任务状态** |
| 代码位置 | `app/notify/service.py` |
| 对外接口 | `notify_task_done(task, ws_hub, mailer)`（全依赖注入）；`render_mail(task)->MailMessage`（纯函数） |
| 实现要点 | ws_hub/mailer 为接口；SMTP 未配置时跳过邮件仅 WS；通知按终态分支文案：`succeeded`（数据就绪，含 hit_count）、`partial_succeeded`（**数据可能不完整**，展示 hit_count 与缺失范围，auto_start 仍接续）、`failed_exhausted`（0 条数据，引导重试/联系管理员）、`captcha_pending`（等待人工过码） |
| 依赖 | M02 |
| 测试方案 | Mock ws_hub/mailer 记录调用；断言 payload 含 task_id/status/hit_count；render_mail 四终态主题/正文关键词（partial 必须含“不完整”提示）；ws 异常被吞并记日志 |
| 验收清单 | [ ] 通知失败用例通过 [ ] 不直连真实 SMTP |

### M11 前端应用

| 项 | 内容 |
|---|---|
| 目标与边界 | 榜单浏览、模型对比分析、成本对比、采集任务管理、Casdoor OIDC 登录；**通过 M04 API 交互，不直连 DB** |
| 代码位置 | `frontend/src/{pages,api,stores,lib}/`；`frontend/src/components/ui/`（shadcn 生成组件，**纳入版本管理**） |
| 实现要点 | **组件层用 shadcn/ui + Tailwind CSS**：组件源码拷贝进 `components/ui/`（Radix 原语），样式走 Tailwind + CSS 变量主题（class 策略暗色模式），可自由改不依赖库版本升级；**表格逻辑用 TanStack Table**（榜单排序/分页/筛选在 `useLeaderboardTable` 等 hook 中实现，UI 只渲染 columns），**表单用 react-hook-form + zod**（schema 与后端 pydantic 字段对齐），**图表用 Recharts** 封装单一 `<Chart option/data>` 组件（榜单趋势折线、对比雷达、TCO 堆叠柱状）；图标 lucide-react、Toast 用 sonner；不引入第二套组件库（antd 作为备选：仅当后续页面膨胀、需要开箱即用的重型表格/表单时再评估）。API client 层统一封装（token 注入/401 跳转）；评分展示直接消费 M09 输出结构 |
| 依赖 | M04 |
| 测试方案 | Vitest + Testing Library；MSW mock `/api` 响应；组件测：榜单 Table 渲染/排序（断言自己实现的 hook 逻辑 + `data-testid`，Radix 交互用 `userEvent` 驱动）、表单校验（zod schema 纯函数直测）、`<Chart>` mock Recharts 实例只断言收到正确数据；store reducer 单测 |
| 验收清单 | [ ] 核心页面组件单测通过 [ ] MSW 下无真实网络请求 |

### M12 部署与 CI

| 项 | 内容 |
|---|---|
| 目标与边界 | docker-compose 全栈（已就绪，见架构文档第 7 节）+ CI 流水线；**不含生产运维手册** |
| 代码位置 | `docker-compose.yaml`、`.github/workflows/ci.yml`、`backend/Dockerfile`、`frontend/Dockerfile` |
| 实现要点 | CI 两级：PR 跑 `ruff + mypy + pytest tests/unit`（无 Docker 依赖）；merge 前 `pytest tests/integration`（testcontainers）；镜像构建用 compose 同一 Dockerfile |
| 测试方案 | compose `config` 校验；CI 本身以流水线绿灯为验收 |
| 验收清单 | [ ] PR 流水线 <10min [ ] 本地 `docker compose up -d` 全栈健康 |

---

## 5. 集成测试与联调场景（模块卡片之外的三条端到端链路）

| 场景 | 链路 | 断言 |
|---|---|---|
| S1 API 全链路 | 登录 token → M03 → M04 → M02(RLS) | org A 用户查不到 org B 的评测；401/403 正确 |
| S2 采集链路 | beat/eager 触发 → M08 → M05 → M06(mock 站点) → M02 → M04 可查 | 采集后 API 能查到新 snapshot；fetch_tasks 状态正确（含部分成功：到顶且 hit_count≥1 → `partial_succeeded`，0 条 → `failed_exhausted`） |
| S3 降级链路 | M06 站点全方案 mock 失败 ×3 | 任务 `failed_exhausted`；告警通知（M10）触发一次 |

集成环境：`docker compose up -d` 起 PG/Redis，站点 HTTP 用 `responses`/本地 mock server（compose 内 `mock-target` 服务，可选）。

---

## 6. 开发里程碑总 Checklist

```text
P0 骨架可用
  [ ] M01 服务启动 + /healthz
  [ ] M02 五表迁移（含 subscription_plans、fetch_tasks.hit_count）+ 仓储单测
  [ ] M03 Casdoor 登录 + RLS 集成用例
  [ ] M04 路由骨架 + OpenAPI
  [ ] M12 CI 绿灯
P1 数据能进来
  [x] M05 五件套（状态机分支 100%，131 用例含 M06 全绿）
  [x] M06 首批至少 3 站点（API/公开数据、逆向、Playwright 兜底各覆盖一类）
  [ ] M07 验证码分派
  [ ] M08 beat 定时 → API 可见数据
P2 能出结论
  [ ] M09 评分引擎 + golden case
  [ ] M10 通知
  [ ] POST /analysis/run 端到端
P3 可视化
  [ ] M11 五页面 + 组件单测
```
