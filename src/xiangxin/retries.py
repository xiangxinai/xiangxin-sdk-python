"""重试策略。 / Retry policy."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Callable

from .exceptions import APIConnectionError, APIError, APITimeoutError, RateLimitError, parse_retry_after

__all__ = ["RetryPolicy", "DEFAULT_RETRY_STATUSES"]

DEFAULT_RETRY_STATUSES: frozenset[int] = frozenset({408, 429, *range(500, 600)})
"""默认会重试的 HTTP 状态码。 / HTTP statuses retried by default."""


@dataclass(frozen=True)
class RetryPolicy:
    """控制 SDK 何时、隔多久重试失败的请求。

    Controls when and how long the SDK waits before retrying a failed request.
    Delays grow exponentially (``backoff_initial * 2**n``, capped at
    ``backoff_max``) with random jitter; a ``retry-after`` / ``retry-after-ms``
    header from the server takes precedence when ``respect_retry_after`` is on.

    指数退避：第 n 次重试等待 ``backoff_initial * 2**n``（不超过 ``backoff_max``），
    并随机扣减 ``backoff_jitter`` 比例的抖动；若服务端返回 ``retry-after``，优先使用它。

    Example::

        from xiangxin import RetryPolicy, XiangxinClient

        client = XiangxinClient(retry=RetryPolicy(max_retries=4, backoff_max=2.0))
        client = XiangxinClient(retry=RetryPolicy(max_retries=0))  # 关闭重试 / disable
    """

    max_retries: int = 2
    """首次请求之外的最大重试次数；``0`` 表示不重试。 / Retries after the first attempt."""

    retry_statuses: frozenset[int] = field(default_factory=lambda: DEFAULT_RETRY_STATUSES)
    """会触发重试的 HTTP 状态码。 / HTTP statuses that trigger a retry."""

    backoff_initial: float = 0.5
    """首次退避秒数。 / First backoff delay in seconds."""

    backoff_max: float = 5.0
    """单次退避上限（秒）。 / Maximum single backoff delay in seconds."""

    backoff_jitter: float = 0.25
    """每次延迟中随机扣减的比例（0–1）。 / Fraction randomly subtracted from each delay."""

    respect_retry_after: bool = True
    """是否遵守 ``retry-after`` / ``retry-after-ms`` 响应头。 / Honor retry-after headers."""

    max_retry_after: float = 60.0
    """服务端建议等待时间的上限（秒）；超过时不采纳，改用指数退避。

    Upper bound on a server-requested wait; longer hints fall back to exponential backoff.
    """

    retry_connection_errors: bool = True
    """是否重试连接错误。 / Retry ``APIConnectionError``."""

    retry_timeouts: bool = True
    """是否重试超时。 / Retry ``APITimeoutError``."""

    predicate: Callable[[BaseException], bool] | None = None
    """自定义判断：返回 ``True`` 时额外触发重试。 / Extra predicate forcing a retry."""

    timeout: float | None = 60.0
    """单次 SDK 调用的总预算（秒，含所有尝试与等待）；``None`` 不限。

    Total budget per SDK call in seconds, including attempts and waits; ``None`` = unlimited.
    """

    def __post_init__(self) -> None:
        if self.max_retries < 0:
            raise ValueError("max_retries must be >= 0")
        if not 0 <= self.backoff_jitter <= 1:
            raise ValueError("backoff_jitter must be between 0 and 1")
        if self.backoff_initial < 0 or self.backoff_max < 0:
            raise ValueError("backoff values must be >= 0")
        # 允许传入普通 set / Accept a plain set for convenience.
        object.__setattr__(self, "retry_statuses", frozenset(self.retry_statuses))

    def should_retry(self, error: BaseException) -> bool:
        """判断某个异常是否应当重试（不考虑次数与预算）。

        Whether ``error`` is retryable, ignoring attempt count and budget.
        """
        if self.predicate is not None and self.predicate(error):
            return True
        if isinstance(error, APITimeoutError):
            return self.retry_timeouts
        if isinstance(error, APIConnectionError):
            return self.retry_connection_errors
        if isinstance(error, APIError):
            return error.status_code in self.retry_statuses
        return False

    def backoff(self, retry_index: int) -> float:
        """第 ``retry_index`` 次重试（从 0 起）的退避秒数，含抖动。

        Backoff delay in seconds for the ``retry_index``-th retry (0-based), with jitter.
        """
        if self.backoff_initial <= 0 or self.backoff_max <= 0:
            return 0.0
        base = min(self.backoff_max, self.backoff_initial * (2**retry_index))
        return base * (1 - self.backoff_jitter * random.random())

    def delay_for(self, error: BaseException, retry_index: int) -> float | None:
        """计算下一次重试前的等待秒数；返回 ``None`` 表示不应重试。

        Seconds to wait before the next retry, or ``None`` if it should not be retried.
        """
        if self.respect_retry_after and isinstance(error, APIError):
            hinted = error.retry_after if isinstance(error, RateLimitError) else parse_retry_after(error.headers)
            if hinted is not None:
                if hinted <= self.max_retry_after:
                    return hinted
                # 建议等待过长：不采纳，改用指数退避（与 TypeSafe JS SDK 一致）
                # A server hint beyond the cap is ignored in favour of exponential backoff.
        return self.backoff(retry_index)
