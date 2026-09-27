from __future__ import annotations

import httpx
import pytest
import respx

from xiangxin import (
    APIError,
    APIResponseValidationError,
    AuthenticationError,
    BadRequestError,
    ConflictError,
    InsufficientBalanceError,
    InternalServerError,
    Noul,
    NotFoundError,
    OverloadedError,
    PermissionDeniedError,
    RateLimitError,
    RequestTooLargeError,
    RetryPolicy,
    UnprocessableEntityError,
    XiangxinClient,
    XiangxinError,
)

from .conftest import BASE, SAMPLE_RESPONSE

KEY = "sk-xx-" + "b" * 40
URL = f"{BASE}/v1/systemone"
NO_RETRY = RetryPolicy(max_retries=0)


def make_client(**kwargs) -> XiangxinClient:
    return XiangxinClient(api_key=KEY, base_url=BASE, **kwargs)


@pytest.mark.parametrize(
    ("status", "body", "exc_type"),
    [
        (400, {"detail": "bad_request"}, BadRequestError),
        (401, {"detail": "invalid_api_key"}, AuthenticationError),
        (402, {"detail": "insufficient_balance"}, InsufficientBalanceError),
        (403, {"detail": "forbidden"}, PermissionDeniedError),
        (404, {"detail": "model_not_found"}, NotFoundError),
        (409, {"detail": "reflex_not_ready"}, ConflictError),
        (413, {"detail": "request_too_large"}, RequestTooLargeError),
        (422, {"detail": "Too many choices. Must have at most 255 choices."}, UnprocessableEntityError),
        (429, {"detail": "rate_limited"}, RateLimitError),
        (500, {"detail": "internal"}, InternalServerError),
        (503, None, InternalServerError),
        (529, {"detail": "overloaded"}, OverloadedError),
        (418, {"detail": "teapot"}, APIError),
    ],
)
@respx.mock
def test_status_maps_to_exception(status: int, body, exc_type: type[APIError]) -> None:
    kwargs = {"json": body} if body is not None else {"text": "upstream down"}
    respx.post(URL).respond(status, headers={"x-request-id": "req_err"}, **kwargs)
    with make_client(retry=NO_RETRY) as client:
        with pytest.raises(exc_type) as info:
            client.system_one("s", {"a": Noul()})
    err = info.value
    assert type(err) is exc_type
    assert isinstance(err, APIError) and isinstance(err, XiangxinError)
    assert err.status_code == status == err.status
    assert err.request_id == "req_err"
    assert err.endpoint == f"POST {URL}"
    if body is not None:
        assert err.detail == body["detail"]
        assert body["detail"] in str(err)
    else:
        assert err.body == "upstream down"


def test_hierarchy() -> None:
    from xiangxin import APIConnectionError, APITimeoutError

    for cls in (
        AuthenticationError,
        InsufficientBalanceError,
        NotFoundError,
        UnprocessableEntityError,
        RateLimitError,
        OverloadedError,
        InternalServerError,
    ):
        assert issubclass(cls, APIError)
    assert issubclass(APIError, XiangxinError)
    assert issubclass(APITimeoutError, APIConnectionError)
    assert issubclass(APIConnectionError, XiangxinError)
    assert not issubclass(APIConnectionError, APIError)


@respx.mock
def test_pydantic_style_422_detail() -> None:
    detail = [{"loc": ["body", "questions"], "msg": "field required", "type": "missing"}]
    respx.post(URL).respond(422, json={"detail": detail})
    with make_client() as client:
        with pytest.raises(UnprocessableEntityError) as info:
            client.system_one("s", {"a": Noul()})
    assert info.value.detail == detail


@respx.mock
def test_malformed_success_body() -> None:
    respx.post(URL).respond(200, json={"model": "x", "answers": {"a": {"type": "noul"}}})
    with make_client() as client:
        with pytest.raises(APIResponseValidationError) as info:
            client.system_one("s", {"a": Noul()})
    assert "answers.a" in str(info.value)


# -- 重试 / retries ---------------------------------------------------------------


@respx.mock
def test_retry_on_429_honors_retry_after(sleeps: list[float]) -> None:
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(429, json={"detail": "rate_limited"}, headers={"retry-after": "3"}),
            httpx.Response(429, json={"detail": "rate_limited"}, headers={"retry-after-ms": "250"}),
            httpx.Response(200, json=SAMPLE_RESPONSE),
        ]
    )
    with make_client() as client:
        resp = client.system_one("s", {"a": Noul()})
    assert resp.model == "xiangxin-s1-1.0.0"
    assert route.call_count == 3
    assert sleeps == [3.0, 0.25]


@respx.mock
def test_rate_limit_error_exposes_retry_after(sleeps: list[float]) -> None:
    respx.post(URL).respond(429, json={"detail": "rate_limited"}, headers={"retry-after": "2"})
    with make_client(retry=RetryPolicy(max_retries=1)) as client:
        with pytest.raises(RateLimitError) as info:
            client.system_one("s", {"a": Noul()})
    assert info.value.retry_after == 2.0
    assert sleeps == [2.0]


@respx.mock
def test_retry_on_529_uses_backoff(sleeps: list[float]) -> None:
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(529, json={"detail": "overloaded"}),
            httpx.Response(529, json={"detail": "overloaded"}),
            httpx.Response(200, json=SAMPLE_RESPONSE),
        ]
    )
    policy = RetryPolicy(max_retries=2, backoff_initial=0.5, backoff_jitter=0)
    with make_client(retry=policy) as client:
        client.system_one("s", {"a": Noul()})
    assert route.call_count == 3
    assert sleeps == [0.5, 1.0]


@respx.mock
def test_529_gives_up_after_max_retries(sleeps: list[float]) -> None:
    route = respx.post(URL).respond(529, json={"detail": "overloaded"})
    with make_client() as client:
        with pytest.raises(OverloadedError):
            client.system_one("s", {"a": Noul()})
    assert route.call_count == 3  # 1 + max_retries(2)
    assert len(sleeps) == 2


@pytest.mark.parametrize("status", [400, 401, 402, 404, 422])
@respx.mock
def test_no_retry_on_client_errors(status: int, sleeps: list[float]) -> None:
    route = respx.post(URL).respond(status, json={"detail": "nope"}, headers={"retry-after": "1"})
    with make_client(retry=RetryPolicy(max_retries=5)) as client:
        with pytest.raises(APIError):
            client.system_one("s", {"a": Noul()})
    assert route.call_count == 1
    assert sleeps == []


@respx.mock
def test_per_call_retry_override(sleeps: list[float]) -> None:
    route = respx.post(URL).respond(503)
    with make_client() as client:
        with pytest.raises(InternalServerError):
            client.system_one("s", {"a": Noul()}, retry=NO_RETRY)
    assert route.call_count == 1


@respx.mock
def test_retry_after_beyond_cap_is_not_retried(sleeps: list[float]) -> None:
    route = respx.post(URL).respond(429, headers={"retry-after": "3600"})
    with make_client() as client:
        with pytest.raises(RateLimitError):
            client.system_one("s", {"a": Noul()})
    assert route.call_count == 1


@respx.mock
def test_retry_budget_stops_retries(sleeps: list[float]) -> None:
    route = respx.post(URL).respond(429, headers={"retry-after": "5"})
    with make_client(retry=RetryPolicy(max_retries=3, timeout=4.0)) as client:
        with pytest.raises(RateLimitError):
            client.system_one("s", {"a": Noul()})
    assert route.call_count == 1


def test_connection_errors_are_retried(sleeps: list[float]) -> None:
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            raise httpx.ConnectError("reset", request=request)
        return httpx.Response(200, json={"models": [{"name": "xiangxin-s1-latest", "description": "d"}]})

    with make_client(transport=httpx.MockTransport(handler)) as client:
        assert client.models.list().models[0].name == "xiangxin-s1-latest"
    assert calls["n"] == 2 and len(sleeps) == 1


def test_retry_policy_accepts_plain_set_and_validates() -> None:
    policy = RetryPolicy(retry_statuses={429})
    assert policy.retry_statuses == frozenset({429})
    with pytest.raises(ValueError):
        RetryPolicy(max_retries=-1)
    with pytest.raises(ValueError):
        RetryPolicy(backoff_jitter=2)
