from __future__ import annotations

import json

import httpx
import pytest
import respx

from xiangxin import (
    AsyncXiangxinClient,
    Choice,
    InsufficientBalanceError,
    Noul,
    OverloadedError,
    RateLimitError,
    RetryPolicy,
    Score,
    SystemOneResponse,
    UnprocessableEntityError,
)

from .conftest import BASE, SAMPLE_HEADERS, SAMPLE_RESPONSE

KEY = "sk-xx-" + "c" * 40
URL = f"{BASE}/v1/systemone"


def make_client(**kwargs) -> AsyncXiangxinClient:
    return AsyncXiangxinClient(api_key=KEY, base_url=BASE, **kwargs)


@respx.mock
async def test_async_system_one_body_and_parsing() -> None:
    route = respx.post(URL).respond(200, json=SAMPLE_RESPONSE, headers=SAMPLE_HEADERS)
    async with make_client() as client:
        resp = await client.system_one(
            state="退款还没到账",
            questions={
                "is_urgent": Noul(instructions="紧急？"),
                "department": {"type": "choice", "criteria": {"billing": None, "technical": None}},
                "frustration": Score(criteria=["平静", "不满", "非常愤怒"]),
            },
        )
    body = json.loads(route.calls.last.request.content)
    assert body["model"] == "xiangxin-latest"
    assert body["questions"]["department"] == {"type": "choice", "criteria": {"billing": None, "technical": None}}
    assert body["questions"]["is_urgent"] == {"type": "noul", "instructions": "紧急？"}
    assert isinstance(resp, SystemOneResponse)
    assert resp.answers["is_urgent"].noul == 0.95
    assert resp.answers["department"].choice == "billing"
    assert resp.answers["frustration"].probabilities[1] == 0.95
    assert resp.usage.input_tokens == 296
    assert resp.request_id == "req_123"


@respx.mock
async def test_async_dict_vs_class_equivalent() -> None:
    route = respx.post(URL).respond(200, json=SAMPLE_RESPONSE)
    async with make_client() as client:
        await client.system_one("s", {"c": Choice(instructions="i", criteria={"a": "x", "b": None})})
        await client.system_one("s", {"c": {"type": "choice", "instructions": "i", "criteria": {"a": "x", "b": None}}})
    assert json.loads(route.calls[0].request.content) == json.loads(route.calls[1].request.content)


@respx.mock
async def test_async_models_and_raw() -> None:
    respx.get(f"{BASE}/v1/models").respond(200, json={"models": [{"name": "xiangxin-latest", "description": "d"}]})
    respx.post(URL).respond(200, json=SAMPLE_RESPONSE, headers=SAMPLE_HEADERS)
    async with make_client() as client:
        models = await client.models.list()
        assert models.models[0].name == "xiangxin-latest"
        raw = await client.with_raw_response.system_one("s", {"a": Noul()})
        assert raw.headers["x-xiangxin-total-ms"] == "71"
        assert raw.parse().model == "xiangxin-1.0.0"
        raw_models = await client.with_raw_response.models.list()
        assert raw_models.status_code == 200


@pytest.mark.parametrize(
    ("status", "exc_type"),
    [(402, InsufficientBalanceError), (422, UnprocessableEntityError), (529, OverloadedError)],
)
@respx.mock
async def test_async_errors(status: int, exc_type: type, sleeps: list[float]) -> None:
    respx.post(URL).respond(status, json={"detail": "x"})
    async with make_client(retry=RetryPolicy(max_retries=0)) as client:
        with pytest.raises(exc_type):
            await client.system_one("s", {"a": Noul()})


@respx.mock
async def test_async_retry_429_then_529(sleeps: list[float]) -> None:
    route = respx.post(URL).mock(
        side_effect=[
            httpx.Response(429, json={"detail": "rate_limited"}, headers={"retry-after": "1.5"}),
            httpx.Response(529, json={"detail": "overloaded"}),
            httpx.Response(200, json=SAMPLE_RESPONSE),
        ]
    )
    async with make_client(retry=RetryPolicy(max_retries=2, backoff_initial=0.2, backoff_jitter=0)) as client:
        resp = await client.system_one("s", {"a": Noul()})
    assert resp.answers["is_urgent"].noul == 0.95
    assert route.call_count == 3
    assert sleeps == [1.5, 0.4]


@respx.mock
async def test_async_no_retry_on_422(sleeps: list[float]) -> None:
    route = respx.post(URL).respond(422, json={"detail": "max_tokens_exceeded"})
    async with make_client() as client:
        with pytest.raises(UnprocessableEntityError):
            await client.system_one("s", {"a": Noul()})
    assert route.call_count == 1 and sleeps == []


@respx.mock
async def test_async_rate_limit_exhausted(sleeps: list[float]) -> None:
    route = respx.post(URL).respond(429, headers={"retry-after": "0"})
    async with make_client() as client:
        with pytest.raises(RateLimitError):
            await client.system_one("s", {"a": Noul()})
    assert route.call_count == 3 and sleeps == [0.0, 0.0]


async def test_async_timeout_mapping() -> None:
    from xiangxin import APITimeoutError

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("slow", request=request)

    async with make_client(transport=httpx.MockTransport(handler), retry=RetryPolicy(max_retries=0)) as client:
        with pytest.raises(APITimeoutError):
            await client.system_one("s", {"a": Noul()})
