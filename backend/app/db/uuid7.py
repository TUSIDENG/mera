"""UUIDv7 生成工具（RFC 9562，应用层时间有序主键）。"""

from __future__ import annotations

import os
import threading
import time
import uuid

_RANDOM_MASK = (1 << 74) - 1
_VARIANT_BITS = 0b10 << 62
_lock = threading.Lock()
_last_timestamp_ms = 0
_counter = 0


def uuid7() -> uuid.UUID:
    """生成时间有序的 UUIDv7；同一毫秒内通过计数器单调递增。"""
    global _last_timestamp_ms, _counter

    timestamp_ms = int(time.time() * 1000)
    with _lock:
        if timestamp_ms <= _last_timestamp_ms:
            timestamp_ms = _last_timestamp_ms
            _counter += 1
        else:
            _last_timestamp_ms = timestamp_ms
            _counter = int.from_bytes(os.urandom(9), "big")

        sequence = _counter & _RANDOM_MASK
        random_part = (sequence & ((1 << 62) - 1)) | _VARIANT_BITS
        value = (timestamp_ms << 80) | (7 << 76) | random_part
        return uuid.UUID(int=value)
