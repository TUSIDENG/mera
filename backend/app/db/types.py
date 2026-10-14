"""跨数据库方言的字段类型。"""

from __future__ import annotations

import uuid
from collections.abc import Sequence

from sqlalchemy import JSON, Uuid
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.types import TypeDecorator


class JSONBType(TypeDecorator):
    """PostgreSQL 使用 JSONB，SQLite 单测回退为通用 JSON。"""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(JSON())


class UUIDArrayType(TypeDecorator):
    """PostgreSQL 使用 UUID[]，SQLite 单测回退为 JSON 数组。"""

    impl = JSON
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(ARRAY(Uuid()))
        return dialect.type_descriptor(JSON())

    def process_bind_param(self, value: Sequence[uuid.UUID] | None, dialect):
        if value is None:
            return None
        if dialect.name == "postgresql":
            return list(value)
        return [str(item) for item in value]

    def process_result_value(self, value, dialect):
        if value is None:
            return []
        return [item if isinstance(item, uuid.UUID) else uuid.UUID(item) for item in value]
