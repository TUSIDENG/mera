# MERA Casdoor 权限菜单与用户导入指南

本文档列出 MERA 需要注入 Casdoor 的角色与菜单权限项清单，并给出用户与权限的导入方法（API 自动化、init_data.json、XLSX 批量导入），同时约定多组织多应用演进的命名规范与路线。

> 上下文：MERA 不自建身份体系，登录认证与菜单权限统一由 Casdoor 提供（见架构文档第 5 节）。菜单权限采用**前后端双重校验**：前端按权限渲染菜单/路由，后端管理接口再次校验。

## 1. 权限模型与标识约定

Casdoor 侧对象映射：

| Casdoor 对象 | MERA 中的含义 |
|---|---|
| Organization | `main`（默认组织，所有内部用户归属的主组织；token 的 `owner` claim；多应用演进中的组织规划见第 5 节） |
| Application | `mera`（OIDC Client，Client ID/Secret 填入 `.env`） |
| Role | `mera-user`（普通用户）、`mera-admin`（管理员） |
| Permission | 一条权限项 = 一组菜单资源标识授权给若干角色，Action 统一 `Read`，Effect 统一 `Allow` |

资源标识（Permission 的 `resources` 字段）统一约定：

- 普通菜单：`menu:mera:<页面>`，如 `menu:mera:leaderboard`
- 管理菜单：`menu:mera:admin:<模块>`，如 `menu:mera:admin:models`
- 前端路由与标识一一对应；后端管理接口复用同一标识做二次校验
- 命名空间从第一天启用：未来同一组织将承载多个应用（爬虫、ERP、WMS 等），标识必须带应用前缀，避免跨应用冲突（演进规划见第 5 节）

## 2. 权限菜单清单

### 2.1 普通用户菜单（role: mera-user）

| 资源标识 | 菜单名称 | 前端路由 | 说明 |
|---|---|---|---|
| `menu:mera:leaderboard` | 榜单浏览 | `/leaderboard` | 模型快照榜单，排序/筛选（M11） |
| `menu:mera:compare` | 模型对比分析 | `/compare` | 性能 vs 成本推演、Break-even 分析 |
| `menu:mera:cost` | 成本对比 | `/cost` | API/订阅/自部署三方 TCO 比对 |
| `menu:mera:tasks` | 采集任务管理 | `/tasks` | 查看本组织 fetch_tasks、手动触发采集 |

> 登录页 `/login` 无需授权。用户评估历史入口在“模型对比分析”页内，不单独占用菜单。

### 2.2 管理菜单（role: mera-admin）

| 资源标识 | 菜单名称 | 前端路由 | 说明 |
|---|---|---|---|
| `menu:mera:admin:models` | 模型数据管理 | `/admin/models` | 全部 model_snapshots 检索、data JSON 查看、手动触发抓取 |
| `menu:mera:admin:evaluations` | 评估数据管理 | `/admin/evaluations` | 全部 user_evaluations 检索（管理接口绕过 RLS 用户隔离） |
| `menu:mera:admin:tasks` | 获取任务管理 | `/admin/tasks` | 全部 fetch_tasks 状态、captcha_pending 人工过码、failed_exhausted 重触发 |
| `menu:mera:admin:costs` | 基础设施成本 | `/admin/costs` | infrastructure_costs 录入/启停（自部署 TCO 依据） |
| `menu:mera:admin:plans` | 订阅套餐管理 | `/admin/plans` | subscription_plans 录入/启停（Break-even 比对依据） |
| `menu:mera:admin:system` | 任务与系统 | `/admin/system` | Celery 定时任务状态、最近抓取结果与失败日志 |

### 2.3 角色-权限绑定矩阵

| 权限项名称（Permission name） | resources | 绑定角色 |
|---|---|---|
| `perm-mera-user-menus` | `menu:mera:leaderboard`, `menu:mera:compare`, `menu:mera:cost`, `menu:mera:tasks` | `mera-user`, `mera-admin` |
| `perm-mera-admin-models` | `menu:mera:admin:models` | `mera-admin` |
| `perm-mera-admin-evaluations` | `menu:mera:admin:evaluations` | `mera-admin` |
| `perm-mera-admin-tasks` | `menu:mera:admin:tasks` | `mera-admin` |
| `perm-mera-admin-costs` | `menu:mera:admin:costs` | `mera-admin` |
| `perm-mera-admin-plans` | `menu:mera:admin:plans` | `mera-admin` |
| `perm-mera-admin-system` | `menu:mera:admin:system` | `mera-admin` |

> `mera-admin` 同时绑定 `perm-mera-user-menus`，保证管理员可用普通用户功能。管理菜单拆成 6 条权限，便于将来按职能细分（如只给运营开采集任务管理）。

## 3. 初始化与导入

### 3.0 前置：Organization 与 Application

1. `docker compose up -d` 后打开 `http://localhost:8000`，以初始管理员 `built-in` / `built-in`（admin/123，以 `deploy/casdoor/app.conf` 为准）登录。
2. 创建 Organization `main`（默认主组织）；创建 Application `mera`，记录 **Client ID / Client Secret** 填入 `.env` 的 `CASDOOR_CLIENT_ID` / `CASDOOR_CLIENT_SECRET`。
3. Application 的 **Token fields** 中确保 token 携带 `sub`、`owner`、`roles`（M03 后端 `decode_token` 依赖这三个 claim 提取用户/组织/角色）。
4. `docker compose restart backend-app worker-1 worker-2 beat`。

### 3.1 方式一：Casdoor Admin API 导入（推荐，可重复执行）

Casdoor 管理 API 使用应用的 Client ID/Secret 做 HTTP Basic Auth（管理全量数据用 `built-in` 组织下 `app-built-in` 的凭证）。接口幂等策略：先 `add-*`，返回已存在时改调 `update-*`。

```bash
# 按目标环境导出（示例为本地；测试/生产替换为对应地址与凭证，见第 4 节）
export CASDOOR_ENDPOINT=http://localhost:8000
export CASDOOR_AUTH="app-built-in-client-id:app-built-in-client-secret"   # 替换为实际凭证
export CASDOOR_ORG=main

# 1) 角色
curl -u "$CASDOOR_AUTH" -X POST "$CASDOOR_ENDPOINT/api/add-role" -H 'Content-Type: application/json' -d "{
  \"owner\": \"$CASDOOR_ORG\", \"name\": \"mera-user\", \"displayName\": \"MERA 普通用户\", \"isEnabled\": true,
  \"users\": [], \"groups\": [], \"roles\": [], \"domains\": []
}"
curl -u "$CASDOOR_AUTH" -X POST "$CASDOOR_ENDPOINT/api/add-role" -H 'Content-Type: application/json' -d "{
  \"owner\": \"$CASDOOR_ORG\", \"name\": \"mera-admin\", \"displayName\": \"MERA 管理员\", \"isEnabled\": true,
  \"users\": [], \"groups\": [], \"roles\": [], \"domains\": []
}"

# 2) 权限项（普通菜单）
curl -u "$CASDOOR_AUTH" -X POST "$CASDOOR_ENDPOINT/api/add-permission" -H 'Content-Type: application/json' -d "{
  \"owner\": \"$CASDOOR_ORG\", \"name\": \"perm-mera-user-menus\", \"displayName\": \"MERA 普通用户菜单\",
  \"users\": [], \"groups\": [], \"roles\": [\"$CASDOOR_ORG/mera-user\", \"$CASDOOR_ORG/mera-admin\"], \"domains\": [],
  \"model\": \"\", \"adapter\": \"\", \"resourceType\": \"menu\",
  \"resources\": [\"menu:mera:leaderboard\", \"menu:mera:compare\", \"menu:mera:cost\", \"menu:mera:tasks\"],
  \"actions\": [\"Read\"], \"effect\": \"Allow\", \"isEnabled\": true, \"state\": \"approved\"
}"

# 3) 权限项（管理菜单，逐条替换 name/displayName/resources/roles=[main/mera-admin]）
curl -u "$CASDOOR_AUTH" -X POST "$CASDOOR_ENDPOINT/api/add-permission" -H 'Content-Type: application/json' -d "{
  \"owner\": \"$CASDOOR_ORG\", \"name\": \"perm-mera-admin-models\", \"displayName\": \"MERA 管理-模型数据\",
  \"users\": [], \"groups\": [], \"roles\": [\"$CASDOOR_ORG/mera-admin\"], \"domains\": [],
  \"model\": \"\", \"adapter\": \"\", \"resourceType\": \"menu\",
  \"resources\": [\"menu:mera:admin:models\"],
  \"actions\": [\"Read\"], \"effect\": \"Allow\", \"isEnabled\": true, \"state\": \"approved\"
}"
# 对其余 5 个管理菜单重复上一条，替换 name/displayName/resources：
#   perm-mera-admin-evaluations -> menu:mera:admin:evaluations
#   perm-mera-admin-tasks       -> menu:mera:admin:tasks
#   perm-mera-admin-costs       -> menu:mera:admin:costs
#   perm-mera-admin-plans       -> menu:mera:admin:plans
#   perm-mera-admin-system      -> menu:mera:admin:system

# 4) 创建用户并挂角色
curl -u "$CASDOOR_AUTH" -X POST "$CASDOOR_ENDPOINT/api/add-user" -H 'Content-Type: application/json' -d "{
  \"owner\": \"$CASDOOR_ORG\", \"name\": \"alice\", \"displayName\": \"Alice\",
  \"password\": \"ChangeMe123!\", \"email\": \"alice@example.com\"
}"
# 将用户绑定到角色（roles 数组为该用户已有的全部角色）
curl -u "$CASDOOR_AUTH" -X POST "$CASDOOR_ENDPOINT/api/update-user?id=$CASDOOR_ORG%2Falice" \
  -H 'Content-Type: application/json' \
  -d "$(curl -s -u "$CASDOOR_AUTH" "$CASDOOR_ENDPOINT/api/get-user?id=$CASDOOR_ORG%2Falice" | \
       python -c 'import json,sys; u=json.load(sys.stdin); u["roles"]=["main/mera-user"]; print(json.dumps(u))')"
```

成功响应均为 `{"status":"ok","msg":"","data":"Affected"}`。批量场景建议将第 2.3 节矩阵写成 JSON 后用 Python 循环调用，脚本放 `deploy/casdoor/`（不纳入本仓库的密钥写入脚本需走环境变量）。

### 3.2 方式二：init_data.json 首次启动导入

Casdoor 支持容器启动时在**空库**上加载 `/init_data.json`（`app.conf` 的 `initDataFile` 配置）：

1. 编写 `deploy/casdoor/init_data.json`，包含 `organizations`、`applications`、`roles`、`permissions`、`users` 五个数组，字段名与 Casdoor API 对象一致（同 3.1 请求体）。
2. compose 挂载：在 `casdoor` 服务 `volumes` 增加 `./deploy/casdoor/init_data.json:/init_data.json:ro`，并在 `deploy/casdoor/app.conf` 增加 `initDataFile = "/init_data.json"`。
3. `docker compose down -v && docker compose up -d`（**会清空 Casdoor 库**，仅限首次初始化）。

> init_data.json 只在空库生效，不适合增量变更；日常变更用方式一。

### 3.3 用户批量导入（XLSX）

用户较多时可在 Casdoor Web UI 批量导入：

1. 进入 Organization `main` → **Users** 页面，点击 **Download template (.xlsx)** 获取模板。
2. 按模板填写 `name` / `displayName` / `email` / `password` 等列（明文密码将按组织密码算法哈希入库）。
3. 点击 **Upload (.xlsx)** 上传完成导入。
4. 角色绑定：UI 导入不携带角色，导入后用 3.1 的 `update-user` 脚本批量补挂 `main/mera-user` 或 `main/mera-admin`。

也可用 API 逐条 `add-user`（字段同 3.1），适合与权限初始化脚本合并成一条流水线。

## 4. 多环境（测试/生产）与多应用

### 4.1 多环境导入

原则：测试与生产使用**各自独立的 Casdoor 实例**（或同一实例下独立 Organization），用户数据不互通；每个环境创建独立 Application，得到各自的 Client ID/Secret，写入对应环境的 `.env`。

本文所有命令均以三个环境变量参数化，**同一套脚本逐环境执行即可**，无环境相关硬编码：

```bash
# ── 测试环境 ──
export CASDOOR_ENDPOINT=https://casdoor.test.example.com
export CASDOOR_AUTH="test-client-id:test-client-secret"
export CASDOOR_ORG=main
# 执行 3.1 的全部 curl（建议固化成 deploy/casdoor/init_menus.sh）

# ── 生产环境：重新导出三个变量后重跑同一脚本 ──
export CASDOOR_ENDPOINT=https://casdoor.example.com
export CASDOOR_AUTH="prod-client-id:prod-client-secret"
export CASDOOR_ORG=main
```

各环境后端 `.env` 对照：

| 变量 | 测试 | 生产 | 说明 |
|---|---|---|---|
| `CASDOOR_ENDPOINT` | 测试 Casdoor 内网/网关地址 | 生产 Casdoor 内网/网关地址 | 后端拉 JWKS 用 |
| `CASDOOR_ISSUER` | 测试 Casdoor 外部地址（token 实际 `iss`） | 生产 Casdoor 外部地址 | **与 token 的 `iss` 必须一致** |
| `CASDOOR_CLIENT_ID/SECRET` | 测试 Application 凭证 | 生产 Application 凭证 | aud 校验 = Client ID |

> `CASDOOR_ISSUER` 解决容器内外地址不一致：后端拉 JWKS 走 `CASDOOR_ENDPOINT`（容器可达），校验 token `iss` 走 `CASDOOR_ISSUER`（Casdoor 签发的外部地址）；两者相同可不配，默认回退到 endpoint。

### 4.2 多应用共存

Casdoor 的角色与权限项是 **Organization 级**对象，同一 Organization 下所有 Application 共享。按场景选择：

| 场景 | 做法 |
|---|---|
| A. 多个应用同属 MERA（如将来独立的 `mera-admin` 前端） | 共用 `mera-*` 角色与权限项，无需重复定义；每个 Application 只需在 Token fields 带上 `sub`/`owner`/`roles` |
| B. 同一组织下接入非 MERA 应用（爬虫、ERP、WMS 等，见第 5 节） | 各应用使用自己的资源前缀（`menu:<app>:*`）与角色前缀（`<app>-user` / `<app>-admin`），权限项互不绑定对方角色；本文标识已按此约定命名 |
| C. 不同应用需要完全隔离的用户体系 | 拆多个 Organization，按第 3 节在各组织分别执行导入（脚本已按 `CASDOOR_ORG` 参数化） |

多应用下的后端隔离是天然的：`decode_token` 校验 `aud = CASDOOR_CLIENT_ID`，A 应用签发的 token 无法用于 B 应用的后端；`owner`（组织）则经 RLS 做数据隔离。

### 4.3 环境间数据迁移注意

- 权限项/角色是**配置**，用 3.1 脚本在测试环境验证通过后原样推广到生产；
- 用户是**数据**，测试与生产不互相导入（生产用户走注册或 XLSX 首次导入）；
- init_data.json（3.2）只适合首次空库初始化，跨环境推广用 API 脚本（3.1）。

## 5. 演进规划：多组织多应用

目标规模：2~3 个组织、7~8 个应用（MERA、专用爬虫、基础资料、ERP、WMS、刊登系统等）共用同一 Casdoor SSO。本节约定在 MERA 阶段即落地的规范，保证演进时 MERA 侧零改造。

### 5.1 拓扑原则

- **组织按"用户体系边界"划分**：同一批员工登录所有内部系统 → 一个主组织承载全部内部应用；外部用户、合作方等独立用户群 → 另建组织。不要按应用拆组织。
- **应用只是 OIDC 客户端**：新增应用 = 新建 Application + 配置 Token fields + 按第 3 节灌入该应用的角色/权限项。
- 跨组织需要共用同一应用时，使用 Casdoor 共享应用机制（见 5.4）。

### 5.2 应用注册表（新增应用先登记，key 一经使用不更改）

| app key | 系统 | 资源前缀 | 角色 |
|---|---|---|---|
| `mera` | 模型评估与选型系统 | `menu:mera:` | `mera-user` / `mera-admin` |
| `crawler` | 专用爬虫 | `menu:crawler:` | `crawler-user` / `crawler-admin` |
| `basedata` | 基础资料 | `menu:basedata:` | `basedata-user` / `basedata-admin` |
| `erp` | ERP | `menu:erp:` | `erp-user` / `erp-admin` |
| `wms` | WMS | `menu:wms:` | `wms-user` / `wms-admin` |
| `listing` | 刊登系统 | `menu:listing:` | `listing-user` / `listing-admin` |

> 注册表随新应用接入持续补充；权限项命名统一 `perm-<app>-<用途>`。

### 5.3 命名约定（MERA 阶段已采用）

- **角色**：`<app>-user` / `<app>-admin`，禁止创建全局 `user`/`admin` 角色（会在所有应用间互相放大权限）
- **资源标识**：`menu:<app>:<页面>`（管理菜单 `menu:<app>:admin:<模块>`）
- **Token fields**：每个应用必带 `sub` / `owner` / `roles` 三个 claim，接入 checklist 第一项
- **组织名**：默认主组织为 `main`（公司级名称，不编码环境或应用）；环境用独立 Casdoor 实例区分
  - 注意：Casdoor 组织创建后不可改名。`main` 从首个组织起即作为主组织名，后续新增组织按用户群命名（如外部合作方 `partner`）

### 5.4 跨组织共享应用（备用机制）

- **共享应用**：`built-in` 组织创建 shared application，各组织获得 `-org-<组织名>` 后缀的独立 Client ID，一套应用配置多组织可用
- **统一登录入口**：应用登录页开启组织选择（Input/Select），用户选择组织后完成认证
- 角色/权限仍是组织级：逐组织执行同一套导入脚本（`CASDOOR_ORG` 参数化已支持）
- 总公司-分公司等层级关系 Casdoor 不建模（组织是扁平的），层级放业务库（`parent_org_id`），跨组织数据视图由应用层实现

### 5.5 分阶段路线

| 阶段 | 动作 | MERA 侧改动 |
|---|---|---|
| Phase 1（当前） | 单组织 `main` + 单应用 `mera`，命名空间标识与 `<app>-` 角色前缀（本文档即此状态） | 无 |
| Phase 2（新应用接入） | 同组织新建 Application，按注册表灌入该应用角色/权限；用户按需挂多个应用的角色 | 无，`aud` 校验天然隔离 |
| Phase 3（用户群分裂） | 按 5.1 拆组织；需跨组织共用的应用改为共享应用 | 无，`owner` → RLS 链路兼容 |

> MERA 后端认证按 `aud`/`owner` 驱动（M03），角色名仅由前端路由守卫与 M08 管理接口校验消费，三个阶段均无需修改认证代码。

## 6. 导入后验收清单

- [ ] Casdoor Users 中存在目标用户，且 `Roles` 列显示 `main/mera-user` 或 `main/mera-admin`
- [ ] Permissions 页面存在 7 条权限项（1 条用户菜单 + 6 条管理菜单），resources 与第 2 节一致
- [ ] 用 `mera-user` 角色的用户登录前端：仅显示 4 个普通菜单，`/admin/*` 路由不可达
- [ ] 用 `mera-admin` 角色的用户登录前端：普通菜单 + 6 个管理菜单全部可见
- [ ] token 解码后可读到 `sub` / `owner=main` / `roles`（M03 `decode_token` 依赖）
- [ ] 直接调用管理 API 不带 `mera-admin` 角色返回 401/403（后端双重校验，M04 管理路由落地后验证）
