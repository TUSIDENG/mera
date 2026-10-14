"""UUIDv7 工具测试。"""

from app.db.uuid7 import uuid7


def test_uuid7_has_version_7_and_is_time_ordered() -> None:
    first = uuid7()
    second = uuid7()

    assert first.version == 7
    assert second.version == 7
    assert first < second
