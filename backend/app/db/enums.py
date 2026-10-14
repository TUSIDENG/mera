"""数据库状态与分类常量。"""

from __future__ import annotations

from enum import StrEnum


class FetchTaskType(StrEnum):
    MODEL_METRICS = "model_metrics"
    INFRASTRUCTURE_COST = "infrastructure_cost"


class FetchTaskStatus(StrEnum):
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    PARTIAL_SUCCEEDED = "partial_succeeded"
    FAILED_EXHAUSTED = "failed_exhausted"
    CAPTCHA_PENDING = "captcha_pending"


class EvaluationStatus(StrEnum):
    AWAITING_DATA = "awaiting_data"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    COMPLETED = "completed"
    FAILED = "failed"


class CostType(StrEnum):
    GPU_RENTAL = "gpu_rental"
    GPU_PURCHASE = "gpu_purchase"
    CPU = "cpu"
    ELECTRICITY = "electricity"
    COLOCATION = "colocation"
    BANDWIDTH = "bandwidth"


class BillingCycle(StrEnum):
    MONTHLY = "monthly"
    YEARLY = "yearly"


class SubscriptionSource(StrEnum):
    MANUAL = "manual"
    FETCH = "fetch"
