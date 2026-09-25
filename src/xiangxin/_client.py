"""同步客户端 ``XiangxinClient`` 与异步客户端 ``AsyncXiangxinClient``。

The synchronous ``XiangxinClient`` and asynchronous ``AsyncXiangxinClient``.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Mapping
from types import TracebackType
from typing import Any, TypeVar, overload

import httpx
from pydantic import BaseModel

from ._base import (
    MODELS_PATH,
    SYSTEM_ONE_PATH,
    RawResponse,
    Timeout,
    build_system_one_body,
    default_headers,
    log_response,
    make_api_error,
    merge_extra_headers,
    resolve_api_key,
    resolve_base_url,
    resolve_model,
    validate_timeout,
)
from ._logging import logger, redact_headers
from .constants import DEFAULT_TIMEOUT
from .exceptions import APIConnectionError, APITimeoutError, XiangxinError
from .retries import RetryPolicy
from .types import JSONContent, ListModelsResponse, Question, SystemOneResponse

__all__ = [
    "XiangxinClient",
    "AsyncXiangxinClient",
    "Models",
    "AsyncModels",
]

ResponseT = TypeVar("ResponseT", bound=BaseModel)


def _sleep(seconds: float) -> None:
    time.sleep(seconds)


async def _async_sleep(seconds: float) -> None:
    await asyncio.sleep(seconds)


class _Config:
    """两种客户端共用的配置解析。 / Configuration shared by both clients."""

    def __init__(
        self,
        *,
        api_key: str | None,
        base_url: str | None,
        model: str | None,
        retry: RetryPolicy | None,
        timeout: Timeout | None,
        headers: Mapping[str, str] | None,
        transport: Any,
        http_client: Any,
    ) -> None:
        if transport is not None and http_client is not None:
            raise ValueError("transport 与 http_client 不能同时传入 / pass transport or http_client, not both")
        validate_timeout(timeout)
        self.api_key = resolve_api_key(api_key)
        self.base_url = resolve_base_url(base_url)
        self.model = resolve_model(model)
        self.retry = retry if retry is not None else RetryPolicy()
        self.timeout = timeout
        self.headers = default_headers(self.api_key, headers)

    def url(self, path: str) -> str:
        return self.base_url + path

    def request_timeout(self, timeout: Timeout | None) -> Any:
        validate_timeout(timeout)
        if timeout is not None:
            return timeout
        if self.timeout is not None:
            return self.timeout
        return httpx.USE_CLIENT_DEFAULT

    def request_headers(self, extra_headers: Mapping[str, str] | None) -> dict[str, str]:
        headers = dict(self.headers)
        extra = merge_extra_headers(extra_headers)
        if extra:
            headers.update(extra)
        return headers


def _translate_transport_error(exc: httpx.TransportError, timeout: Any) -> XiangxinError:
    if isinstance(exc, httpx.TimeoutException):
        err: XiangxinError = APITimeoutError(f"请求超时 / request timed out: {exc}")
        err.timeout = timeout  # type: ignore[attr-defined]
        return err
    return APIConnectionError(f"连接失败 / connection error: {exc}")


def _next_delay(
    policy: RetryPolicy, error: XiangxinError, attempt: int, deadline: float | None
) -> float | None:
    """返回下一次重试前的等待秒数，``None`` 表示放弃。 / Delay before next retry, or ``None`` to give up."""
    if attempt >= policy.max_retries or not policy.should_retry(error):
        return None
    delay = policy.delay_for(error, attempt)
    if delay is None:
        return None
    if deadline is not None and time.monotonic() + delay >= deadline:
        return None
    return delay


# ===========================================================================
# 同步 / Sync
# ===========================================================================


class XiangxinClient:
    """象信 AI 同步客户端。 / Synchronous client for the 象信 AI API.

    显式参数优先于环境变量；空白的环境变量会被忽略。
    Explicit arguments take precedence over environment variables; blank env values are ignored.

    Args:
        api_key: API 密钥，默认读取 ``XIANGXIN_API_KEY``。 / API key; defaults to ``XIANGXIN_API_KEY``.
        base_url: API 根地址，默认读取 ``XIANGXIN_BASE_URL``，否则 ``https://api.xiangxinai.cn``。
            / API root; defaults to ``XIANGXIN_BASE_URL`` or ``https://api.xiangxinai.cn``.
        model: 默认模型，默认 ``xiangxin-latest``（可用 ``XIANGXIN_DEFAULT_MODEL`` 覆盖）。
            / Default model, ``xiangxin-latest`` unless ``XIANGXIN_DEFAULT_MODEL`` is set.
        retry: 重试策略，传 ``RetryPolicy(max_retries=0)`` 关闭重试。 / Retry policy.
        timeout: 单次 HTTP 操作超时（秒或 ``httpx.Timeout``），默认 30 秒。
            / Per-operation timeout (seconds or ``httpx.Timeout``), default 30s.
        headers: 附加请求头。 / Extra request headers.
        transport: 自定义 ``httpx.BaseTransport``（测试或代理用）。 / Custom transport.
        http_client: 自带的 ``httpx.Client``，与 ``transport`` 互斥；关闭 SDK 客户端时一并关闭。
            / Your own ``httpx.Client``; exclusive with ``transport``; closed with this client.

    Raises:
        XiangxinError: 缺少或非法的 API 密钥、非法超时。 / Missing/invalid API key or timeout.
        ValueError: 同时传入 ``transport`` 与 ``http_client``。 / Both transport and http_client given.

    Example::

        from xiangxin import XiangxinClient, Noul

        with XiangxinClient() as client:
            resp = client.system_one(
                state="我被重复扣费了两次，请尽快处理！",
                questions={"is_billing": Noul(instructions="这是否与扣费相关？")},
            )
            print(resp.answers["is_billing"].noul, resp.usage.input_tokens)
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        retry: RetryPolicy | None = None,
        timeout: Timeout | None = None,
        headers: Mapping[str, str] | None = None,
        transport: httpx.BaseTransport | None = None,
        http_client: httpx.Client | None = None,
    ) -> None:
        self._config = _Config(
            api_key=api_key,
            base_url=base_url,
            model=model,
            retry=retry,
            timeout=timeout,
            headers=headers,
            transport=transport,
            http_client=http_client,
        )
        if http_client is not None:
            self._http = http_client
        else:
            self._http = httpx.Client(
                transport=transport,
                timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
            )
        self.models = Models(self)
        """模型资源：``client.models.list()``。 / Models resource."""
        self.with_raw_response = XiangxinClientWithRawResponse(self)
        """返回原始 HTTP 响应的视图。 / View returning raw HTTP responses."""

    # -- 属性 / properties ---------------------------------------------------

    @property
    def base_url(self) -> str:
        """API 根地址。 / API root URL."""
        return self._config.base_url

    @property
    def model(self) -> str:
        """默认模型。 / Default model."""
        return self._config.model

    @property
    def retry(self) -> RetryPolicy:
        """客户端级重试策略。 / Client-level retry policy."""
        return self._config.retry

    # -- 请求核心 / request core --------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        retry: RetryPolicy | None,
        timeout: Timeout | None,
        extra_headers: Mapping[str, str] | None,
    ) -> httpx.Response:
        policy = retry if retry is not None else self._config.retry
        req_timeout = self._config.request_timeout(timeout)
        headers = self._config.request_headers(extra_headers)
        url = self._config.url(path)
        deadline = time.monotonic() + policy.timeout if policy.timeout is not None else None
        attempt = 0
        while True:
            try:
                return self._send_once(method, url, headers, json_body, req_timeout)
            except XiangxinError as error:
                delay = _next_delay(policy, error, attempt, deadline)
                if delay is None:
                    raise
                logger.warning(
                    "Retrying %s %s in %.2fs (attempt %d/%d) after %s",
                    method, path, delay, attempt + 1, policy.max_retries, error,
                )
                _sleep(delay)
                attempt += 1

    def _send_once(
        self, method: str, url: str, headers: dict[str, str], json_body: Any, timeout: Any
    ) -> httpx.Response:
        logger.debug("Request %s %s headers=%s body=%s", method, url, redact_headers(headers), json_body)
        started = time.monotonic()
        try:
            response = self._http.request(method, url, headers=headers, json=json_body, timeout=timeout)
        except httpx.TransportError as exc:
            raise _translate_transport_error(exc, timeout) from exc
        elapsed_ms = (time.monotonic() - started) * 1000
        log_response(response, elapsed_ms)
        logger.debug("Response headers=%s body=%s", redact_headers(response.headers), response.text)
        if not response.is_success:
            raise make_api_error(response)
        return response

    # -- 公开 API / public API ------------------------------------------------

    def _system_one_raw(
        self,
        state: JSONContent,
        questions: Mapping[str, Question],
        *,
        model: str | None,
        retry: RetryPolicy | None,
        timeout: Timeout | None,
        extra_headers: Mapping[str, str] | None,
        extra_body: Mapping[str, Any] | None,
        response_model: type[Any] | None,
    ) -> RawResponse[Any]:
        body = build_system_one_body(state, questions, model or self._config.model, extra_body)
        response = self._request(
            "POST", SYSTEM_ONE_PATH, json_body=body, retry=retry, timeout=timeout, extra_headers=extra_headers
        )
        return RawResponse(response, response_model or SystemOneResponse)

    @overload
    def system_one(
        self,
        state: JSONContent,
        questions: Mapping[str, Question],
        *,
        model: str | None = None,
        retry: RetryPolicy | None = None,
        timeout: Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        extra_body: Mapping[str, Any] | None = None,
        response_model: None = None,
    ) -> SystemOneResponse: ...

    @overload
    def system_one(
        self,
        state: JSONContent,
        questions: Mapping[str, Question],
        *,
        model: str | None = None,
        retry: RetryPolicy | None = None,
        timeout: Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        extra_body: Mapping[str, Any] | None = None,
        response_model: type[ResponseT],
    ) -> ResponseT: ...

    def system_one(
        self,
        state: JSONContent,
        questions: Mapping[str, Question],
        *,
        model: str | None = None,
        retry: RetryPolicy | None = None,
        timeout: Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        extra_body: Mapping[str, Any] | None = None,
        response_model: type[Any] | None = None,
    ) -> Any:
        """对 ``state`` 提出一组带名字的问题，一次前向返回全部答案。

        Ask named questions about ``state`` and get all answers in one forward pass.

        Args:
            state: 文本、JSON 对象或数组。 / Text, a JSON object, or an array.
            questions: 非空映射：问题名 → ``Noul`` / ``Choice`` / ``Score`` 或等价字典。
                / Non-empty mapping of names to question objects or dicts.
            model: 覆盖客户端默认模型。 / Override the client's default model.
            retry: 仅本次调用生效的重试策略。 / Retry policy for this call only.
            timeout: 仅本次调用生效的超时。 / Timeout for this call only.
            extra_headers: 附加请求头（不能覆盖鉴权头）。 / Extra headers (auth is protected).
            extra_body: 浅合并到请求体顶层的附加字段。 / Extra top-level body fields, shallow-merged.
            response_model: 自定义 pydantic 响应模型。 / Custom pydantic response model.

        Returns:
            ``SystemOneResponse``（或 ``response_model`` 的实例）。
            / ``SystemOneResponse`` or an instance of ``response_model``.

        Raises:
            XiangxinError: 问题为空或格式错误。 / Empty or malformed questions.
            APIError: 重试后服务端仍返回错误（子类见 :mod:`xiangxin.exceptions`）。
                / The server returned an error after any retries.
            APIConnectionError: 重试后仍无法连接或超时。 / Connection failure or timeout after retries.
        """
        raw = self._system_one_raw(
            state,
            questions,
            model=model,
            retry=retry,
            timeout=timeout,
            extra_headers=extra_headers,
            extra_body=extra_body,
            response_model=response_model,
        )
        return raw.parse()

    def close(self) -> None:
        """关闭底层 HTTP 连接（包括传入的 ``http_client``）。

        Close the underlying HTTP client, including a supplied one.
        """
        self._http.close()

    def __enter__(self) -> XiangxinClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()

    def __repr__(self) -> str:
        return f"XiangxinClient(base_url={self.base_url!r}, model={self.model!r})"


class Models:
    """模型资源，通过 ``client.models`` 访问。 / Models resource, reached via ``client.models``."""

    def __init__(self, client: XiangxinClient) -> None:
        self._client = client

    def _list_raw(
        self,
        *,
        retry: RetryPolicy | None,
        timeout: Timeout | None,
        extra_headers: Mapping[str, str] | None,
    ) -> RawResponse[ListModelsResponse]:
        response = self._client._request(
            "GET", MODELS_PATH, retry=retry, timeout=timeout, extra_headers=extra_headers
        )
        return RawResponse(response, ListModelsResponse)

    def list(
        self,
        *,
        retry: RetryPolicy | None = None,
        timeout: Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> ListModelsResponse:
        """列出当前账号可用的模型。 / List the models available to the account."""
        return self._list_raw(retry=retry, timeout=timeout, extra_headers=extra_headers).parse()


class _ModelsWithRawResponse:
    def __init__(self, models: Models) -> None:
        self._models = models

    def list(
        self,
        *,
        retry: RetryPolicy | None = None,
        timeout: Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> RawResponse[ListModelsResponse]:
        """同 ``models.list``，但返回 :class:`RawResponse`。 / Like ``models.list`` but returns a RawResponse."""
        return self._models._list_raw(retry=retry, timeout=timeout, extra_headers=extra_headers)


class XiangxinClientWithRawResponse:
    """``client.with_raw_response``：各方法返回 :class:`RawResponse`，可读取响应头。

    ``client.with_raw_response``: methods return a :class:`RawResponse` exposing headers.

    Example::

        raw = client.with_raw_response.system_one(state, questions)
        print(raw.headers["x-xiangxin-model-ms"])
        resp = raw.parse()
    """

    def __init__(self, client: XiangxinClient) -> None:
        self._client = client
        self.models = _ModelsWithRawResponse(client.models)

    def system_one(
        self,
        state: JSONContent,
        questions: Mapping[str, Question],
        *,
        model: str | None = None,
        retry: RetryPolicy | None = None,
        timeout: Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        extra_body: Mapping[str, Any] | None = None,
        response_model: type[Any] | None = None,
    ) -> RawResponse[Any]:
        """同 ``system_one``，但返回 :class:`RawResponse`。 / Like ``system_one`` but returns a RawResponse."""
        return self._client._system_one_raw(
            state,
            questions,
            model=model,
            retry=retry,
            timeout=timeout,
            extra_headers=extra_headers,
            extra_body=extra_body,
            response_model=response_model,
        )


# ===========================================================================
# 异步 / Async
# ===========================================================================


class AsyncXiangxinClient:
    """象信 AI 异步客户端，参数与 :class:`XiangxinClient` 相同。

    Asynchronous client for the 象信 AI API; same arguments as :class:`XiangxinClient`,
    but ``transport`` / ``http_client`` take their async httpx counterparts.

    Example::

        import asyncio
        from xiangxin import AsyncXiangxinClient, Score

        async def main() -> None:
            async with AsyncXiangxinClient() as client:
                resp = await client.system_one(
                    state="客服回复很慢，我已经等了三天。",
                    questions={"anger": Score(instructions="用户有多生气？", criteria=["平静", "不满", "愤怒"])},
                )
                print(resp.answers["anger"].score)

        asyncio.run(main())
    """

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str | None = None,
        model: str | None = None,
        retry: RetryPolicy | None = None,
        timeout: Timeout | None = None,
        headers: Mapping[str, str] | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        self._config = _Config(
            api_key=api_key,
            base_url=base_url,
            model=model,
            retry=retry,
            timeout=timeout,
            headers=headers,
            transport=transport,
            http_client=http_client,
        )
        if http_client is not None:
            self._http = http_client
        else:
            self._http = httpx.AsyncClient(
                transport=transport,
                timeout=timeout if timeout is not None else DEFAULT_TIMEOUT,
            )
        self.models = AsyncModels(self)
        """模型资源：``await client.models.list()``。 / Models resource."""
        self.with_raw_response = AsyncXiangxinClientWithRawResponse(self)
        """返回原始 HTTP 响应的视图。 / View returning raw HTTP responses."""

    @property
    def base_url(self) -> str:
        """API 根地址。 / API root URL."""
        return self._config.base_url

    @property
    def model(self) -> str:
        """默认模型。 / Default model."""
        return self._config.model

    @property
    def retry(self) -> RetryPolicy:
        """客户端级重试策略。 / Client-level retry policy."""
        return self._config.retry

    async def _request(
        self,
        method: str,
        path: str,
        *,
        json_body: Any = None,
        retry: RetryPolicy | None,
        timeout: Timeout | None,
        extra_headers: Mapping[str, str] | None,
    ) -> httpx.Response:
        policy = retry if retry is not None else self._config.retry
        req_timeout = self._config.request_timeout(timeout)
        headers = self._config.request_headers(extra_headers)
        url = self._config.url(path)
        deadline = time.monotonic() + policy.timeout if policy.timeout is not None else None
        attempt = 0
        while True:
            try:
                return await self._send_once(method, url, headers, json_body, req_timeout)
            except XiangxinError as error:
                delay = _next_delay(policy, error, attempt, deadline)
                if delay is None:
                    raise
                logger.warning(
                    "Retrying %s %s in %.2fs (attempt %d/%d) after %s",
                    method, path, delay, attempt + 1, policy.max_retries, error,
                )
                await _async_sleep(delay)
                attempt += 1

    async def _send_once(
        self, method: str, url: str, headers: dict[str, str], json_body: Any, timeout: Any
    ) -> httpx.Response:
        logger.debug("Request %s %s headers=%s body=%s", method, url, redact_headers(headers), json_body)
        started = time.monotonic()
        try:
            response = await self._http.request(method, url, headers=headers, json=json_body, timeout=timeout)
        except httpx.TransportError as exc:
            raise _translate_transport_error(exc, timeout) from exc
        elapsed_ms = (time.monotonic() - started) * 1000
        log_response(response, elapsed_ms)
        logger.debug("Response headers=%s body=%s", redact_headers(response.headers), response.text)
        if not response.is_success:
            raise make_api_error(response)
        return response

    async def _system_one_raw(
        self,
        state: JSONContent,
        questions: Mapping[str, Question],
        *,
        model: str | None,
        retry: RetryPolicy | None,
        timeout: Timeout | None,
        extra_headers: Mapping[str, str] | None,
        extra_body: Mapping[str, Any] | None,
        response_model: type[Any] | None,
    ) -> RawResponse[Any]:
        body = build_system_one_body(state, questions, model or self._config.model, extra_body)
        response = await self._request(
            "POST", SYSTEM_ONE_PATH, json_body=body, retry=retry, timeout=timeout, extra_headers=extra_headers
        )
        return RawResponse(response, response_model or SystemOneResponse)

    @overload
    async def system_one(
        self,
        state: JSONContent,
        questions: Mapping[str, Question],
        *,
        model: str | None = None,
        retry: RetryPolicy | None = None,
        timeout: Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        extra_body: Mapping[str, Any] | None = None,
        response_model: None = None,
    ) -> SystemOneResponse: ...

    @overload
    async def system_one(
        self,
        state: JSONContent,
        questions: Mapping[str, Question],
        *,
        model: str | None = None,
        retry: RetryPolicy | None = None,
        timeout: Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        extra_body: Mapping[str, Any] | None = None,
        response_model: type[ResponseT],
    ) -> ResponseT: ...

    async def system_one(
        self,
        state: JSONContent,
        questions: Mapping[str, Question],
        *,
        model: str | None = None,
        retry: RetryPolicy | None = None,
        timeout: Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        extra_body: Mapping[str, Any] | None = None,
        response_model: type[Any] | None = None,
    ) -> Any:
        """异步版 :meth:`XiangxinClient.system_one`，参数与返回值相同。

        Async version of :meth:`XiangxinClient.system_one`; same arguments and return value.
        """
        raw = await self._system_one_raw(
            state,
            questions,
            model=model,
            retry=retry,
            timeout=timeout,
            extra_headers=extra_headers,
            extra_body=extra_body,
            response_model=response_model,
        )
        return raw.parse()

    async def aclose(self) -> None:
        """关闭底层 HTTP 连接（包括传入的 ``http_client``）。

        Close the underlying HTTP client, including a supplied one.
        """
        await self._http.aclose()

    async def close(self) -> None:
        """``aclose`` 的别名。 / Alias of ``aclose``."""
        await self.aclose()

    async def __aenter__(self) -> AsyncXiangxinClient:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        await self.aclose()

    def __repr__(self) -> str:
        return f"AsyncXiangxinClient(base_url={self.base_url!r}, model={self.model!r})"


class AsyncModels:
    """异步模型资源，通过 ``client.models`` 访问。 / Async models resource."""

    def __init__(self, client: AsyncXiangxinClient) -> None:
        self._client = client

    async def _list_raw(
        self,
        *,
        retry: RetryPolicy | None,
        timeout: Timeout | None,
        extra_headers: Mapping[str, str] | None,
    ) -> RawResponse[ListModelsResponse]:
        response = await self._client._request(
            "GET", MODELS_PATH, retry=retry, timeout=timeout, extra_headers=extra_headers
        )
        return RawResponse(response, ListModelsResponse)

    async def list(
        self,
        *,
        retry: RetryPolicy | None = None,
        timeout: Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> ListModelsResponse:
        """列出当前账号可用的模型。 / List the models available to the account."""
        raw = await self._list_raw(retry=retry, timeout=timeout, extra_headers=extra_headers)
        return raw.parse()


class _AsyncModelsWithRawResponse:
    def __init__(self, models: AsyncModels) -> None:
        self._models = models

    async def list(
        self,
        *,
        retry: RetryPolicy | None = None,
        timeout: Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> RawResponse[ListModelsResponse]:
        """同 ``models.list``，但返回 :class:`RawResponse`。 / Like ``models.list`` but returns a RawResponse."""
        return await self._models._list_raw(retry=retry, timeout=timeout, extra_headers=extra_headers)


class AsyncXiangxinClientWithRawResponse:
    """异步版 ``with_raw_response``。 / Async ``with_raw_response`` view."""

    def __init__(self, client: AsyncXiangxinClient) -> None:
        self._client = client
        self.models = _AsyncModelsWithRawResponse(client.models)

    async def system_one(
        self,
        state: JSONContent,
        questions: Mapping[str, Question],
        *,
        model: str | None = None,
        retry: RetryPolicy | None = None,
        timeout: Timeout | None = None,
        extra_headers: Mapping[str, str] | None = None,
        extra_body: Mapping[str, Any] | None = None,
        response_model: type[Any] | None = None,
    ) -> RawResponse[Any]:
        """同 ``system_one``，但返回 :class:`RawResponse`。 / Like ``system_one`` but returns a RawResponse."""
        return await self._client._system_one_raw(
            state,
            questions,
            model=model,
            retry=retry,
            timeout=timeout,
            extra_headers=extra_headers,
            extra_body=extra_body,
            response_model=response_model,
        )
