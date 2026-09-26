"""同步 / 异步客户端共享的纯逻辑（无 I/O）。

I/O-free logic shared by the sync and async clients.
"""

from __future__ import annotations

import json
import os
from collections.abc import Mapping, Sequence
from urllib.parse import quote
from typing import Any, Generic, TypeVar, Union

import httpx
from pydantic import BaseModel, ValidationError

from ._logging import logger
from ._version import __version__
from .constants import API_KEY_ENV, BASE_URL_ENV, DEFAULT_BASE_URL, DEFAULT_MODEL, DEFAULT_MODEL_ENV, REQUEST_ID_HEADER
from .exceptions import APIError, APIResponseValidationError, XiangxinError, error_class_for_status
from .types import XiangxinResponse, _Question

T = TypeVar("T", bound=BaseModel)

Timeout = Union[float, httpx.Timeout]

SYSTEM_ONE_PATH = "/v1/systemone"
MODELS_PATH = "/v1/models"
REFLEXES_PATH = "/v1/reflexes"
USER_AGENT = f"xiangxin-python/{__version__}"


def _env(name: str) -> str | None:
    value = os.environ.get(name)
    if value is None or not value.strip():
        return None
    return value.strip()


def resolve_api_key(api_key: str | None) -> str:
    """校验并返回 API 密钥；显式传入的空字符串不会回退到环境变量。

    Validate and return the API key. An explicit empty key does not fall back to the env.
    """
    key = api_key if api_key is not None else _env(API_KEY_ENV)
    if key is None:
        raise XiangxinError(
            f"缺少 API 密钥：请传入 api_key 或设置环境变量 {API_KEY_ENV}。"
            f" / Missing API key: pass api_key or set {API_KEY_ENV}."
        )
    key = key.strip()
    if not key:
        raise XiangxinError("API 密钥为空。 / The API key is empty.")
    if any(ch.isspace() or ord(ch) < 0x21 or ord(ch) > 0x7E for ch in key):
        raise XiangxinError(
            "API 密钥包含空白、控制字符或非 ASCII 字符。"
            " / The API key contains whitespace, control or non-ASCII characters."
        )
    return key


def resolve_base_url(base_url: str | None) -> str:
    url = base_url if base_url is not None else (_env(BASE_URL_ENV) or DEFAULT_BASE_URL)
    url = url.strip().rstrip("/")
    if not url.startswith(("http://", "https://")):
        raise XiangxinError(f"base_url 必须以 http:// 或 https:// 开头 / invalid base_url: {url!r}")
    return url


def resolve_model(model: str | None) -> str:
    return model if model is not None else (_env(DEFAULT_MODEL_ENV) or DEFAULT_MODEL)


def validate_timeout(timeout: Timeout | None) -> None:
    if timeout is None or isinstance(timeout, httpx.Timeout):
        return
    if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or timeout <= 0:
        raise XiangxinError(f"timeout 必须是正数或 httpx.Timeout / invalid timeout: {timeout!r}")


def default_headers(api_key: str, extra: Mapping[str, str] | None) -> dict[str, str]:
    headers = {"User-Agent": USER_AGENT}
    if extra:
        headers.update(extra)
    # 鉴权与 Accept 不允许被覆盖 / Auth and Accept are protected.
    headers["Authorization"] = f"Bearer {api_key}"
    headers["Accept"] = "application/json"
    return headers


def merge_extra_headers(extra_headers: Mapping[str, str] | None) -> dict[str, str] | None:
    if not extra_headers:
        return None
    return {k: v for k, v in extra_headers.items() if k.lower() not in {"authorization", "accept"}}


def serialize_question(name: str, question: Any) -> dict[str, Any]:
    """把问题对象或字典转成请求体中的字典。 / Turn a question object or dict into its wire dict."""
    if isinstance(question, _Question):
        return question.to_dict()
    if isinstance(question, Mapping):
        data = dict(question)
        kind = data.get("type")
        if not isinstance(kind, str) or not kind:
            raise XiangxinError(f"问题 {name!r} 缺少 type 字段 / question {name!r} is missing 'type'")
        if kind in ("choice", "score") and not data.get("criteria"):
            raise XiangxinError(f"{kind} 问题 {name!r} 的 criteria 不能为空 / {kind} question {name!r} needs criteria")
        return data
    raise XiangxinError(
        f"问题 {name!r} 必须是 Noul/Choice/Score 或字典，得到 {type(question).__name__}"
        f" / question {name!r} must be Noul/Choice/Score or a dict"
    )


def build_system_one_body(
    state: Any,
    questions: Mapping[str, Any],
    model: str,
    extra_body: Mapping[str, Any] | None,
) -> dict[str, Any]:
    if state is None:
        raise XiangxinError("state 不能为 None / state must not be None")
    if not isinstance(questions, Mapping) or not questions:
        raise XiangxinError("questions 必须是非空映射 / questions must be a non-empty mapping")
    body: dict[str, Any] = {
        "state": state,
        "model": model,
        "questions": {name: serialize_question(name, q) for name, q in questions.items()},
    }
    if extra_body:
        body.update(extra_body)
    return body


def reflex_path(name: str, suffix: str = "") -> str:
    """``/v1/reflexes/{name}{suffix}``，名字做 URL 转义。 / Reflex URL path with the name escaped."""
    if not isinstance(name, str) or not name:
        raise XiangxinError("反射名不能为空 / reflex name must be a non-empty string")
    return f"{REFLEXES_PATH}/{quote(name, safe='')}{suffix}"


def build_reflex_body(
    name: str,
    questions: Mapping[str, Any],
    examples: Sequence[Mapping[str, Any]],
    description: str | None,
    extra_body: Mapping[str, Any] | None,
) -> dict[str, Any]:
    """构造 ``POST /v1/reflexes`` 的请求体；条数与名字格式由服务端校验。

    Build the ``POST /v1/reflexes`` body; counts and name format are validated server-side.
    """
    if not isinstance(name, str) or not name:
        raise XiangxinError("反射名不能为空 / reflex name must be a non-empty string")
    if not isinstance(questions, Mapping) or not questions:
        raise XiangxinError("questions 必须是非空映射 / questions must be a non-empty mapping")
    if isinstance(examples, (str, bytes)) or not isinstance(examples, Sequence) or not examples:
        raise XiangxinError("examples 必须是非空列表 / examples must be a non-empty list")
    wire_examples: list[dict[str, Any]] = []
    for i, example in enumerate(examples):
        if not isinstance(example, Mapping) or "state" not in example or not isinstance(example.get("answers"), Mapping):
            raise XiangxinError(
                f"第 {i} 条样本须为 {{state, answers}} 字典 / example {i} must be a dict with state and answers"
            )
        wire_examples.append({**example, "answers": dict(example["answers"])})
    body: dict[str, Any] = {
        "name": name,
        "questions": {qname: serialize_question(qname, q) for qname, q in questions.items()},
        "examples": wire_examples,
    }
    if description is not None:
        body["description"] = description
    if extra_body:
        body.update(extra_body)
    return body


def endpoint_of(request: httpx.Request) -> str:
    url = request.url.copy_with(query=None, fragment=None)
    return f"{request.method} {url}"


def make_api_error(response: httpx.Response) -> APIError:
    """根据响应状态码构造对应的异常。 / Build the exception matching the response status."""
    body: Any
    try:
        body = response.json() if response.content else None
    except (json.JSONDecodeError, UnicodeDecodeError):
        body = response.text
    detail = body.get("detail") if isinstance(body, dict) else body
    if detail is None:
        message = response.reason_phrase or "HTTP error"
    elif isinstance(detail, str):
        message = detail
    else:
        message = json.dumps(detail, ensure_ascii=False)
    cls = error_class_for_status(response.status_code)
    return cls(
        message,
        status_code=response.status_code,
        body=body,
        headers=response.headers,
        endpoint=endpoint_of(response.request),
    )


def parse_response(response: httpx.Response, cls: type[T]) -> T:
    """把成功响应解析为 ``cls``，结构不符时抛 ``APIResponseValidationError``。

    Parse a successful response into ``cls``; raise ``APIResponseValidationError`` on mismatch.
    """
    endpoint = endpoint_of(response.request)
    try:
        payload = response.json()
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise APIResponseValidationError(
            f"响应不是合法 JSON / response is not valid JSON: {exc}",
            status_code=response.status_code,
            body=response.text,
            headers=response.headers,
            endpoint=endpoint,
        ) from exc
    try:
        parsed = cls.model_validate(payload)
    except ValidationError as exc:
        err = exc.errors()[0] if exc.errors() else {}
        path = ".".join(str(p) for p in err.get("loc", ()))
        raise APIResponseValidationError(
            f"响应结构不符 / response did not match {cls.__name__}: {path}: {err.get('msg', exc)}",
            status_code=response.status_code,
            body=payload,
            headers=response.headers,
            endpoint=endpoint,
        ) from exc
    if isinstance(parsed, XiangxinResponse):
        parsed._http_response = response
    return parsed


def log_response(response: httpx.Response, elapsed_ms: float) -> None:
    logger.info(
        "%s %s -> %d in %.0fms (request_id=%s)",
        response.request.method,
        response.request.url.path,
        response.status_code,
        elapsed_ms,
        response.headers.get(REQUEST_ID_HEADER),
    )


class RawResponse(Generic[T]):
    """``with_raw_response`` 返回的原始响应包装，可按需调用 :meth:`parse`。

    Raw response wrapper returned by ``with_raw_response``; call :meth:`parse`
    to get the typed model.
    """

    def __init__(self, http_response: httpx.Response, cls: type[T]) -> None:
        self.http_response = http_response
        self._cls = cls
        self._parsed: T | None = None

    @property
    def status_code(self) -> int:
        """HTTP 状态码。 / HTTP status code."""
        return self.http_response.status_code

    @property
    def headers(self) -> httpx.Headers:
        """响应头。 / Response headers."""
        return self.http_response.headers

    @property
    def request_id(self) -> str | None:
        """``x-request-id`` 响应头。 / The ``x-request-id`` header."""
        return self.http_response.headers.get(REQUEST_ID_HEADER)

    def json(self) -> Any:
        """原始 JSON 响应体。 / Raw JSON body."""
        return self.http_response.json()

    def parse(self) -> T:
        """解析为带类型的响应模型（结果会缓存）。 / Parse into the typed model (cached)."""
        if self._parsed is None:
            self._parsed = parse_response(self.http_response, self._cls)
        return self._parsed

    def __repr__(self) -> str:
        return f"<RawResponse [{self.status_code}] {self._cls.__name__}>"
