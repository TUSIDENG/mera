"""M05 单元测试 fixtures。"""

from __future__ import annotations

import pytest
from fakes import FakeClock


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()
