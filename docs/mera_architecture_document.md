# 智能模型选型与决策分析系统 (MERA)
## 系统设计与架构规格说明书 (v4.2)

---

## 1. 系统定位与核心边界 (System Scope & Boundaries)

### 1.1 系统定位
**MERA (Model Evaluation & Selection System)** 是一个专注于 **大模型任务评估、算力开销推演与最佳选型规划** 的决策支持系统。系统利用异步任务调度与多维度分析算法，帮用户解决“如何为特定业务选出性能最强、性价比最高模型”的难题。

### 1.2 系统边界与职责划定
* **In-Scope (本系统负责)**：
  1. **异步数据采集**：通过 Celery 调度任务从外部源（LMSYS, LiveCodeBench, OpenRouter 等）采集模型性能基准与 API 价格，持久化存入数据库。
  2. **智能选型分析**：直接基于本地数据库存储的模型元数据，进行性能 vs. 成本推演、订阅计划 Break-even 盈亏平衡分析，并在调用量级达到阈值时给出**自部署 (Self-Hosted GPU)** 方案的成本比对与建议。
  3. **产物导出**：生成 Markdown 选型报告，并导出兼容现有开源 Proxy（如 LiteLLM Proxy）的 YAML 配置文件。
  4. **统一认证与权限**：通过 Casdoor 统一授权系统提供 OIDC 登录与菜单级权限授权，并由数据库行级安全 (RLS) 实现数据隔离。
  5. **管理面板**：提供管理员视角的后台面板，支持查看/检索全部模型快照数据、全部用户评估数据等，其访问入口与菜单权限均由 Casdoor 统一下发。
* **Out-of-Scope (使用现有开源系统)**：
  * **不开发 LLM API 网关/代理层**：实际的请求路由与网关转发直接使用开源的 **LiteLLM Proxy** 或 **Semantic Router**，MERA 仅负责向其输出导出的 YAML 规则文件。

---

## 2. 系统架构设计 (System Architecture)

系统采用解耦架构，分为 **数据采集调度层**、**数据库持久化层** 和 **选型分析与 API 层**。

```text
+---------------------------------------------------------------------------------+
|                          前端 React (用户端 Dashboard + 管理面板 Admin)            |
|  用户端: [任务评估输入] [查看 Markdown 报告] [导出 Proxy YAML]                     |
|  管理端: [全部模型数据] [全部评估数据] (菜单按 Casdoor 权限渲染)                   |
+---------------------------------------------------------------------------------+
        │ OIDC 登录 / Bearer Token                 │ REST API
        ▼                                         ▼
+------------------------------------+   +------------------------------------------------+
|   Casdoor 统一授权中心              |   |              FastAPI 后端应用层                  |
| - OIDC Provider (登录/Token/用户信息)|◄──| - OIDC 资源校验 & Casdoor 菜单权限中间件         |
| - 应用 / 组织 / 用户 / 角色          |   | - RLS 租户隔离中间件                            |
| - 菜单权限 / 角色绑定                |   | - 选型分析引擎 (API/订阅/自部署 GPU 三方比对)     |
+------------------------------------+   |   └─> 直接读取 PostgreSQL 最新模型快照            |
                                         +------------------------------------------------+
          │ Trigger Fetch Task                      ▲ Direct Query Snapshots
          ▼                                        │
+------------------------------------+    +---------------------------------------+
|  Celery 异步调度层 (Task Queue)     |    |        数据库持久化层 (PostgreSQL)      |
|  - 周期性抓取/触发式更新            |───>| - model_snapshots (模型基准/按量定价快照) |
|  - OpenRouter / LMSYS 抓取 Task    |    | - user_evaluations (用户评估历史)     |
+------------------------------------+    | - fetch_tasks (按需获取任务)          |
                                          | - infrastructure_costs (自部署成本)    |
                                          | - subscription_plans (订阅套餐计划)    |
                                          |   主键统一 UUID v7，扩展字段存 data JSONB |
                  │                       +---------------------------------------+
                  ▼                                          ▲
          [ Redis Broker ]                                   │ RLS Strict Isolation
```

---

## 3. 解耦设计：数据获取与选型分析 (Data Fetching vs. Selection Engine)

### 3.1 架构分离原则
1. **数据获取 (Data Fetching)**：耗时、依赖外部网络，通过 Celery + Redis 进行异步后台调度，抓取结果批量落库存储 snapshot。
2. **选型分析 (Selection & Analysis)**：要求毫秒级响应，分析引擎**不直接发起外部 HTTP 请求**，而是基于请求时间戳和领域标签，直接从 PostgreSQL 数据库查询已落库的模型元数据进行推演。

### 3.2 Celery 异步调度与抓取流 (Task Workflow)

```text
[ Daily Cron / Manual Trigger ] 
          │
          ▼
[ Celery Worker: fetch_model_metrics_task ]
          │
          ├──> 1. 按策略降级采集: 官方 API → 逆向接口 → Playwright/开源 RPA
          ├──> 2. Parse Quality Score, Latency, Input/Output Token Price（命中验证码按 3.6 处理）
          └──> 3. Batch UPSERT into `model_snapshots`（扩展属性写入 data JSONB）
```

### 3.3 分析触发与按需数据获取流程 (On-Demand Fetch & Notify)

用户发起分析时，分析引擎先查库；若该领域尚无快照数据，则**不同步阻塞等待**，而是创建一个获取任务（`fetch_tasks`）异步拉取，完成后再通知用户。流程如下：

```text
[ 用户发起分析 (权重/用量参数 + auto_start 选项) ]
          │
          ▼
 查询 model_snapshots 是否存在模型数据
          │
   ┌──────┴────────────────────┐
   │ 有数据                     │ 无数据
   ▼                           ▼
 直接执行分析            创建 fetch_task (status=pending, attempt_count=0)
   │                     关联本次 evaluation(status=awaiting_data)
   │                           │
   │                           ▼
   │                  Celery Worker 抓取并落库（hit_count = 实际命中模型/资产条数）
   │                     ├─ hit_count ≥ 最小阈值 → status=succeeded（停止重试）
   │                     ├─ 失败 / 命中 0 条 且 attempt_count < MAX_FETCH_ATTEMPTS
   │                     │      → 指数退避自动重试，attempt_count+1
   │                     ├─ 达到最大次数但 hit_count ≥ 1 → status=partial_succeeded
   │                     │      （降级接受已有数据，通知“数据不完整”，auto_start 照常接续分析）
   │                     └─ 达到最大次数且 hit_count = 0 → status=failed_exhausted（停止，不再抓取）
   │                           │
   ▼                           ▼
                      完成后发送异步通知 (站内/WebSocket + 邮件)
                           │
              ┌────────────┴──────────────┐
              │ auto_start=true           │ auto_start=false
              ▼                           ▼
      自动开始分析并生成报告       通知用户“数据就绪”，由用户再次确认后开启分析
      (evaluation→completed)      (evaluation 保持 awaiting_confirmation → 用户确认→completed)
```

**关键规则：**

1. **两种开始方式（创建任务时由用户选择 `auto_start`）**
   * `auto_start = true`：数据获取成功后，系统**自动接续执行分析**并生成报告，用户无需再次操作。
   * `auto_start = false`：数据就绪后仅**通知用户**，评估停留在“待确认”，由用户再次点击确认后才开始分析（便于用户在等待期间补充/修正输入参数）。
2. **完成异步通知**：抓取任务结束（成功或失败）后，通过 WebSocket/站内消息实时推送，并发邮件通知；通知内容包含任务状态、命中模型数量及（失败时的）原因。
3. **最大获取次数限制与“部分成功”（防止无限获取、避免有效数据被丢弃）**
   * 系统配置 `MAX_FETCH_ATTEMPTS`（默认 3 次）与 `MIN_FETCH_HITS`（默认 1 条）：同一获取任务失败或抓取后命中条数（模型数/资产数，记为 `hit_count`）低于阈值时，按指数退避自动重试，`attempt_count` 每次 +1。
   * **`hit_count ≥ MIN_FETCH_HITS` 即视为成功**，任务结束不再重试：完整落库置 `succeeded`；若中途存在翻页中断、部分策略失败等导致数据可能不完整（即便未到最大次数），置 `partial_succeeded` 并在通知中标注缺失范围。
   * **达到 `MAX_FETCH_ATTEMPTS` 时按命中数终态分流（核心规则）**：只要本次已获取 **≥1 条模型或资产**（`hit_count ≥ 1`），即使过程中伴随错误/分页截断，也**不再判失败**，而是置 `partial_succeeded`（降级接受已有数据，通知“数据可能不完整”，`auto_start=true` 时照常接续分析）；**仅当 `hit_count = 0`（一条有效数据都没有）时才置 `failed_exhausted`** 并彻底停止，通知用户稍后重试或联系管理员。
   * `task_type=infrastructure_cost` 时，“命中条数”指 UPSERT 的资产/价格条目数（`infrastructure_costs` 行数），规则与模型类任务完全一致。
4. **去重与幂等**：同一 domain 已有进行中的 `fetch_task` 时，新的分析请求复用该任务，不重复创建，避免并发重复抓取。

### 3.4 自部署成本数据获取

自部署 GPU 的性价比测算依赖硬件/机房/能源等成本参数，这些数据同样通过 Celery 任务周期性采集或由管理员维护，落入 `infrastructure_costs` 表（见 4.1）。分析时根据该表计算自部署方案的真实总拥有成本 (TCO)，而非使用硬编码常量。

### 3.5 多策略数据采集与降级机制 (Fetch Strategy & Fallback)

> 各策略的具体技术实现（抓包逆向、Playwright、Robot Framework + RPA Framework、验证码工程化）见 [mera_data_fetch_implementation_guide.md](./mera_data_fetch_implementation_guide.md)。

外部数据源（榜单、云厂商定价页等）开放程度不一。采集任务针对每个数据源按以下优先级**逐级降级**，具体采用的方式记录在 `fetch_tasks.data->>'strategy'` 中，便于追溯与排障：

```text
                 [ 针对某数据源开始采集 ]
                            │
                            ▼
              (1) 官方 API / 公开数据接口
                   有开放 API 或可下载数据集？
              ┌────────是────────┐
              │                 否
              ▼                  ▼
        直接调用 API    (2) 逆向分析其加密/签名参数
        (最稳定、首选)     抓包分析请求，还原签名/token/加密体
                            │
                   ┌────────能还原────────┐
                   │                     不能/风控强
                   ▼                      ▼
            按还原算法直接请求      (3) Playwright 浏览器自动化
            (注意协议合规与限频)        或开源 RPA (如 TagUI/Robocorp)
                                        渲染 JS、模拟真实用户操作
                                              │
                                              ▼
                                   (4) 命中验证码时的处理 (见 3.6)
                                              │
                          全部策略失败 → 计入 attempt_count，按 3.3 重试/置 failed_exhausted
```

**各策略说明与边界：**

1. **策略 1：官方 API / 公开数据集（首选）**
   * OpenRouter、部分云厂商提供官方 API 或可下载的价格 JSON/CSV，直接 HTTP 调用，稳定性与合规性最好，是默认方式。
2. **策略 2：逆向接口加密 / 签名（谨慎使用）**
   * 目标站点无公开 API 但前端通过 XHR/fetch 返回结构化数据时，可通过抓包与前端 JS 分析，还原其签名、token、请求体加密算法（如常见的参数签名、AES/RSA 加密体），直接请求接口，比浏览器自动化更快、更省资源。
   * **合规前提**：仅采集公开可访问的事实性数据（价格、榜单分数），遵守目标站点 `robots.txt`、服务条款与当地法律法规；不得绕过付费墙、不得抓取个人隐私数据。逆向结果可能随站点更新失效，需结合 `attempt_count` 与告警及时维护。
3. **策略 3：Playwright / 开源 RPA 自动化（兜底）**
   * 当接口强依赖运行时 JS、签名难以还原，或风控较强时，使用 **Playwright**（无头/有头浏览器）驱动真实页面渲染、翻页、点击导出；复杂桌面/表单流程可辅以开源 RPA 工具。
   * 通过真实 UA、合理操作间隔、复用登录态/Cookie、降低并发等方式**模拟正常用户行为**，减少被判定为机器的概率。
   * 对 Canvas/WebGL 等深度指纹风控站点，可改用**指纹浏览器**（商用 AdsPower/BitBrowser 经 CDP 接管；容器化首选开源 Camoufox）生成隔离 profile 并绑定代理（实现细节见采集指南 4.1）。
4. **策略选择持久化**：`fetch_tasks` 记录本次实际使用的 `fetch_strategy`、是否命中验证码及处理结果，便于统计各数据源稳定性并决定是否需要人工介入。

### 3.6 验证码 (CAPTCHA) 处理策略

自动化采集可能遭遇滑块、点选文字、旋转图片、reCAPTCHA/hCaptcha 等人机验证。处理原则是**优先降低触发概率，触发后分级处理，不强行绕过**：

| 环节 | 措施 |
|---|---|
| **预防（优先）** | 使用 Playwright 模拟真人鼠标轨迹/停顿、保持指纹与 Cookie 一致、控制频率与并发、使用住宅/干净 IP、错峰采集，从源头减少验证码出现 |
| **滑块验证** | 模拟带加减速与抖动的人类拖拽轨迹（而非匀速直线），必要时结合缺口图像识别计算位移；仅用于公开数据的正常访问 |
| **点选/旋转类** | 接入打码平台（第三方验证码识别服务）或目标检测模型识别目标坐标后由 Playwright 点击；相关凭据通过环境变量注入，不落库 |
| **强验证 (reCAPTCHA/hCaptcha)** | 不做技术绕过；触发后**挂起任务并转人工**——通过 `fetch_tasks.status=captcha_pending` 通知管理员，在有头浏览器中人工完成验证后，复用会话继续采集 |
| **最终兜底** | 验证码持续无法通过则结束本次尝试，`attempt_count+1`，按 3.3 退避重试；达上限置 `failed_exhausted` 并告警，**避免高频尝试导致 IP/账号被封** |

> 所有验证码处理均以“访问公开数据、遵守目标站点规则”为前提；对于明确禁止自动化访问的站点，应改用官方授权 API、采购其数据服务或由管理员手动导入，而非强行破解。

---

## 4. 核心数据表结构设计 (Database Schema & RLS)

### 4.1 数据表定义 (PostgreSQL Schema)

```sql
-- 1. 模型基准与定价快照表 (全局数据，由 Celery Worker 写入/更新)
-- 一个模型一行：不同榜单/领域的数据聚合在同一行，域信息随来源记录落到 data.sources[key].domain
CREATE TABLE model_snapshots (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),  -- UUID v7，时间有序
    model_id VARCHAR(100) NOT NULL,        -- 如 'anthropic/claude-3-5-sonnet'
    provider VARCHAR(50) NOT NULL,          -- 如 'anthropic'
    benchmark_score NUMERIC(5,2),          -- 主榜分（按来源优先级聚合），可空
    score_source VARCHAR(100),             -- 主榜分来源：来源 key 或 llm:<scorer>
    scores JSONB NOT NULL DEFAULT '{}'::jsonb, -- 各能力维度分（intelligence/coding/agentic/long_context/image/video）
    data JSONB NOT NULL DEFAULT '{}'::jsonb, -- 采集原始数据：data.sources[<source_key>] = {raw_model_id, domain, record, benchmark_score, scores}
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
    -- 注意：订阅套餐（ChatGPT Plus / Claude Pro 等包月计划）不在此表，见 subscription_plans
);

-- Celery UPSERT 的业务幂等键：同一模型只保留一行，多来源在 data.sources 内合并
CREATE UNIQUE INDEX uq_model_snapshot ON model_snapshots (model_id);
CREATE INDEX idx_model_snapshot_score ON model_snapshots (benchmark_score DESC);
CREATE INDEX idx_model_snapshot_provider ON model_snapshots (provider);
CREATE INDEX idx_model_snapshot_data ON model_snapshots USING GIN (data);

-- 2. 用户选型评估历史表 (用户隔离数据，开启 RLS)
CREATE TABLE user_evaluations (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),  -- UUID v7，时间有序
    user_id VARCHAR(100) NOT NULL,          -- 绑定 Casdoor OIDC User ID
    domain VARCHAR(50) NOT NULL,            -- 核心过滤字段
    status VARCHAR(30) NOT NULL DEFAULT 'completed', -- awaiting_data/awaiting_confirmation/completed/failed
    fetch_task_id UUID,                     -- 关联触发的按需获取任务 (无数据时)
    snapshot_used_ids UUID[] NOT NULL DEFAULT '{}', -- 本次推演参考的快照 ID 集合 (追溯)
    data JSONB NOT NULL DEFAULT '{}'::jsonb, -- 其余字段: 任务描述/token 量级/报告 MD/
                                             -- Proxy YAML/三方成本推演结果/输入参数/auto_start 等
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_user_eval_user ON user_evaluations (user_id, created_at DESC);
CREATE INDEX idx_user_eval_data ON user_evaluations USING GIN (data);

-- 开启行级安全隔离 (RLS)
ALTER TABLE user_evaluations ENABLE ROW LEVEL SECURITY;

CREATE POLICY user_eval_isolation_policy ON user_evaluations
    FOR ALL
    TO authenticated_users
    USING (user_id = current_setting('app.current_user_id'));

-- 3. 按需数据获取任务表 (记录触发式抓取的生命周期，全局，用户可查看自己的任务)
CREATE TABLE fetch_tasks (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    task_type VARCHAR(30) NOT NULL,         -- model_metrics / infrastructure_cost
    source_key VARCHAR(80) NOT NULL,        -- 站点目录标识，对应 app/fetchers/sites/<source_key>/
    domain VARCHAR(50),                     -- 目标领域 (model_metrics 时使用)
    triggered_by VARCHAR(100) NOT NULL,     -- Casdoor User ID；cron 触发记为 system
    status VARCHAR(30) NOT NULL DEFAULT 'pending', -- pending/running/succeeded/partial_succeeded/failed/failed_exhausted/captcha_pending
    attempt_count INT NOT NULL DEFAULT 0,   -- 已尝试次数，达到 MAX_FETCH_ATTEMPTS 后按 hit_count 决定终态
    hit_count INT NOT NULL DEFAULT 0,       -- 本次实际 UPSERT 的模型/资产条数；终态判定核心字段（见 3.3 规则 3）
    auto_start BOOLEAN NOT NULL DEFAULT false, -- 获取成功（含 partial_succeeded）后是否自动开始分析
    fetch_strategy VARCHAR(50),             -- 命中的站点方案: <source_key>/<api|reverse_api|playwright_rpa>
    error_message TEXT,
    data JSONB NOT NULL DEFAULT '{}'::jsonb, -- 请求参数/各次尝试详情/缺失范围/验证码处理记录等
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 进行中任务去重：同类型 + 同站点(+领域)只允许一个未结束任务 (triggered_by=system 的 cron 不受此限)
CREATE UNIQUE INDEX uq_fetch_in_progress
    ON fetch_tasks (task_type, source_key, COALESCE(domain, ''))
    WHERE status IN ('pending', 'running');
CREATE INDEX idx_fetch_task_user ON fetch_tasks (triggered_by, created_at DESC);
CREATE INDEX idx_fetch_task_data ON fetch_tasks USING GIN (data);

-- 终态与 hit_count 的一致性（见 3.3 规则 3）：
--   succeeded         -> hit_count >= MIN_FETCH_HITS（数据完整）
--   partial_succeeded -> hit_count >= 1（达到最大尝试次数但有部分数据，或中途翻页截断）
--   failed_exhausted  -> hit_count = 0 且 attempt_count >= MAX_FETCH_ATTEMPTS（一条有效数据都没有）
-- 状态迁移在应用层状态机校验（非法迁移抛 InvalidTransition），这里用 CHECK 做数据兜底：
ALTER TABLE fetch_tasks
    ADD CONSTRAINT ck_fetch_terminal_hit_count CHECK (
        status <> 'failed_exhausted' OR hit_count = 0
    );

-- fetch_tasks 建表后，再补 user_evaluations 对它的外键
ALTER TABLE user_evaluations
    ADD CONSTRAINT fk_eval_fetch_task FOREIGN KEY (fetch_task_id) REFERENCES fetch_tasks(id);

-- 4. 自部署基础设施成本表 (硬件采购/电费/机房租赁/GPU 服务器租赁，供 TCO 测算)
CREATE TABLE infrastructure_costs (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    cost_type VARCHAR(30) NOT NULL,         -- gpu_rental / gpu_purchase / cpu / electricity / colocation / bandwidth
    name VARCHAR(150) NOT NULL,             -- 如 'H100 80G 月租' / '工业电价(每 kWh)' / '机房机柜月租'
    region VARCHAR(50) NOT NULL DEFAULT 'default', -- 区域，不同地区价格不同
    unit VARCHAR(30) NOT NULL,              -- 计量单位: month / kWh / hour / item
    unit_price NUMERIC(12,4) NOT NULL,      -- 单价 (USD)
    source VARCHAR(50),                     -- 数据来源: 云厂商/人工录入/采集任务
    is_active BOOLEAN NOT NULL DEFAULT true,
    data JSONB NOT NULL DEFAULT '{}'::jsonb, -- 规格/功耗/折旧年限/利用率/备注等扩展属性
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_infra_cost_lookup
    ON infrastructure_costs (cost_type, region, is_active);
CREATE INDEX idx_infra_cost_data ON infrastructure_costs USING GIN (data);

-- 5. 模型订阅套餐计划表 (固定月费计划: ChatGPT Plus/Pro、Claude Pro/Max、Gemini AI Plus 等)
-- 供分析引擎做“按量 API vs 订阅包月 vs 自部署”Break-even 盈亏平衡分析，不与 model_snapshots 混放
CREATE TABLE subscription_plans (
    id UUID PRIMARY KEY DEFAULT uuid_generate_v7(),
    provider VARCHAR(50) NOT NULL,           -- 厂商: openai / anthropic / google ...
    plan_key VARCHAR(80) NOT NULL,           -- 套餐标识: plus / pro / max / team ...
    plan_name VARCHAR(150) NOT NULL,         -- 展示名: 'ChatGPT Plus' / 'Claude Pro'
    monthly_price NUMERIC(12,2) NOT NULL,    -- 固定月费 (USD)
    currency VARCHAR(8) NOT NULL DEFAULT 'USD',
    billing_cycle VARCHAR(20) NOT NULL DEFAULT 'monthly', -- monthly / yearly（年付折算月费写入 monthly_price）
    is_active BOOLEAN NOT NULL DEFAULT true,
    source VARCHAR(50) NOT NULL DEFAULT 'manual', -- manual(管理员录入) / fetch(采集任务)
    data JSONB NOT NULL DEFAULT '{}'::jsonb, -- 用量上限(消息数/token 配额/速率)、覆盖模型列表、年付原价、官网 URL、生效日期等
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- 同一厂商同一套餐只保留一条当前记录（UPSERT 幂等键）
CREATE UNIQUE INDEX uq_subscription_plan
    ON subscription_plans (provider, plan_key, billing_cycle);
CREATE INDEX idx_subscription_active ON subscription_plans (is_active, provider);
CREATE INDEX idx_subscription_data ON subscription_plans USING GIN (data);
```

> **为什么订阅计划不放在 `model_snapshots`**：
> 1. **粒度不同**：`model_snapshots` 的幂等键是 `model_id`，一行 = 一个具体模型（多榜单来源合并，各类能力维度分与**按量 token 单价**都在这一行）；订阅套餐是**厂商/账号级固定月费**，一个套餐覆盖多个模型（如 ChatGPT Plus 同时含 GPT-4o/4.1/o 系列），还带消息条数/速率上限，强行塞入会破坏 `model_id` 唯一键语义。
> 2. **计费模型不同**：按量价格是“每 1M token 单价”，参与 `tokens × 单价` 线性计算；订阅是固定月费，只在 Break-even 分析中作为常量档位比较，且依赖“用量上限”判断是否够用。
> 3. **变更频率与来源不同**：订阅档位少、变动慢，以**管理员录入为主**（`source='manual'`，管理面板可维护），可选由采集任务补充；榜单/按量价格变化快、由 Celery 高频抓取。
>
> 分析引擎在第 4.4 节三方案比对时，`订阅包月` 一档从本表按 `provider` 取该用户候选模型对应厂商的**最低可用活跃套餐**（而非硬编码 `20.0`）。

### 4.2 主键与字段设计约定 (UUID v7 & JSONB Convention)

1. **主键统一使用 UUID v7**
   * UUID v7 以 Unix 毫秒时间戳为前缀，**单调趋势有序**，在 B-tree 索引上顺序写入，避免 UUID v4 (`gen_random_uuid()`) 随机插入导致的页分裂与缓存命中率下降；同时保留 UUID 全局唯一、应用端可生成、不可枚举、便于分布式与多环境数据迁移的优点。
   * 生成方式：PostgreSQL 18+ 可直接使用内置 `uuid_generate_v7()`；低版本由**应用层生成**（如 Python `uuid_utils` / `uuid6` 库的 `uuid7()`），不依赖数据库版本，Celery 与 FastAPI 两侧使用同一工具函数。
2. **“必要字段建列，其余进 `data` JSONB”**
   * 只有参与**关系约束、高频过滤/排序、RLS 判定**的字段才保留为物理列（如 `model_id`、`provider`、`domain`、`benchmark_score`、`user_id`、`snapshot_used_ids`）。
   * 其余易变、来源异构、按需扩展的属性全部放入 `data` JSONB（各榜单原始指标、价格、延迟、上下文长度、报告正文、Proxy YAML、成本推演结果等）。新增指标时**无需 ALTER TABLE 变更表结构**，直接写入 JSON 键即可。
   * JSONB 支持 GIN 索引，可对内部键做高效查询（如 `data->>'latency_ms'`、`@>` 包含查询）。

---

## 5. 统一认证授权与管理面板 (Casdoor OIDC, RBAC & Admin Panel)

### 5.1 Casdoor 统一授权中心
系统**不自建身份体系**，登录认证与菜单权限统一由 **Casdoor** 提供：

1. **OIDC 认证登录**：Casdoor 作为 OIDC Provider，前端通过 Authorization Code 流程登录，获取 `id_token` / `access_token`；Google、Facebook、SSO 等身份源在 Casdoor 侧以 Connector 接入，MERA 只对接 OIDC 一种协议。
2. **用户与应用模型**：复用 Casdoor 的 Organization / Application / User / Group 模型。MERA 在 Casdoor 注册为一个 Application，用户的唯一标识采用 OIDC `sub`（写入 `user_evaluations.user_id`）。
3. **菜单权限授权 (RBAC)**：在 Casdoor 中建立角色（如 `user`、`admin`）与权限项（Permission），以“资源 = 菜单/接口标识”的方式授权；前端登录后拉取用户权限集合，**按权限动态渲染菜单与路由**（无权限的管理菜单不显示、路由不可达）。

### 5.2 后端鉴权中间件
* FastAPI 中间件校验 Bearer Token（OIDC JWT 签名/有效期/Issuer/Audience），解析出 `user_id`，并通过 `SET app.current_user_id` 交由 PostgreSQL RLS 强制数据隔离。
* 菜单/操作权限采用**前后端双重校验**：前端控制菜单与按钮可见性，后端对每个管理接口再次校验 Casdoor 下发的权限项，防止绕过前端直接调用。

### 5.3 管理面板 (Admin Panel)
面向具备 `admin` 角色的用户，菜单入口由 Casdoor 权限控制，独立于普通用户 Dashboard：

| 模块 | 功能 |
|---|---|
| 模型数据管理 | 查看/分页/检索全部 `model_snapshots`，按 provider / 模型名过滤，查看单条快照的完整 `data` JSON，手动触发抓取任务 |
| 评估数据管理 | 查看全部用户的 `user_evaluations`，按用户 / 领域 / 状态 / 时间检索，查看报告正文、成本推演结果与引用快照（**管理接口绕过 RLS 的用户隔离**，但受 `admin` 权限严格限制） |
| 获取任务管理 | 查看全部 `fetch_tasks` 的状态（含 `partial_succeeded`）、`fetch_strategy`、`attempt_count`、`hit_count`、错误信息与进行中任务；对 `captcha_pending` 任务支持在有头浏览器中人工过码后续跑，对 `failed_exhausted` 任务支持手动重新触发 |
| 基础设施成本 | 查看/维护 `infrastructure_costs`（GPU 租赁/采购、CPU、电费、机柜、带宽），支持人工录入与启停，作为自部署 TCO 测算依据 |
| 订阅套餐管理 | 查看/维护 `subscription_plans`（ChatGPT Plus/Pro、Claude Pro/Max 等厂商固定月费套餐、用量上限、覆盖模型、年付折算价），支持人工录入/启停，作为订阅 vs 按量 Break-even 比对依据 |
| 任务与系统 | 查看 Celery 定时任务状态、最近抓取结果与失败日志 |

> 业务数据（模型/评估）默认只读；`infrastructure_costs` 与 `subscription_plans` 允许管理员录入维护。所有访问行为经 Casdoor 鉴权并留审计日志。

---

## 6. 关键模块简要实现 (Core Code Highlights)

### 6.1 Celery 异步数据抓取 (`tasks.py`)

```python
from celery import Celery
import requests
# 引入 PostgreSQL 数据库连接

celery_app = Celery("mera_tasks", broker="redis://localhost:6379/0")

MAX_FETCH_ATTEMPTS = 3

# 采集策略按优先级降级：官方 API -> 逆向接口 -> Playwright/RPA
FETCH_STRATEGIES = ("api", "reverse_api", "playwright_rpa")

def fetch_via_api(source):
    """策略1：官方/公开 API（首选）"""
    resp = requests.get(source["api_url"], timeout=30)
    resp.raise_for_status()
    return resp.json().get("data", [])

def fetch_via_reverse_api(source):
    """策略2：按抓包还原的签名/加密算法直接请求接口（仅公开数据，遵守 robots/ToS）"""
    # headers/签名由还原算法生成；站点变更会导致失败，交由上层降级
    raise NotImplementedError

def fetch_via_playwright(source):
    """策略3：Playwright 渲染页面、模拟真人操作；遇验证码交 handle_captcha 分级处理"""
    # with sync_playwright() as p: browser -> page.goto -> 滚动/翻页/解析
    raise NotImplementedError

@celery_app.task(
    name="fetch_and_store_model_metrics",
    autoretry_for=(Exception,), retry_backoff=True, max_retries=MAX_FETCH_ATTEMPTS - 1,
)
def fetch_and_store_model_metrics(fetch_task_id=None):
    """
    异步 Celery 任务：按策略降级抓取榜单数据并落库，
    尝试次数/策略/验证码处理记录到 fetch_tasks。
    终态规则（见 3.3 规则 3）：hit_count>=阈值即 succeeded；
    达到最大次数但 hit_count>=1 置 partial_succeeded；hit_count=0 才 failed_exhausted。
    """
    task = load_fetch_task(fetch_task_id)
    models_data, used_strategy = None, None
    truncated = False  # 仅指“取到的数据被截断”（如翻页中途异常）；备选策略失败不算截断

    # 逐级降级尝试
    for strategy in FETCH_STRATEGIES:
        try:
            # fetcher 返回 (records, truncated)：truncated=True 表示翻页中断、数据可能不全
            models_data, truncated = {
                "api": fetch_via_api,
                "reverse_api": fetch_via_reverse_api,
                "playwright_rpa": fetch_via_playwright,
            }[strategy](SOURCE)
            used_strategy = strategy
            break
        except CaptchaRequired:
            # 滑块/点选自动处理；强验证挂起转人工 (status=captcha_pending)
            handle_captcha(task) or task.mark_captcha_pending()
        except Exception:
            continue  # 当前策略失败，降级到下一策略

    # UPSERT 落库：核心字段建列，其余属性写入 data JSONB；返回实际写入条数
    hit_count = len(models_data) if models_data else 0
    if models_data:
        for item in models_data:
            pass  # INSERT ... ON CONFLICT(model_id, domain) DO UPDATE

    reached_max = task.attempt_count + 1 >= MAX_FETCH_ATTEMPTS

    # 终态分流：以 hit_count 为准，而非以“是否抛过异常”为准
    if hit_count >= MIN_FETCH_HITS and not truncated:
        task.mark_succeeded(strategy=used_strategy, hit_count=hit_count)
    elif hit_count >= 1 and (truncated or reached_max):
        # 有部分数据：达到最大尝试次数，或数据被截断 —— 降级接受，不丢弃有效数据
        task.mark_partial_succeeded(strategy=used_strategy, hit_count=hit_count)
    elif hit_count >= 1:
        task.mark_succeeded(strategy=used_strategy, hit_count=hit_count)
    else:
        task.bump_attempt()              # attempt_count+1
        if task.attempt_count >= MAX_FETCH_ATTEMPTS:
            task.mark_failed_exhausted() # hit_count=0 才彻底停止并通知
        raise
        return

    task.notify_and_maybe_auto_start()  # succeeded/partial_succeeded 均通知；auto_start=true 照常接续分析
    return f"upserted {hit_count} model metrics via {used_strategy} (status={task.status})."
```

### 6.2 选型推演与报告生成引擎 (`analyzer.py`)

```python
import uuid
import yaml

# 单卡可承载的月度 token 吞吐（按模型与并发实测，可存入 data/配置）
GPU_TOKENS_PER_MONTH = 3_000_000_000

def self_host_monthly_cost(db_session, gpu_count: int, region: str = "default") -> float:
    """
    基于 infrastructure_costs 表计算自部署 TCO：
      GPU 租赁/折旧 + 电费 + 机柜(colocation) + 带宽 + CPU 等，按 gpu_count 汇总
    替代原先硬编码的单卡价格，使自部署性价比测算随成本表实时更新
    """
    rows = db_session.query(InfrastructureCost).filter(
        InfrastructureCost.region == region,
        InfrastructureCost.is_active.is_(True),
    ).all()
    total = 0.0
    for r in rows:
        qty = gpu_count if r.data.get("per_gpu", True) else 1
        total += float(r.unit_price) * qty
    return total

def run_model_selection_analysis(db_session, user_id, domain, monthly_tokens, daily_chats):
    """
    从数据库读取已保存 Snapshot，在内存中完成 Pareto 选型，
    并进行 API / 订阅包月 / 自部署 GPU 三方成本推演
    """
    # 1. 直接查询数据库，获取最新模型元数据快照（价格等扩展字段从 data JSONB 读取）
    snapshots = db_session.query(ModelSnapshot).filter(ModelSnapshot.domain == domain).all()
    if not snapshots:
        raise ValueError(f"No benchmark data available for domain: {domain}")

    def price(s):  # 平均 token 单价 (USD / 1M tokens)，价格存放在 data JSONB
        return (float(s.data["input_price_per_1m"]) + float(s.data["output_price_per_1m"])) / 2

    # 2. 极致性能与高性价比模型
    perf_model = max(snapshots, key=lambda s: s.benchmark_score)
    value_model = max(snapshots, key=lambda s: s.benchmark_score / (price(s) + 0.01))

    # 3. 三种部署方式的月度成本推演
    # 3.1 商业 API：按量付费
    api_cost = monthly_tokens / 1_000_000 * price(perf_model)

    # 3.2 订阅包月：从 subscription_plans 表取候选性能模型所属厂商的最低可用套餐
    # （固定月费，有用量/速率上限；表为空时回退保守默认值，不再硬编码业务常量）
    provider = perf_model.provider
    row = db_session.execute(
        text("""SELECT plan_name, monthly_price
                  FROM subscription_plans
                 WHERE provider = :p AND is_active = true
                 ORDER BY monthly_price ASC LIMIT 1"""),
        {"p": provider},
    ).first()
    sub_plan_name, sub_cost = (row[0], float(row[1])) if row else ("默认订阅", 20.0)

    # 3.3 自部署 GPU：固定成本随规模摊薄
    gpu_count = max(1, -(-monthly_tokens // GPU_TOKENS_PER_MONTH))  # 向上取整
    self_host_cost = self_host_monthly_cost(db_session, gpu_count)  # 来自 infrastructure_costs 的 TCO
    self_host_feasible = monthly_tokens >= GPU_TOKENS_PER_MONTH     # 至少跑满 1 张卡才具性价比

    options = {"商业 API": api_cost, "订阅包月": sub_cost, "自部署 GPU": self_host_cost}
    best_name, best_cost = min(options.items(), key=lambda kv: kv[1])

    if best_name == "自部署 GPU" and self_host_feasible:
        deploy_advice = (
            f"调用量级已达 {monthly_tokens:,} tokens/月，可跑满 {gpu_count} 张 GPU，"
            f"自部署月成本约 ${self_host_cost:,.0f}，低于 API ${api_cost:,.0f}，建议自部署开源模型。"
        )
    elif self_host_feasible is False and api_cost >= sub_cost:
        deploy_advice = (
            f"量级不足以摊薄 GPU 固定成本（自部署需约 ${self_host_cost:,.0f}/月），"
            f"建议购买订阅包月（${sub_cost}/月），低于 API 预估 ${api_cost:,.0f}。"
        )
    else:
        deploy_advice = (
            f"量级较小，建议直接使用商业 API，预估每月 ${api_cost:,.2f}，"
            f"低于订阅（${sub_cost}）与自部署（${self_host_cost:,.0f}）。"
        )

    # 4. 拼接 Markdown 报告
    md_report = f"""# MERA 模型选型报告
## 部署方式成本比对（月度）
| 方案 | 预估月成本 | 说明 |
|---|---|---|
| 商业 API | ${api_cost:,.2f} | 按量付费，弹性免运维 |
| 订阅包月 | ${sub_cost:,.2f} | {sub_plan_name}，固定费用，有用量上限 |
| 自部署 GPU | ${self_host_cost:,.0f} | {gpu_count} 张 GPU，固定成本，规模越大单位成本越低 |

**结论**：{deploy_advice}

## 推荐模型组合
* **性能首选**: `{perf_model.model_id}` (Score: {perf_model.benchmark_score})
* **性价比首选**: `{value_model.model_id}` (Score: {value_model.benchmark_score})
"""

    # 5. 生成供 LiteLLM Proxy 使用的 YAML 配置
    proxy_yaml = yaml.dump({
        "model_list": [{
            "model_name": "auto-router",
            "litellm_params": {
                "model": value_model.model_id,
                "fallbacks": [perf_model.model_id]
            }
        }]
    }, allow_unicode=True)

    # 6. 持久化：必要字段建列，报告/YAML/成本结果等整体写入 data JSONB
    db_session.execute(
        text("""INSERT INTO user_evaluations
                (id, user_id, domain, snapshot_used_ids, data)
                VALUES (:id, :user_id, :domain, :sids, CAST(:data AS JSONB))"""),
        {
            "id": uuid.uuid7() if hasattr(uuid, "uuid7") else uuid7(),  # 应用层生成 UUID v7
            "user_id": user_id,
            "domain": domain,
            "sids": [s.id for s in snapshots],
            "data": {
                "task_input": {"monthly_tokens": monthly_tokens, "daily_chats": daily_chats},
                "markdown_report": md_report,
                "litellm_proxy_yaml": proxy_yaml,
                "cost_analysis": {
                    "api": api_cost,
                    "subscription": sub_cost,
                    "subscription_plan": sub_plan_name,
                    "self_hosted": self_host_cost, "gpu_count": gpu_count,
                    "recommended": best_name,
                },
            },
        },
    )
    return {"markdown_report": md_report, "litellm_yaml": proxy_yaml}
```

---

## 7. 本地部署 (Docker Compose 一体化环境)

本地开发/演示通过仓库根目录的 `docker-compose.yaml` 一键拉起完整系统：**1 个 backend-app、1 个 frontend-app、2 个负责数据采集的 worker 实例**，以及 PostgreSQL、Redis、Casdoor 等基础设施。容器间通过桥接网络 `mera-net` 互通，配置通过 `.env` 注入，数据持久化到命名卷。

### 7.1 服务拓扑与职责

| 服务（容器名） | 实例数 | 镜像来源 | 职责 |
|---|---|---|---|
| `backend-app` (mera-backend) | 1 | 本地构建 `backend/` | FastAPI：REST API、OIDC 校验、RLS 中间件、选型分析引擎；启动前自动执行 Alembic 迁移 |
| `frontend-app` (mera-frontend) | 1 | 本地构建 `frontend/` | React 构建产物由 Nginx 托管，`/api/`（含 WebSocket）反代到 backend-app |
| `worker-1` (mera-worker-1) | 1 | 复用 backend 镜像 | Celery Worker：消费 `default,fetch_api` 队列，承载官方 API / 逆向接口等轻量采集 |
| `worker-2` (mera-worker-2) | 1 | 复用 backend 镜像 | Celery Worker：消费 `default,fetch_browser` 队列，承载 Playwright 浏览器自动化（2 并发，`shm_size=1gb`） |
| `beat` (mera-beat) | 1 | 复用 backend 镜像 | Celery Beat：周期性采集调度，**仅单实例**防止重复触发 |
| `postgres` (mera-postgres) | 1 | `postgres:18-alpine` | 业务数据库：model_snapshots / user_evaluations / fetch_tasks / infrastructure_costs / subscription_plans |
| `redis` (mera-redis) | 1 | `redis:7-alpine` | Celery Broker（db0）+ Result Backend（db1），开启 AOF 持久化 |
| `casdoor` (mera-casdoor) | 1 | `casbin/casdoor` | OIDC Provider + 菜单权限（RBAC） |
| `casdoor-postgres` | 1 | `postgres:16-alpine` | Casdoor 专用数据库，与业务库隔离 |
| `flower`（可选） | 0/1 | 复用 backend 镜像 | Celery 监控面板，`--profile monitor` 时启动，端口 5555 |

> **队列分工**：`worker-1` 与 `worker-2` 同时消费 `default` 队列互为冗余；任务路由把 Playwright 类重任务投递到 `fetch_browser`（仅 worker-2 消费），把 API/逆向类轻任务投递到 `fetch_api`（仅 worker-1 消费），避免浏览器渲染占满并发拖慢普通任务。
>
> **RPA 不在本地 Compose 内**：Robot Framework + RPA Framework 运行在三类独立专用节点，以外部执行器 + Webhook 回调方式接入，详见 [mera_data_fetch_implementation_guide.md](./mera_data_fetch_implementation_guide.md) 第 5 节：
> * **Windows 桌面 RPA 节点**：首选 **Windows 10/11 专业版**云桌面（兼容性/成本优于 Windows Server；仅多会话并行或合规强制时用 Server + RDS），保持交互桌面会话存活（自动登录 / 禁锁屏；Server 侧 `tscon` 转接 console / NSSM Runner），用 `RPA.Windows` 操控桌面软件；
> * **Ubuntu RPA 节点**：无 Windows GUI 依赖的 robot 任务（Web/Excel/网络 ADB）Docker 镜像化运行；
> * **云手机集群**：云 Android 实例经网络 ADB + 多端口 Appium 接入，Runner 按“一设备一任务”调度并在任务间重置环境（iOS 需 macOS + XCUITest，资源不足时降级人工导入）。
>
> **指纹浏览器**：对深度指纹风控站点，浏览器策略使用指纹浏览器（商用 AdsPower/BitBrowser 部署在宿主机或云端带桌面节点，Playwright 经 Local API + CDP 接管；容器化场景首选开源 **Camoufox** 随 worker-2 容器一体化；DonutBrowser 为候选观察），详见采集指南 4.1 节。

```text
  http://localhost:3000                 Nginx (frontend-app)
        │ 静态 SPA                        │ /api/ 反代 + WebSocket
        ▼                                 ▼
  浏览器 ──OIDC──> http://localhost:8000 (casdoor)      http://localhost:8000 容器内 (backend-app)
                        │                                    │
                        └── casdoor-postgres:5432            ├──> postgres:5432 (业务库)
                                                             └──> redis:6379 (broker/result)
                                                                   │ 投递任务
                              ┌────────────────────────────────────┼────────────────────────────┐
                              ▼                                                     ▼
                    worker-1 (-Q default,fetch_api)                      worker-2 (-Q default,fetch_browser)
                    beat ── 周期定时任务投递（单实例）                     [Playwright/Chromium, shm 1gb]
```

### 7.2 端口、卷与环境变量

| 本地端口 | 服务 | 说明 |
|---|---|---|
| 3000 | frontend-app | 系统访问入口 |
| 8080 | backend-app | FastAPI（直连调试用，正常访问走前端 /api） |
| 8000 | casdoor | Casdoor 管理后台 / OIDC 端点 |
| 5432 | postgres | 业务 PostgreSQL（本地调试直连） |
| 6379 | redis | Redis（本地调试直连） |
| 5555 | flower | 可选，`--profile monitor` 启动 |

持久化命名卷：`pg_data`（业务库）、`casdoor_pg_data`（Casdoor 库）、`redis_data`（AOF）、`beat_data`（celery beat 调度文件）。

主要环境变量（`.env`，模板见 `.env.example`）：

| 变量 | 用途 |
|---|---|
| `POSTGRES_PASSWORD` | 业务库 mera 用户密码，backend/worker/beat 的 `DATABASE_URL` 自动引用 |
| `CASDOOR_CLIENT_ID` / `CASDOOR_CLIENT_SECRET` | Casdoor 中注册 mera 应用后回填，重启后端服务生效 |
| `SMTP_HOST/PORT/USER/PASSWORD/FROM` | 抓取完成异步通知的邮件通道 |
| `MAX_FETCH_ATTEMPTS` | 获取任务最大尝试次数（默认 3，见 3.3） |

### 7.3 启动步骤

```bash
# 0. 前置：Docker Engine + Docker Compose v2
# 1. 准备环境变量
cp .env.example .env        # Windows PowerShell: Copy-Item .env.example .env

# 2. 一键启动（首次会构建 backend / frontend 镜像；backend 镜像默认安装 Chromium）
docker compose up -d

# 3. 初始化 Casdoor：浏览器打开 http://localhost:8000
#    初始管理员 built-in/built-in，创建 Organization 与 Application(mera)、
#    建立 user/admin 角色与菜单权限项，将 Client ID/Secret 填入 .env
docker compose restart backend-app worker-1 worker-2 beat

# 4. 访问系统
#    前端:        http://localhost:3000
#    API 文档:    http://localhost:8080/docs
#    Flower(可选): docker compose --profile monitor up -d flower -> http://localhost:5555
```

**构建契约（应用代码需遵循的约定）：**

```text
.
├── docker-compose.yaml
├── .env / .env.example
├── deploy/casdoor/app.conf            # Casdoor 本地配置（连接 casdoor-postgres）
├── backend/
│   ├── Dockerfile                     # python:3.12-slim；构建参数 INSTALL_PLAYWRIGHT=true 时装 Chromium
│   ├── requirements.txt
│   ├── scripts/start-backend.sh       # 启动前 alembic upgrade head，再起 uvicorn
│   └── app/                           # main:app / worker.celery_app / fetchers/...
└── frontend/
    ├── Dockerfile                     # node:20 构建 (npm run build -> dist)，nginx:alpine 托管
    └── nginx.conf                     # SPA 回退 + /api/ 与 WebSocket 反代 backend-app:8000
```

Celery 应用实例路径约定为 `app.worker.celery_app:celery_app`；Worker 启动命令为
`celery -A app.worker.celery_app worker -Q <队列> -n <名称> --concurrency=<N>`。

### 7.4 日常运维操作

```bash
docker compose logs -f worker-1           # 查看采集日志
docker compose ps                          # 服务状态 / 健康检查
docker compose restart backend-app         # 改 .env 后重启
docker compose up -d --scale worker-1=2    # 横向扩容（队列消费者可多副本；beat 不可扩容）
docker compose down                         # 停止并移除容器（保留数据卷）
docker compose down -v                      # 连同数据卷一并清除（重置本地环境）
```

* 站点采集配置 `app/fetchers/sites/*/config.yaml` 以只读卷挂载进后端与 worker，本地调整无需重建镜像；
* 健康检查：postgres `pg_isready`、redis `ping`，backend/worker 通过 `depends_on: condition: service_healthy` 保证启动顺序；
* Beat 必须保持单实例（多副本会重复下发定时任务），扩容只针对 worker；
* 生产部署差异：密钥走密钥管理服务而非 `.env`、启用 TLS 与 Casdoor 对外域名、数据库/Redis 不暴露宿主机端口、Worker 按节点标签分散部署（浏览器节点单独配置）、RPA 走独立 Windows + Appium 节点。

---

## 8. 总结 (Summary)

1. **专注选型核心**：不开发 LLM API 代理层，网关交给 LiteLLM Proxy，MERA 专精于**智能选型计算与部署配置输出**。
2. **数据与分析解耦**：Celery 后台异步抓取基准/定价快照，分析请求**直接查库**，保证毫秒级响应。
3. **主键统一 UUID v7**：时间有序、顺序写入，兼顾索引性能与全局唯一/分布式/防枚举优势。
4. **Schema 弹性扩展**：核心字段建列、其余属性存入 `data` JSONB，新增指标无需频繁变更表结构。
5. **统一认证与管理面板**：认证 (OIDC) 与菜单权限统一由 **Casdoor** 授权，前后端双重校验；管理员可在管理面板查看全部模型与评估数据，普通用户数据由 RLS 严格隔离。
6. **三方案成本比对**：选型同时推演 **商业 API / 订阅包月 / 自部署 GPU** 的月度成本，在调用量级达到可跑满 GPU 的阈值时推荐自部署，并保留引用快照确保结论可追溯。
7. **按需获取与闭环通知**：分析时无数据则异步触发获取任务，完成后通知用户；可选“获取成功自动开始分析”或“等待用户确认”，并通过最大获取次数 (`MAX_FETCH_ATTEMPTS`) 防止无限抓取。
8. **多策略采集与验证码处理**：数据源按 **官方 API → 逆向接口 → Playwright/开源 RPA** 优先级降级采集，全程以合规访问公开数据为前提；对滑块/点选等验证码优先预防、其次自动识别，强验证转人工，避免高频触发封禁。
9. **自部署成本可配置**：GPU 租赁/采购、CPU、电费、机房租赁、带宽等成本统一存入 `infrastructure_costs`，自部署性价比基于真实 TCO 计算，而非硬编码常量。
10. **一键本地部署**：根目录 `docker-compose.yaml` 以容器方式拉起 1 个 backend-app、1 个 frontend-app、2 个采集 worker（轻量 API/逆向队列与 Playwright 浏览器队列分工）及 beat、PostgreSQL、Redis、Casdoor 全套环境，数据卷持久化、健康检查保证启动顺序，详见第 7 节。