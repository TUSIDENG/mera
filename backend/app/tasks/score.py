"""LLM 离线打分任务：采集成功后对涉及的快照逐个打分。

兜底语义：LLM 调用/解析失败按 max_retries=2 + 指数退避重试，重试耗尽后仅记日志，
行保持采集回落分（score_source 为维度名），不向 broker 裸抛。
"""

from __future__ import annotations

from app.core.config import get_settings
from app.core.logging import get_logger
from app.db.session import get_session_factory
from app.llm_scoring.graph import score_snapshot
from app.repositories.repository import Repository
from app.services.enqueue import SCORE_TASK_NAME
from app.worker import celery_app

logger = get_logger(__name__)


def enqueue_score(model_id: str) -> None:
    """生产者入口：路由到 default 队列（worker.py task_routes 兜底）。"""
    celery_app.send_task(SCORE_TASK_NAME, args=[model_id])


@celery_app.task(name=SCORE_TASK_NAME, bind=True, max_retries=2, retry_backoff=True)
def run_score_task(self, model_id: str) -> bool | None:
    """执行一次 LLM 打分；开关关闭返回 None，打分成功/跳过返回 True/False。"""
    settings = get_settings()
    if not settings.llm_scorer_enabled:
        return None
    factory = get_session_factory(settings)
    with factory() as session:
        repo = Repository(session)
        try:
            scored = score_snapshot(repo, settings, model_id=model_id)
            session.commit()
            return scored
        except Exception as exc:  # noqa: BLE001  # 重试耗尽后仅记日志，行保持采集回落分
            session.rollback()
            try:
                raise self.retry(exc=exc) from exc
            except self.MaxRetriesExceededError:
                logger.exception(
                    "LLM 打分重试耗尽，保持采集回落分",
                    extra={"model_id": model_id},
                )
                return None
