"""SDK 异常体系。 / Exception hierarchy of the SDK.

::

    XiangxinError
    ├── APIError                        服务端返回了非 2xx 响应 / non-2xx HTTP response
    │   ├── BadRequestError             400
    │   ├── AuthenticationError         401
    │   ├── InsufficientBalanceError    402
    │   ├── PermissionDeniedError       403
    │   ├── NotFoundError               404
    │   ├── ConflictError               409
    │   ├── RequestTooLargeError        413
    │   ├── UnprocessableEntityError    422
    │   ├── RateLimitError              429
    │   ├── OverloadedError             529
    │   ├── InternalServerError         其他 5xx / other 5xx
    │   └── APIResponseValidationError  2xx 但响应体结构不符 / malformed 2xx body
    ├── APIConnectionError              没有拿到 HTTP 响应 / no HTTP response
    │   └── APITimeoutError             请求超时 / request timed out
    └── WaitTimeoutError                ``reflexes.wait`` 等待超时 / wait deadline exceeded
"""

from __future__ import annotations

import email.utils
import time
from typing import Any

import httpx

from .constants import REQUEST_ID_HEADER

__all__ = [
    "XiangxinError",
    "APIError",
    "BadRequestError",
    "AuthenticationError",
    "InsufficientBalanceError",
    "PermissionDeniedError",
    "NotFoundError",
    "ConflictError",
    "RequestTooLargeError",
    "UnprocessableEntityError",
    "RateLimitError",
    "OverloadedError",
    "InternalServerError",
    "APIResponseValidationError",
    "APIConnectionError",
    "APITimeoutError",
    "WaitTimeoutError",
]


class XiangxinError(Exception):
    """所有 SDK 异常的基类；配置错误（如缺少 API 密钥）也直接抛出此类。

    Base class for every SDK error. Configuration problems such as a missing
    API key are raised as this class directly.
    """


class APIError(XiangxinError):
    """服务端返回了不成功的 HTTP 响应。

    An unsuccessful HTTP response, carrying its status, body and headers.

    Attributes:
        status_code: HTTP 状态码。 / HTTP status code.
        body: 解析后的 JSON 错误体，或纯文本，空体为 ``None``。
            / Parsed JSON error body, plain text, or ``None`` when empty.
        detail: 错误体中的 ``detail`` 字段（若有）。 / The ``detail`` field, if any.
        headers: 响应头。 / Response headers.
        endpoint: ``"METHOD URL"``（不含查询参数）。 / ``"METHOD URL"`` without query.
    """

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        body: Any = None,
        headers: httpx.Headers | None = None,
        endpoint: str | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.body = body
        self.headers = headers if headers is not None else httpx.Headers()
        self.endpoint = endpoint

    @property
    def status(self) -> int:
        """``status_code`` 的别名。 / Alias of ``status_code``."""
        return self.status_code

    @property
    def detail(self) -> Any:
        """错误体的 ``detail`` 字段；没有时为 ``None``。

        The ``detail`` field of the error body, or ``None``.
        """
        if isinstance(self.body, dict):
            return self.body.get("detail")
        return None

    @property
    def request_id(self) -> str | None:
        """``x-request-id`` 响应头，便于联系技术支持。

        The ``x-request-id`` response header, useful when contacting support.
        """
        return self.headers.get(REQUEST_ID_HEADER)

    def __str__(self) -> str:
        parts = [f"{self.status_code} {self.message}"]
        if self.request_id:
            parts.append(f"(request_id={self.request_id})")
        return " ".join(parts)


class BadRequestError(APIError):
    """请求格式错误（400）。 / The request was malformed (400)."""


class AuthenticationError(APIError):
    """API 密钥缺失、无效或已禁用（401）。 / Missing, invalid or disabled API key (401)."""


class InsufficientBalanceError(APIError):
    """组织余额不足，请在控制台充值（402）。

    The organization's balance is exhausted; top up in the console (402).
    """


class PermissionDeniedError(APIError):
    """无权访问（403）。 / Access denied (403)."""


class NotFoundError(APIError):
    """资源不存在，例如未知模型（404）。 / Resource not found, e.g. unknown model (404)."""


class ConflictError(APIError):
    """与资源当前状态冲突（409），不会自动重试。 / Conflicts with the resource's state (409); never retried.

    ``detail`` 取值 / ``detail`` values:

    - ``reflex_not_ready``：反射首次训练尚未完成，暂不能推理。 / The reflex has no trained version yet.
    - ``reflex_busy``：该反射正在训练，不能再次提交。 / The reflex is already training.
    - ``too_many_reflexes: …``：已达每个组织的反射数量上限。 / Per-organization reflex limit reached.
    """


class RequestTooLargeError(APIError):
    """请求体过大（413），例如练反射的样本超过 50MB。

    The request body is too large (413), e.g. reflex examples above 50MB.
    """


class UnprocessableEntityError(APIError):
    """请求未通过服务端校验，例如选项过多或超出 token 上限（422）。

    The request failed server-side validation, e.g. too many choices or
    too many tokens (422).
    """


class RateLimitError(APIError):
    """超出速率限制（429）。 / Rate limit exceeded (429).

    Attributes:
        retry_after: 服务端建议的等待秒数；无该头时为 ``None``。
            / Server-suggested wait in seconds, or ``None``.
    """

    def __init__(self, message: str, **kwargs: Any) -> None:
        super().__init__(message, **kwargs)
        self.retry_after: float | None = parse_retry_after(self.headers)


class OverloadedError(APIError):
    """服务过载或模型后端暂不可用（529），稍后重试即可。

    The service is overloaded or no model backend is available (529);
    retrying later usually succeeds.
    """


class InternalServerError(APIError):
    """服务端内部错误（5xx，529 除外）。 / Server-side failure (5xx other than 529)."""


class APIResponseValidationError(APIError):
    """HTTP 成功但响应体缺少或包含结构错误的必需字段。

    A successful HTTP response whose body is missing or has malformed required data.
    """


class APIConnectionError(XiangxinError, ConnectionError):
    """请求未能得到 HTTP 响应（DNS、连接被拒绝、连接中断等）。

    The request failed without an HTTP response (DNS, refused, reset, ...).
    """


class APITimeoutError(APIConnectionError, TimeoutError):
    """请求超过了配置的超时时间。 / The request exceeded its configured timeout."""


class WaitTimeoutError(XiangxinError, TimeoutError):
    """``reflexes.wait`` 在 ``timeout`` 内没有等到结束状态；训练本身不受影响。

    ``reflexes.wait`` gave up before the reflex reached a final status; training continues.

    Attributes:
        reflex: 最后一次查询到的反射。 / The reflex as last observed.
    """

    def __init__(self, message: str, reflex: Any = None) -> None:
        super().__init__(message)
        self.reflex = reflex


_STATUS_TO_ERROR: dict[int, type[APIError]] = {
    400: BadRequestError,
    401: AuthenticationError,
    402: InsufficientBalanceError,
    403: PermissionDeniedError,
    404: NotFoundError,
    409: ConflictError,
    413: RequestTooLargeError,
    422: UnprocessableEntityError,
    429: RateLimitError,
    529: OverloadedError,
}


def error_class_for_status(status_code: int) -> type[APIError]:
    """把 HTTP 状态码映射到异常类。 / Map an HTTP status code to an exception class."""
    if status_code in _STATUS_TO_ERROR:
        return _STATUS_TO_ERROR[status_code]
    if status_code >= 500:
        return InternalServerError
    return APIError


def parse_retry_after(headers: httpx.Headers) -> float | None:
    """解析 ``retry-after-ms`` / ``retry-after`` 头，返回秒数。

    Parse ``retry-after-ms`` or ``retry-after`` (seconds or HTTP date) into seconds.
    """
    raw_ms = headers.get("retry-after-ms")
    if raw_ms:
        try:
            value = float(raw_ms) / 1000.0
            if value >= 0:
                return value
        except ValueError:
            pass
    raw = headers.get("retry-after")
    if not raw:
        return None
    try:
        value = float(raw)
        return value if value >= 0 else None
    except ValueError:
        pass
    try:
        parsed = email.utils.parsedate_to_datetime(raw)
    except (TypeError, ValueError, IndexError):
        return None
    if parsed is None:
        return None
    return max(0.0, parsed.timestamp() - time.time())
