"""M01 结构化日志：local 环境用可读单行格式，dev/prod 输出 JSON 便于日志采集。

logger 的 extra 字段会进入 JSON 输出（如 task_id），堆栈仅进日志不进响应体。
"""

from __future__ import annotations

import json
import logging
import sys

# LogRecord 自带属性不作为 extra 重复输出
_RESERVED_ATTRS = frozenset(
    vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()
    | {"message", "asctime", "taskName"}
)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload: dict = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _RESERVED_ATTRS and not key.startswith("_"):
                payload[key] = value
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False, default=str)


def configure_logging(settings) -> None:
    """按 Settings 配置根 logger；幂等，可重复调用（create_app 多实例）。"""
    handler = logging.StreamHandler(sys.stdout)
    if settings.app_env == "local":
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    else:
        handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers = [handler]
    root.setLevel(logging.DEBUG if settings.debug else logging.INFO)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
