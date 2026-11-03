"""M08 采集任务外壳：读 fetch_tasks、加载站点方案链、交给 M05 编排执行。

职责边界：策略降级/退避/终态分流在 M05 orchestrator；快照/成本/套餐 upsert
由 run_fetch 内部按 DTO 类型路由到 M02 仓储完成。本模块只做 I/O 外壳：
取任务 -> 装配依赖 -> 触发执行 -> 提交事务。异常不裸抛（避免 broker 无限重投），
按 M02 状态机兜底标记 failed_exhausted，迁移非法时仅记日志。
"""

from __future__ import annotations

import uuid
from typing import cast

from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.exceptions import ConfigError
from app.core.logging import get_logger
from app.db.enums import FetchTaskStatus
from app.db.session import get_session_factory
from app.fetchers.config_loader import SITES_DIR, SiteConfig, load_site
from app.fetchers.orchestrator import FetchTaskControl, RepoTaskHandle, run_fetch
from app.repositories.repository import Repository
from app.services.enqueue import FETCH_TASK_NAME
from app.worker import celery_app

logger = get_logger(__name__)


@celery_app.task(name=FETCH_TASK_NAME)
def run_fetch_task(task_id: str) -> str | None:
    """执行一次采集任务并返回终态字符串；任务不存在或执行异常返回 None。

    幂等：消息重复投递时，已终态任务的状态机迁移会被仓储拒绝并走兜底日志，
    不产生二次写入。
    """
    settings = get_settings()
    task_uuid = uuid.UUID(task_id)
    factory = get_session_factory(settings)
    with factory() as session:
        repo = Repository(session)
        row = repo.get_task(task_uuid)
        if row is None:
            logger.warning("采集任务不存在，丢弃消息", extra={"task_id": task_id})
            return None
        try:
            site = load_site(SITES_DIR, row.source_key)
            site = select_site_strategies(site, (row.data or {}).get("fetch_strategy"))
            # RepoTaskHandle 是 run_fetch 的官方适配器；其 attempt_count 为只读属性，
            # 与协议的可写声明存在静态差异（编排层运行期只读，无冲突），显式收窄。
            handle = cast(FetchTaskControl, RepoTaskHandle(repo, task_uuid))
            result = run_fetch(
                handle,
                site,
                repo,
                min_hits=settings.min_fetch_hits,
                max_attempts=settings.max_fetch_attempts,
            )
            session.commit()
        except Exception as exc:  # 兜底：不裸抛，避免 broker 层无限重投
            session.rollback()
            logger.exception("采集任务执行异常", extra={"task_id": task_id})
            _mark_failed_safely(repo, session, task_uuid, exc)
            return None
        logger.info(
            "采集任务完成",
            extra={
                "task_id": task_id,
                "status": str(result.status),
                "hit_count": result.hit_count,
            },
        )
        return str(result.status)


def select_site_strategies(site: SiteConfig, strategy: str | None) -> SiteConfig:
    """按任务声明的 fetch_strategy 裁剪站点方案链（纯函数）；None 为全部声明策略。

    指定站点未声明的策略属于配置错配，抛 ConfigError 快速失败（不消耗退避重试）。
    """
    if strategy is None:
        return site
    if strategy not in site.strategies:
        raise ConfigError(f"站点 {site.key} 未声明方案: {strategy}")
    return SiteConfig(
        key=site.key,
        path=site.path,
        cfg=site.cfg,
        data_type=site.data_type,
        data_types=site.data_types,
        domain=site.domain,
        strategies=[strategy],
        fetchers=[(name, fetcher) for name, fetcher in site.fetchers if name == strategy],
        skipped=[(name, reason) for name, reason in site.skipped if name == strategy],
    )


def _mark_failed_safely(
    repo: Repository, session: Session, task_uuid: uuid.UUID, exc: Exception
) -> None:
    """异常兜底：新事务内按状态机标记 failed_exhausted；状态不允许时仅记日志。"""
    error_message = f"{exc.__class__.__name__}: {exc}"
    try:
        task = repo.get_task(task_uuid)
        if task is None:
            return
        if task.status == FetchTaskStatus.PENDING.value:
            task = repo.mark_running(task_uuid)
        if task.status == FetchTaskStatus.RUNNING.value:
            repo.mark_failed_exhausted(task_uuid, error_message=error_message)
        else:
            logger.warning(
                "任务状态不允许兜底标记 failed_exhausted，保持原状态",
                extra={"task_id": str(task_uuid), "status": task.status},
            )
        session.commit()
    except Exception:  # 兜底本身失败不能再向外抛
        session.rollback()
        logger.exception("采集任务兜底标记失败", extra={"task_id": str(task_uuid)})
