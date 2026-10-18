"""M04 通用分页模型。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class PageParams(BaseModel):
    """统一分页查询参数：page 从 1 开始，page_size 上限 100。"""

    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=100)

    @property
    def offset(self) -> int:
        return (self.page - 1) * self.page_size

    @property
    def limit(self) -> int:
        return self.page_size


class Page[T](BaseModel):
    items: list[T]
    total: int
    page: int
    page_size: int
