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

## 换行符要求

- 仓库内所有文本文件必须使用 **LF（`\n`）** 换行符。
- 禁止提交 CRLF（`\r\n`）换行符。
- 在 Windows 环境中编辑、创建脚本、Dockerfile、YAML、Markdown、Python、TypeScript 等文件时，也必须保持 LF。
