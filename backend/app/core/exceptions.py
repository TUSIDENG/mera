"""M01 统一异常体系（实现指南 3.1）：业务模块只抛这些异常，API 层统一映射为 JSON。

status_code 为该异常类型的默认映射；允许实例级覆盖。
"""

from __future__ import annotations


class AppError(Exception):
    """业务异常基类：code 机器可读、message 人可读、status_code 由 API 层映射。"""

    code: str = "app_error"
    status_code: int = 500

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        status_code: int | None = None,
    ) -> None:
        self.message = message
        if code is not None:
            self.code = code
        if status_code is not None:
            self.status_code = status_code
        super().__init__(message)


class ConfigError(AppError):
    """M05 站点配置非法。"""

    code = "config_error"
    status_code = 500


class SecretError(AppError):
    """M05 密钥缺失/格式错误（异常消息中不得含密钥值）。"""

    code = "secret_error"
    status_code = 500


class AuthError(AppError):
    """M03 认证失败（401）。"""

    code = "auth_error"
    status_code = 401


class FetchFailed(AppError):
    """M06 采集失败（编排层据此降级到下一方案）。"""

    code = "fetch_failed"
    status_code = 502


class CaptchaRequired(AppError):
    """M07 强验证码（编排层据此置 captcha_pending，不再降级）。"""

    code = "captcha_required"
    status_code = 409


class InvalidTransition(AppError):
    """M02 任务状态机非法迁移。"""

    code = "invalid_transition"
    status_code = 409


class InvalidWeights(AppError):
    """M09 评分权重非法（权重和 != 1）。"""

    code = "invalid_weights"
    status_code = 422
