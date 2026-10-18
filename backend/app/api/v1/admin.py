"""M04 管理端路由（mera-admin 角色）：套餐/成本维护与失败任务重触发。"""

from __future__ import annotations

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query

from app.api.depends import get_enqueuer, get_repository, require_admin
from app.core.exceptions import InvalidTransition, NotFoundError
from app.core.security import Identity
from app.db.enums import FetchTaskStatus, SubscriptionSource
from app.repositories.dto import CostRecord, CreateTaskParams, SubscriptionPlanRecord
from app.repositories.repository import Repository
from app.schemas.catalogs import (
    BillingCycleStr,
    CostOut,
    CostPut,
    CostTypeStr,
    PlanOut,
    PlanPut,
)
from app.schemas.common import Page, PageParams
from app.schemas.tasks import FetchTaskOut
from app.services.enqueue import FetchTaskEnqueuer

router = APIRouter(
    prefix="/admin",
    tags=["admin"],
    dependencies=[Depends(require_admin)],
)


@router.get("/subscription-plans", response_model=Page[PlanOut])
def admin_list_plans(
    repo: Annotated[Repository, Depends(get_repository)],
    page_params: Annotated[PageParams, Depends()],
    provider: Annotated[str | None, Query(max_length=50)] = None,
) -> Page[PlanOut]:
    """管理端套餐列表（含停用套餐）。"""
    items, total = repo.list_plans(
        provider=provider,
        active_only=False,
        limit=page_params.limit,
        offset=page_params.offset,
    )
    return Page(
        items=[PlanOut.model_validate(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )


@router.put("/subscription-plans/{provider}/{plan_key}/{billing_cycle}", response_model=PlanOut)
def admin_put_plan(
    provider: str,
    plan_key: str,
    billing_cycle: BillingCycleStr,
    body: PlanPut,
    repo: Annotated[Repository, Depends(get_repository)],
) -> PlanOut:
    """按业务键 upsert 套餐（source=manual）。"""
    repo.upsert_subscription_plans(
        [
            SubscriptionPlanRecord(
                provider=provider,
                plan_key=plan_key,
                plan_name=body.plan_name,
                monthly_price=body.monthly_price,
                currency=body.currency,
                billing_cycle=billing_cycle,
                is_active=body.is_active,
                source=SubscriptionSource.MANUAL.value,
                data=body.data,
            )
        ]
    )
    plan = repo.get_plan(provider, plan_key, billing_cycle)
    if plan is None:  # pragma: no cover - upsert 后必然存在
        raise NotFoundError("套餐写入失败")
    return PlanOut.model_validate(plan)


@router.get("/infrastructure-costs", response_model=Page[CostOut])
def admin_list_costs(
    repo: Annotated[Repository, Depends(get_repository)],
    page_params: Annotated[PageParams, Depends()],
    cost_type: Annotated[CostTypeStr | None, Query()] = None,
) -> Page[CostOut]:
    items, total = repo.list_costs(
        cost_type=cost_type, limit=page_params.limit, offset=page_params.offset
    )
    return Page(
        items=[CostOut.model_validate(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )


@router.put("/infrastructure-costs/{cost_type}/{name}", response_model=CostOut)
def admin_put_cost(
    cost_type: CostTypeStr,
    name: str,
    body: CostPut,
    repo: Annotated[Repository, Depends(get_repository)],
    region: Annotated[str, Query(max_length=50)] = "default",
) -> CostOut:
    """按业务键 upsert 成本条目（region 缺省 default）。"""
    repo.upsert_costs(
        [
            CostRecord(
                cost_type=cost_type,
                name=name,
                unit=body.unit,
                unit_price=body.unit_price,
                region=region,
                source="manual",
                is_active=body.is_active,
                data=body.data,
            )
        ]
    )
    cost = repo.get_cost(cost_type, name, region)
    if cost is None:  # pragma: no cover - upsert 后必然存在
        raise NotFoundError("成本条目写入失败")
    return CostOut.model_validate(cost)


@router.post("/fetch-tasks/{task_id}/retrigger", response_model=FetchTaskOut, status_code=202)
def admin_retrigger_task(
    task_id: uuid.UUID,
    identity: Annotated[Identity, Depends(require_admin)],
    repo: Annotated[Repository, Depends(get_repository)],
    enqueuer: Annotated[FetchTaskEnqueuer, Depends(get_enqueuer)],
) -> FetchTaskOut:
    """重触发 failed_exhausted 任务：按原业务键创建新任务并入队。"""
    task = repo.get_task(task_id)
    if task is None:
        raise NotFoundError(f"采集任务不存在: {task_id}")
    if task.status != FetchTaskStatus.FAILED_EXHAUSTED.value:
        raise InvalidTransition(f"仅 failed_exhausted 任务可重触发（当前 {task.status}）")

    new_task = repo.create_task(
        CreateTaskParams(
            task_type=task.task_type,
            source_key=task.source_key,
            domain=task.domain,
            triggered_by=identity.user_id,
            auto_start=True,
            data={
                "retrigger_of": str(task_id),
                "fetch_strategy": task.fetch_strategy,
            },
        )
    )
    enqueuer.enqueue(new_task.id, strategy=task.fetch_strategy)
    return FetchTaskOut.model_validate(new_task)
