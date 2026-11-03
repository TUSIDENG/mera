"""站点元数据响应模型（M04 站点列表，供前端任务类型联动）。"""

from __future__ import annotations

from pydantic import BaseModel


class SiteOut(BaseModel):
    key: str
    label: str
    domain: str | None
    data_type: str
    data_types: list[str]
