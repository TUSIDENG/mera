"""M09 minmax 归一化边界用例。"""

from __future__ import annotations

import pytest

from app.core.exceptions import AppError
from app.scoring.engine import normalize_benchmark


def test_empty_returns_empty() -> None:
    assert normalize_benchmark({}) == {}


def test_single_value_neutral() -> None:
    assert normalize_benchmark({"only": 42.0}) == {"only": 0.5}


def test_all_equal_values_neutral() -> None:
    assert normalize_benchmark({"a": 10.0, "b": 10.0, "c": 10.0}) == {
        "a": 0.5,
        "b": 0.5,
        "c": 0.5,
    }


def test_minmax_normal_range() -> None:
    assert normalize_benchmark({"a": 0.0, "b": 50.0, "c": 100.0}) == {
        "a": 0.0,
        "b": 0.5,
        "c": 1.0,
    }


def test_minmax_negative_inputs() -> None:
    assert normalize_benchmark({"a": -10.0, "b": 0.0, "c": 10.0}) == {
        "a": 0.0,
        "b": 0.5,
        "c": 1.0,
    }


def test_unknown_method_raises_app_error() -> None:
    with pytest.raises(AppError) as exc_info:
        normalize_benchmark({"a": 1.0}, method="zscore")
    assert exc_info.value.code == "config_error"
