# AGENTS

## 项目简介

MERA（Model Evaluation & Selection System）是一个大模型评估与选型决策支持系统，用于采集模型榜单、API 价格、订阅套餐和自部署基础设施成本，结合性能、价格、用量与组织数据进行模型选型分析。

系统主要包含：

- 后端：Python 3.12、FastAPI、SQLAlchemy 2、Alembic、Celery。
- 前端：React 18、Vite、TypeScript、shadcn/ui、Tailwind CSS。
- 数据与队列：PostgreSQL、Redis。
- 认证：Casdoor OIDC 与 PostgreSQL RLS 组织隔离。
- 采集：官方 API、接口逆向、Playwright、指纹浏览器，按站点配置降级。
- 本地部署：根目录 `docker-compose.yaml` 启动后端、前端、worker、beat、PostgreSQL、Redis 和 Casdoor。

## 工作约定

- 先阅读相关文档和现有代码，再修改实现。
- 优先编辑已有文件，避免创建不必要的新文件。
- 后端业务代码遵循 FastAPI + SQLAlchemy + 依赖注入方式；采集解析、标准化和评分逻辑应保持为可单测的纯函数。
- 前端通过后端 REST API 获取数据，不直连数据库。
- 采集实现必须遵守目标站点服务条款与合规边界，不绕过登录、付费墙或强验证码。
- 密钥、令牌和登录会话只允许通过环境变量或密钥管理注入，禁止写入仓库。

## 注释要求

- 所有 Python 函数、Python 类、TypeScript/JavaScript 函数都必须写注释，没有注释的代码不予合入。
- Python 使用 Google 风格 docstring，前端使用 JSDoc。
- 注释说明「做什么、参数含义、返回值、异常与副作用」，不复述代码字面含义；显而易见的赋值和循环不需要注释。
- 采集解析、标准化、评分等纯函数必须注明输入输出口径、单位与边界情况。
- 修改函数行为时同步更新注释，避免注释与实现不一致。

### Python 函数

```python
def normalize_price(price: Decimal, unit: str, *, quantity: int = 1) -> Decimal:
    """将报价折算为统一口径的单价。

    Args:
        price: 原始报价金额，单位为 ``unit`` 对应的计量单位。
        unit: 计量单位，支持 ``"1k_tokens"``、``"1m_tokens"``、``"month"``。
        quantity: 计价数量，订阅套餐中表示覆盖的用户数，必须大于等于 1。

    Returns:
        统一口径的单价：按 token 计价时归一为「每百万 tokens」，
        按订阅计价时归一为「每用户每月」，保留 6 位小数。

    Raises:
        ValueError: ``unit`` 不被支持，或 ``quantity`` 小于 1。

    Example:
        >>> normalize_price(Decimal("0.002"), "1k_tokens")
        Decimal('2.000000')
    """
    if quantity < 1:
        raise ValueError("quantity must be >= 1")
    if unit not in _UNIT_FACTORS:
        raise ValueError(f"unsupported unit: {unit}")
    return (price * _UNIT_FACTORS[unit] / quantity).quantize(Decimal("0.000001"))
```

### Python 类

```python
class LeaderboardParser:
    """榜单页面解析器，把采集到的原始 HTML 转为标准化榜单条目。

    解析逻辑不依赖数据库与网络，便于单测。

    Attributes:
        source: 榜单来源标识，写入 ``benchmark.source``。
        selectors: 站点 DOM 选择器配置，未传入的键使用内置默认值。

    Example:
        >>> parser = LeaderboardParser(source="lmaarena", selectors={"row": "tr.entry"})
        >>> parser.parse(html)[0].model_name
        'gpt-4o'
    """

    def __init__(self, source: str, selectors: dict[str, str] | None = None) -> None:
        """初始化解析器。

        Args:
            source: 榜单来源标识。
            selectors: 可选的 DOM 选择器覆盖配置。
        """
        self.source = source
        self.selectors = {**DEFAULT_SELECTORS, **(selectors or {})}

    def parse(self, html: str) -> list[BenchmarkEntry]:
        """解析榜单 HTML，返回标准化条目。

        Args:
            html: 采集模块抓取到的原始页面内容。

        Returns:
            按排名升序排列的条目列表；页面中没有可解析行时返回空列表。
        """
        ...
```

### TypeScript / JavaScript 函数

```ts
/**
 * 拉取模型价格列表，并按供应商聚合。
 *
 * @param params - 查询条件。
 * @param params.provider - 供应商标识，如 `"openai"`；为空时返回全部供应商。
 * @param signal - 可选的 AbortSignal，用于取消请求。
 * @returns 按供应商分组的价格列表。
 * @throws {ApiError} 后端返回非 2xx 状态码时抛出。
 * @example
 * const groups = await fetchPrices({ provider: "openai" });
 * console.log(groups[0].models.length);
 */
export async function fetchPrices(
  params: PriceQuery,
  signal?: AbortSignal,
): Promise<PriceGroup[]> {
  const query = new URLSearchParams({ provider: params.provider ?? "" });
  const res = await fetch(`/api/prices?${query}`, { signal });
  if (!res.ok) throw new ApiError(res.status);
  return res.json();
}
```

## 换行符要求

- 仓库内所有文本文件必须使用 **LF（`\n`）** 换行符。
- 禁止提交 CRLF（`\r\n`）换行符。
- 在 Windows 环境中编辑、创建脚本、Dockerfile、YAML、Markdown、Python、TypeScript 等文件时，也必须保持 LF。
