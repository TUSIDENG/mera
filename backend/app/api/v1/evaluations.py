"""M04 用户评测路由：评测记录 CRUD（RLS 组织隔离，按用户过滤）。"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends

from app.api.depends import get_current_identity, get_repository
from app.core.security import Identity
from app.repositories.repository import Repository
from app.schemas.common import Page, PageParams
from app.schemas.evaluations import EvaluationCreate, EvaluationOut

router = APIRouter(prefix="/evaluations", tags=["evaluations"])


@router.post("", response_model=EvaluationOut, status_code=201)
def create_evaluation(
    body: EvaluationCreate,
    identity: Annotated[Identity, Depends(get_current_identity)],
    repo: Annotated[Repository, Depends(get_repository)],
) -> EvaluationOut:
    evaluation = repo.create_evaluation(
        org_id=identity.org_id,
        user_id=identity.user_id,
        domain=body.domain,
        snapshot_used_ids=body.snapshot_used_ids,
        data=body.data,
        fetch_task_id=body.fetch_task_id,
    )
    return EvaluationOut.model_validate(evaluation)


@router.get("", response_model=Page[EvaluationOut])
def list_evaluations(
    identity: Annotated[Identity, Depends(get_current_identity)],
    repo: Annotated[Repository, Depends(get_repository)],
    page_params: Annotated[PageParams, Depends()],
) -> Page[EvaluationOut]:
    items, total = repo.list_evaluations(
        user_id=identity.user_id, limit=page_params.limit, offset=page_params.offset
    )
    return Page(
        items=[EvaluationOut.model_validate(item) for item in items],
        total=total,
        page=page_params.page,
        page_size=page_params.page_size,
    )
