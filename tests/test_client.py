from __future__ import annotations

import json

import httpx
import pytest
import respx

from xiangxin import (
    ChoiceAnswer,
    ListModelsResponse,
    Noul,
    NoulAnswer,
    RawResponse,
    Score,
    SystemOneResponse,
    XiangxinClient,
    XiangxinError,
)
from xiangxin import Choice

from .conftest import BASE, SAMPLE_HEADERS, SAMPLE_RESPONSE

KEY = "sk-xx-" + "a" * 40


def make_client(**kwargs):
    kwargs.setdefault("api_key", KEY)
    kwargs.setdefault("base_url", BASE)
    return XiangxinClient(**kwargs)


def body_of(route: respx.Route, index: int = -1) -> dict:
    return json.loads(route.calls[index].request.content)


# -- 配置 / configuration -----------------------------------------------------


def test_env_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("XIANGXIN_API_KEY", f"  {KEY}\n")
    client = XiangxinClient()
    assert client.base_url == "https://api.xiangxinai.cn"
    assert client.model == "xiangxin-latest"
    monkeypatch.setenv("XIANGXIN_BASE_URL", BASE + "/")
    monkeypatch.setenv("XIANGXIN_DEFAULT_MODEL", "xiangxin-preview")
    client = XiangxinClient()
    assert client.base_url == BASE
    assert client.model == "xiangxin-preview"
    # 显式参数优先 / explicit wins
    assert XiangxinClient(model="xiangxin-1.0.0").model == "xiangxin-1.0.0"


def test_missing_or_invalid_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    with pytest.raises(XiangxinError):
        XiangxinClient()
    with pytest.raises(XiangxinError):
        XiangxinClient(api_key="bad key")
    with pytest.raises(XiangxinError):
        XiangxinClient(api_key="密钥")
    monkeypatch.setenv("XIANGXIN_API_KEY", KEY)
    with pytest.raises(XiangxinError):
        XiangxinClient(api_key="")  # 显式空值不回退 / explicit empty does not fall back


def test_transport_and_http_client_exclusive() -> None:
    with pytest.raises(ValueError):
        make_client(transport=httpx.MockTransport(lambda r: httpx.Response(200)), http_client=httpx.Client())


# -- 请求体 / request body ------------------------------------------------------


@respx.mock
def test_request_body_shape_with_classes() -> None:
    route = respx.post(f"{BASE}/v1/systemone").respond(200, json=SAMPLE_RESPONSE, headers=SAMPLE_HEADERS)
    with make_client(headers={"X-Trace": "t1"}) as client:
        client.system_one(
            state="我被重复扣费了两次",
            questions={
                "is_urgent": Noul(instructions="是否紧急？", criteria={"true": "需要当天处理", "false": None}),
                "department": Choice(
                    instructions="分派部门",
                    criteria={"billing": "扣费与退款", "technical": None, "sales": None},
                ),
                "frustration": Score(criteria=["平静", "不满", "非常愤怒"]),
            },
        )
    request = route.calls.last.request
    assert request.headers["authorization"] == f"Bearer {KEY}"
    assert request.headers["content-type"] == "application/json"
    assert request.headers["x-trace"] == "t1"
    assert request.headers["user-agent"].startswith("xiangxin-python/")
    assert body_of(route) == {
        "state": "我被重复扣费了两次",
        "model": "xiangxin-latest",
        "questions": {
            "is_urgent": {
                "type": "noul",
                "instructions": "是否紧急？",
                "criteria": {"true": "需要当天处理", "false": None},
            },
            "department": {
                "type": "choice",
                "instructions": "分派部门",
                "criteria": {"billing": "扣费与退款", "technical": None, "sales": None},
            },
            # instructions 为 None 时省略 / omitted when None
            "frustration": {"type": "score", "criteria": ["平静", "不满", "非常愤怒"]},
        },
    }


@respx.mock
def test_dict_and_class_questions_are_equivalent() -> None:
    route = respx.post(f"{BASE}/v1/systemone").respond(200, json=SAMPLE_RESPONSE)
    state = {"ticket": "扣费两次", "channel": "app"}
    with make_client() as client:
        client.system_one(
            state,
            {
                "is_urgent": Noul(instructions="是否紧急？"),
                "department": Choice(instructions="部门", criteria={"billing": None, "technical": None}),
                "frustration": Score(instructions="情绪", criteria=["平静", "愤怒"]),
            },
        )
        client.system_one(
            state,
            {
                "is_urgent": {"type": "noul", "instructions": "是否紧急？"},
                "department": {"type": "choice", "instructions": "部门", "criteria": {"billing": None, "technical": None}},
                "frustration": {"type": "score", "instructions": "情绪", "criteria": ["平静", "愤怒"]},
            },
        )
    assert body_of(route, 0) == body_of(route, 1)
    assert body_of(route, 0)["state"] == state


@respx.mock
def test_mixed_questions_model_override_and_extra_body() -> None:
    route = respx.post(f"{BASE}/v1/systemone").respond(200, json=SAMPLE_RESPONSE)
    with make_client() as client:
        client.system_one(
            ["第一条消息", "第二条消息"],
            {"a": Noul(instructions="x"), "b": {"type": "noul", "instructions": "y", "weight": 2}},
            model="xiangxin-preview",
            extra_body={"beam": 4},
            extra_headers={"Authorization": "Bearer hijack", "X-Extra": "1"},
        )
    body = body_of(route)
    assert body["model"] == "xiangxin-preview"
    assert body["beam"] == 4
    assert body["questions"]["b"]["weight"] == 2  # 字典字段原样透传 / dict passthrough
    req = route.calls.last.request
    assert req.headers["authorization"] == f"Bearer {KEY}"  # 鉴权不可覆盖 / protected
    assert req.headers["x-extra"] == "1"


def test_invalid_questions_raise_before_request() -> None:
    with make_client(transport=httpx.MockTransport(lambda r: pytest.fail("no request expected"))) as client:
        with pytest.raises(XiangxinError):
            client.system_one("s", {})
        with pytest.raises(XiangxinError):
            client.system_one("s", {"a": {"instructions": "no type"}})
        with pytest.raises(XiangxinError):
            client.system_one("s", {"a": {"type": "score", "criteria": []}})
        with pytest.raises(XiangxinError):
            client.system_one("s", {"a": "not a question"})  # type: ignore[dict-item]
        with pytest.raises(XiangxinError):
            client.system_one(None, {"a": Noul()})  # type: ignore[arg-type]


# -- 响应解析 / response parsing -------------------------------------------------


@respx.mock
def test_answer_parsing_all_types() -> None:
    respx.post(f"{BASE}/v1/systemone").respond(200, json=SAMPLE_RESPONSE, headers=SAMPLE_HEADERS)
    with make_client() as client:
        resp = client.system_one("s", {"is_urgent": Noul()})
    assert isinstance(resp, SystemOneResponse)
    assert resp.model == "xiangxin-1.0.0"
    assert resp.usage.input_tokens == 296 and resp.usage.output_tokens == 20

    noul = resp.answers["is_urgent"]
    assert isinstance(noul, NoulAnswer) and noul.noul == 0.95

    choice = resp.answers["department"]
    assert isinstance(choice, ChoiceAnswer)
    assert choice.choice == "billing"
    assert choice.probabilities == {"billing": 0.88, "technical": 0.12, "sales": 0.0}
    assert choice.confidence == 0.81

    score = resp["frustration"]
    assert score.type == "score"
    assert score.score == 1.05
    assert score.legend == {0: "平静", 1: "不满", 2: "非常愤怒"}
    assert score.probabilities == {0: 0.0, 1: 0.95, 2: 0.05}
    assert score.confidence == 0.92

    assert set(resp.nouls) == {"is_urgent"}
    assert set(resp.choices) == {"department"}
    assert set(resp.scores) == {"frustration"}
    assert resp.request_id == "req_123"
    assert resp.model_ms == 53.0 and resp.total_ms == 71.0
    assert resp.raw_http_response is not None and resp.raw_http_response.status_code == 200


@respx.mock
def test_unknown_answer_types_are_skipped() -> None:
    payload = {**SAMPLE_RESPONSE, "answers": {**SAMPLE_RESPONSE["answers"], "future": {"type": "rank", "rank": [1]}}}
    respx.post(f"{BASE}/v1/systemone").respond(200, json=payload)
    with make_client() as client:
        resp = client.system_one("s", {"a": Noul()})
    assert "future" not in resp.answers
    assert resp.raw_http_response.json()["answers"]["future"]["type"] == "rank"


@respx.mock
def test_response_model_subclass() -> None:
    respx.post(f"{BASE}/v1/systemone").respond(200, json=SAMPLE_RESPONSE)

    class Ticket(SystemOneResponse):
        is_urgent: NoulAnswer
        department: ChoiceAnswer

    with make_client() as client:
        resp = client.system_one("s", {"is_urgent": Noul()}, response_model=Ticket)
    assert isinstance(resp, Ticket)
    assert resp.is_urgent.noul == 0.95
    assert resp.department == resp.answers["department"]


@respx.mock
def test_with_raw_response() -> None:
    respx.post(f"{BASE}/v1/systemone").respond(200, json=SAMPLE_RESPONSE, headers=SAMPLE_HEADERS)
    respx.get(f"{BASE}/v1/models").respond(200, json={"models": []})
    with make_client() as client:
        raw = client.with_raw_response.system_one("s", {"a": Noul()})
        assert isinstance(raw, RawResponse)
        assert raw.status_code == 200
        assert raw.headers["x-xiangxin-model-ms"] == "53"
        assert raw.request_id == "req_123"
        assert raw.json()["model"] == "xiangxin-1.0.0"
        assert raw.parse().answers["is_urgent"].noul == 0.95
        assert raw.parse() is raw.parse()
        assert client.with_raw_response.models.list().parse().models == []


@respx.mock
def test_models_list() -> None:
    route = respx.get(f"{BASE}/v1/models").respond(
        200,
        json={
            "models": [
                {"name": "xiangxin-latest", "description": "最新正式版", "release_date": "2026-10-01"},
                {"name": "xiangxin-preview", "description": "预览版", "release_date": "2026-10-01"},
            ]
        },
    )
    with make_client() as client:
        result = client.models.list()
    assert isinstance(result, ListModelsResponse)
    assert [m.name for m in result.models] == ["xiangxin-latest", "xiangxin-preview"]
    assert result.models[0].release_date == "2026-10-01"
    assert route.calls.last.request.headers["authorization"] == f"Bearer {KEY}"


# -- 超时与传输 / timeouts & transport --------------------------------------------


def test_timeout_is_forwarded_and_mapped() -> None:
    seen: list = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request.extensions["timeout"])
        raise httpx.ReadTimeout("slow", request=request)

    from xiangxin import APITimeoutError, RetryPolicy

    with make_client(transport=httpx.MockTransport(handler), timeout=5.0, retry=RetryPolicy(max_retries=0)) as client:
        with pytest.raises(APITimeoutError) as info:
            client.system_one("s", {"a": Noul()})
        assert isinstance(info.value, TimeoutError)
        with pytest.raises(APITimeoutError):
            client.system_one("s", {"a": Noul()}, timeout=1.5)
    assert seen[0]["read"] == 5.0
    assert seen[1]["read"] == 1.5


def test_connection_error_mapped() -> None:
    from xiangxin import APIConnectionError, APITimeoutError, RetryPolicy

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    with make_client(transport=httpx.MockTransport(handler), retry=RetryPolicy(max_retries=0)) as client:
        with pytest.raises(APIConnectionError) as info:
            client.models.list()
    assert not isinstance(info.value, APITimeoutError)


def test_logging_redacts_key(caplog: pytest.LogCaptureFixture) -> None:
    import logging

    transport = httpx.MockTransport(lambda r: httpx.Response(200, json=SAMPLE_RESPONSE))
    with caplog.at_level(logging.DEBUG, logger="xiangxin"):
        with make_client(transport=transport) as client:
            client.system_one("s", {"a": Noul()})
    text = caplog.text
    assert "POST /v1/systemone -> 200" in text
    assert KEY not in text and "<redacted>" in text
