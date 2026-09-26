from __future__ import annotations

import json
from typing import Any

import httpx
import pytest
import respx

from xiangxin import (
    REFLEX_MODEL,
    S1_MODEL,
    APITimeoutError,
    AsyncXiangxinClient,
    Choice,
    ConflictError,
    InternalServerError,
    Noul,
    NotFoundError,
    RawResponse,
    Reflex,
    RequestTooLargeError,
    RetryPolicy,
    Score,
    UnprocessableEntityError,
    WaitTimeoutError,
    XiangxinClient,
    XiangxinError,
    constants,
    reflex_model,
)

from .conftest import BASE, SAMPLE_RESPONSE

KEY = "sk-xx-" + "d" * 40
URL = f"{BASE}/v1/reflexes"

QUESTIONS = {
    "department": Choice(instructions="分派部门", criteria={"billing": "扣费、退款", "technical": None}),
    "is_urgent": Noul(instructions="是否紧急？"),
    "anger": {"type": "score", "criteria": ["平静", "不满", "愤怒"]},
}
EXAMPLES = [
    {"state": f"第 {i} 张工单：我被重复扣费了", "answers": {"department": "billing", "is_urgent": i % 2 == 0, "anger": 1}}
    for i in range(10)
]

METRICS = {
    "examples": 1200,
    "train_examples": 960,
    "val_examples": 240,
    "evaluated_on": "val",
    "epochs": 6.0,
    "duration_s": 95.2,
    "before": {"accuracy": 0.61, "log_loss": 0.93, "ece": 0.12, "per_question": {"department": {"accuracy": 0.58, "n": 240}}},
    "after": {"accuracy": 0.97, "log_loss": 0.09, "ece": 0.02, "per_question": {"department": {"accuracy": 0.97, "n": 240}}},
}


def reflex(status: str = "queued", **overrides: Any) -> dict[str, Any]:
    data: dict[str, Any] = {
        "id": "rf_abc123",
        "name": "ticket-router",
        "model": "xiangxin-reflex:ticket-router",
        "description": "",
        "status": status,
        "usable": status == "ready",
        "progress": 1.0 if status == "ready" else 0.0,
        "stage": status,
        "questions": {"department": {"type": "choice", "criteria": {"billing": None, "technical": None}}},
        "examples": 1200,
        "metrics": METRICS if status == "ready" else None,
        "error": None,
        "created_at": "2026-09-25T10:00:00Z",
        "updated_at": "2026-09-25T10:00:00Z",
        "trained_at": "2026-09-25T10:02:00Z" if status == "ready" else None,
    }
    data.update(overrides)
    return data


def make_client(**kwargs: Any) -> XiangxinClient:
    return XiangxinClient(api_key=KEY, base_url=BASE, **kwargs)


def make_async_client(**kwargs: Any) -> AsyncXiangxinClient:
    return AsyncXiangxinClient(api_key=KEY, base_url=BASE, **kwargs)


# -- 常量 / constants -------------------------------------------------------------


def test_model_constants() -> None:
    assert S1_MODEL == constants.S1_MODEL == "xiangxin-s1"
    assert REFLEX_MODEL == constants.REFLEX_MODEL == "xiangxin-reflex"
    assert reflex_model("ticket-router") == "xiangxin-reflex:ticket-router"
    for bad in ("", "Ticket", "-x", "a_b", "a" * 64, "中文"):
        with pytest.raises(ValueError):
            reflex_model(bad)


@respx.mock
def test_system_one_with_reflex_model() -> None:
    route = respx.post(f"{BASE}/v1/systemone").respond(200, json={**SAMPLE_RESPONSE, "model": "xiangxin-reflex:ticket-router"})
    with make_client() as client:
        resp = client.system_one("s", {"a": Noul()}, model=reflex_model("ticket-router"))
    assert json.loads(route.calls.last.request.content)["model"] == "xiangxin-reflex:ticket-router"
    assert resp.model == "xiangxin-reflex:ticket-router"


@respx.mock
def test_reflex_not_ready_is_conflict_and_not_retried() -> None:
    route = respx.post(f"{BASE}/v1/systemone").respond(409, json={"detail": "reflex_not_ready"})
    with make_client() as client:
        with pytest.raises(ConflictError) as info:
            client.system_one("s", {"a": Noul()}, model=reflex_model("ticket-router"))
    assert info.value.detail == "reflex_not_ready"
    assert route.call_count == 1


# -- create -------------------------------------------------------------------


@respx.mock
def test_create_body_and_parsing() -> None:
    route = respx.post(URL).respond(200, json=reflex("queued", queue_position=2), headers={"x-request-id": "req_rf"})
    with make_client() as client:
        r = client.reflexes.create("ticket-router", QUESTIONS, EXAMPLES, description="工单分流")
    body = json.loads(route.calls.last.request.content)
    assert body["name"] == "ticket-router"
    assert body["description"] == "工单分流"
    assert body["questions"] == {
        "department": {"type": "choice", "instructions": "分派部门", "criteria": {"billing": "扣费、退款", "technical": None}},
        "is_urgent": {"type": "noul", "instructions": "是否紧急？"},
        "anger": {"type": "score", "criteria": ["平静", "不满", "愤怒"]},
    }
    assert body["examples"][0] == {"state": "第 0 张工单：我被重复扣费了", "answers": {"department": "billing", "is_urgent": True, "anger": 1}}
    assert len(body["examples"]) == 10
    assert "model" not in body
    assert isinstance(r, Reflex)
    assert r.status == "queued" and not r.done and not r.usable
    assert r.queue_position == 2
    assert r.model == "xiangxin-reflex:ticket-router"
    assert r.metrics is None
    assert r.request_id == "req_rf"


@respx.mock
def test_create_omits_description_by_default() -> None:
    route = respx.post(URL).respond(200, json=reflex())
    with make_client() as client:
        client.reflexes.create("ticket-router", QUESTIONS, EXAMPLES, extra_body={"x": 1})
    body = json.loads(route.calls.last.request.content)
    assert "description" not in body
    assert body["x"] == 1


def test_create_validates_locally() -> None:
    with make_client() as client:
        with pytest.raises(XiangxinError):
            client.reflexes.create("r", {}, EXAMPLES)
        with pytest.raises(XiangxinError):
            client.reflexes.create("r", QUESTIONS, [])
        with pytest.raises(XiangxinError):
            client.reflexes.create("r", QUESTIONS, "not a list")  # type: ignore[arg-type]
        with pytest.raises(XiangxinError):
            client.reflexes.create("r", QUESTIONS, [{"state": "s"}])  # type: ignore[list-item]
        with pytest.raises(XiangxinError):
            client.reflexes.create("r", {"a": {"type": "choice"}}, EXAMPLES)
        with pytest.raises(XiangxinError):
            client.reflexes.create("", QUESTIONS, EXAMPLES)


@pytest.mark.parametrize(
    ("status", "detail", "exc_type"),
    [
        (409, "reflex_busy", ConflictError),
        (409, "too_many_reflexes: at most 20", ConflictError),
        (422, "too_few_examples: at least 10", UnprocessableEntityError),
        (422, "invalid_reflex_name", UnprocessableEntityError),
        (413, "request_too_large", RequestTooLargeError),
    ],
)
@respx.mock
def test_create_errors_not_retried(sleeps: list[float], status: int, detail: str, exc_type: type) -> None:
    route = respx.post(URL).respond(status, json={"detail": detail})
    with make_client() as client:
        with pytest.raises(exc_type) as info:
            client.reflexes.create("ticket-router", QUESTIONS, EXAMPLES)
    assert info.value.detail == detail
    assert route.call_count == 1
    assert sleeps == []


@respx.mock
def test_create_retries_trainer_unavailable(sleeps: list[float]) -> None:
    route = respx.post(URL).mock(
        side_effect=[httpx.Response(503, json={"detail": "trainer_unavailable"}), httpx.Response(200, json=reflex())]
    )
    with make_client() as client:
        r = client.reflexes.create("ticket-router", QUESTIONS, EXAMPLES)
    assert r.status == "queued"
    assert route.call_count == 2
    assert len(sleeps) == 1


@respx.mock
def test_create_does_not_retry_timeouts_by_default(sleeps: list[float]) -> None:
    route = respx.post(URL).mock(side_effect=httpx.ReadTimeout("slow"))
    with make_client() as client:
        with pytest.raises(APITimeoutError):
            client.reflexes.create("ticket-router", QUESTIONS, EXAMPLES)
        assert route.call_count == 1
        # 显式传入的策略照常生效 / an explicit policy is honored
        with pytest.raises(APITimeoutError):
            client.reflexes.create("ticket-router", QUESTIONS, EXAMPLES, retry=RetryPolicy(max_retries=1))
    assert route.call_count == 3


def _timeout_of(request: httpx.Request) -> dict[str, float]:
    return request.extensions["timeout"]


@respx.mock
def test_create_uses_longer_timeout() -> None:
    route = respx.post(URL).respond(200, json=reflex())
    with make_client() as client:
        client.reflexes.create("ticket-router", QUESTIONS, EXAMPLES)
        assert _timeout_of(route.calls.last.request)["read"] == constants.REFLEX_CREATE_TIMEOUT
        client.reflexes.create("ticket-router", QUESTIONS, EXAMPLES, timeout=12.0)
        assert _timeout_of(route.calls.last.request)["read"] == 12.0
    with make_client(timeout=600.0) as client:
        client.reflexes.create("ticket-router", QUESTIONS, EXAMPLES)
        assert _timeout_of(route.calls.last.request)["read"] == 600.0
    with make_client(timeout=5.0) as client:
        client.reflexes.create("ticket-router", QUESTIONS, EXAMPLES)
        assert _timeout_of(route.calls.last.request)["read"] == constants.REFLEX_CREATE_TIMEOUT


# -- list / get / cancel / delete --------------------------------------------------


@respx.mock
def test_list_get_cancel_delete() -> None:
    respx.get(URL).respond(200, json={"reflexes": [reflex("ready"), reflex("training", name="spam", id="rf_2")]})
    respx.get(f"{URL}/ticket-router").respond(200, json=reflex("ready"))
    cancel = respx.post(f"{URL}/ticket-router/cancel").respond(200, json=reflex("cancelled"))
    delete = respx.delete(f"{URL}/ticket-router").respond(200, json={"ok": True})
    with make_client() as client:
        items = client.reflexes.list()
        assert [r.name for r in items] == ["ticket-router", "spam"]
        assert all(isinstance(r, Reflex) for r in items)
        r = client.reflexes.get("ticket-router")
        assert r.done and r.usable
        assert r.metrics is not None and r.metrics.after is not None and r.metrics.before is not None
        assert r.metrics.after.accuracy == 0.97
        assert r.metrics.before.log_loss == 0.93
        assert r.metrics.after.per_question["department"].n == 240
        assert r.metrics.evaluated_on == "val"
        assert client.reflexes.cancel("ticket-router").status == "cancelled"
        assert client.reflexes.delete("ticket-router") is None
    assert cancel.call_count == 1 and delete.call_count == 1


@respx.mock
def test_get_not_found() -> None:
    respx.get(f"{URL}/nope").respond(404, json={"detail": "reflex_not_found"})
    with make_client() as client:
        with pytest.raises(NotFoundError) as info:
            client.reflexes.get("nope")
    assert info.value.detail == "reflex_not_found"


@respx.mock
def test_name_is_url_escaped() -> None:
    route = respx.get(f"{URL}/a%2Fb").respond(200, json=reflex(name="a/b"))
    with make_client() as client:
        client.reflexes.get("a/b")
    assert route.call_count == 1


def test_tolerant_parsing() -> None:
    minimal = Reflex.model_validate({"id": "rf_1", "name": "x", "status": "weird", "new_field": 1})
    assert minimal.usable is False and minimal.metrics is None and minimal.questions == {}
    assert not minimal.done
    partial = Reflex.model_validate(
        reflex("ready", metrics={"after": {"accuracy": 0.9, "future": True}, "something": "new"})
    )
    assert partial.metrics is not None and partial.metrics.after is not None
    assert partial.metrics.after.accuracy == 0.9
    assert partial.metrics.after.ece is None and partial.metrics.after.per_question == {}
    assert partial.metrics.before is None


@respx.mock
def test_with_raw_response() -> None:
    respx.get(f"{URL}/ticket-router").respond(200, json=reflex("ready"), headers={"x-request-id": "req_raw"})
    respx.get(URL).respond(200, json={"reflexes": []})
    with make_client() as client:
        raw = client.with_raw_response.reflexes.get("ticket-router")
        assert isinstance(raw, RawResponse)
        assert raw.request_id == "req_raw"
        assert raw.parse().status == "ready"
        assert client.with_raw_response.reflexes.list().parse().reflexes == []


# -- wait ----------------------------------------------------------------------------


@respx.mock
def test_wait_polls_until_final(sleeps: list[float]) -> None:
    route = respx.get(f"{URL}/ticket-router").mock(
        side_effect=[
            httpx.Response(200, json=reflex("queued")),
            httpx.Response(200, json=reflex("training", progress=0.5)),
            httpx.Response(200, json=reflex("ready")),
        ]
    )
    with make_client() as client:
        r = client.reflexes.wait("ticket-router", poll_interval=0.5)
    assert r.status == "ready"
    assert route.call_count == 3
    assert sleeps == [0.5, 0.5]


@respx.mock
def test_wait_returns_failed_without_raising(sleeps: list[float]) -> None:
    respx.get(f"{URL}/ticket-router").respond(200, json=reflex("failed", error="job_lost"))
    with make_client() as client:
        r = client.reflexes.wait("ticket-router")
    assert r.status == "failed" and r.error == "job_lost"
    assert sleeps == []


@respx.mock
def test_wait_timeout(sleeps: list[float]) -> None:
    respx.get(f"{URL}/ticket-router").respond(200, json=reflex("training"))
    with make_client() as client:
        with pytest.raises(WaitTimeoutError) as info:
            client.reflexes.wait("ticket-router", timeout=0)
        with pytest.raises(XiangxinError):
            client.reflexes.wait("ticket-router", poll_interval=0)
    assert isinstance(info.value, TimeoutError)
    assert info.value.reflex.status == "training"


@respx.mock
def test_wait_propagates_errors_after_retries(sleeps: list[float]) -> None:
    respx.get(f"{URL}/ticket-router").respond(500, json={"detail": "internal"})
    with make_client() as client:
        with pytest.raises(InternalServerError):
            client.reflexes.wait("ticket-router")
    assert len(sleeps) == 2  # 两次重试退避，无轮询等待 / two retry backoffs, no poll sleep


# -- async -----------------------------------------------------------------------------


@respx.mock
async def test_async_reflexes(sleeps: list[float]) -> None:
    create = respx.post(URL).respond(200, json=reflex("queued"))
    respx.get(URL).respond(200, json={"reflexes": [reflex("queued")]})
    respx.get(f"{URL}/ticket-router").mock(
        side_effect=[httpx.Response(200, json=reflex("training")), httpx.Response(200, json=reflex("ready"))]
    )
    respx.post(f"{URL}/ticket-router/cancel").respond(200, json=reflex("cancelled"))
    delete = respx.delete(f"{URL}/ticket-router").respond(200, json={"ok": True})
    async with make_async_client() as client:
        r = await client.reflexes.create(
            "ticket-router", {"d": Choice(criteria={"a": None, "b": None}), "s": Score(criteria=["x", "y"])}, EXAMPLES
        )
        assert r.status == "queued"
        assert _timeout_of(create.calls.last.request)["read"] == constants.REFLEX_CREATE_TIMEOUT
        assert [x.name for x in await client.reflexes.list()] == ["ticket-router"]
        done = await client.reflexes.wait("ticket-router", poll_interval=1.0)
        assert done.status == "ready" and done.metrics is not None
        assert (await client.reflexes.cancel("ticket-router")).status == "cancelled"
        assert await client.reflexes.delete("ticket-router") is None
        raw = await client.with_raw_response.reflexes.create("ticket-router", {"n": Noul()}, EXAMPLES)
        assert raw.parse().name == "ticket-router"
    assert sleeps == [1.0]
    assert delete.call_count == 1
    body = json.loads(create.calls[0].request.content)
    assert body["questions"]["s"] == {"type": "score", "criteria": ["x", "y"]}


@respx.mock
async def test_async_create_conflict_not_retried(sleeps: list[float]) -> None:
    route = respx.post(URL).respond(409, json={"detail": "reflex_busy"})
    async with make_async_client() as client:
        with pytest.raises(ConflictError):
            await client.reflexes.create("ticket-router", QUESTIONS, EXAMPLES)
    assert route.call_count == 1 and sleeps == []


@respx.mock
async def test_async_wait_timeout(sleeps: list[float]) -> None:
    respx.get(f"{URL}/ticket-router").respond(200, json=reflex("queued"))
    async with make_async_client() as client:
        with pytest.raises(WaitTimeoutError):
            await client.reflexes.wait("ticket-router", timeout=0)
