"""M08 Celery 应用装配：broker/backend 取自 Settings，路由兜底与 beat 计划。

队列分工（架构文档）：default 双 worker 冗余、fetch_api 仅 worker-1、
fetch_browser 仅 worker-2；生产者（M04 enqueue）已按策略显式指定队列，
task_routes 仅作未指定队列时的兜底。编排/降级/退避在 M05 orchestrator，
本模块只做触发与配置，不含业务逻辑。
"""

from __future__ import annotations

from celery import Celery

from app.core.config import get_settings
from app.services.enqueue import FETCH_TASK_NAME

_settings = get_settings()

celery_app = Celery(
    "mera",
    broker=_settings.broker_url,
    backend=_settings.result_backend,
    include=["app.tasks.fetch"],
)

celery_app.conf.update(
    # 兜底路由：生产者未显式指定队列时进 default（worker-1/worker-2 冗余消费）
    task_routes={FETCH_TASK_NAME: {"queue": "default"}},
    # 站点配置尚无调度字段，beat 计划留空；引入定时采集时由站点配置生成
    beat_schedule={},
)

# 显式导入任务模块完成注册：include 仅在 worker/beat CLI 启动时懒加载，
# 裸 import（python -c / flower --app 预检）也需要任务立即可见
from app.tasks import fetch as _fetch_tasks  # noqa: F401
