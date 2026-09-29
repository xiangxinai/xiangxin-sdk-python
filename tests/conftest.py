from __future__ import annotations

from typing import Any

import pytest

import xiangxin._client as client_module

BASE = "https://api.test.xiangxinai.cn"

SAMPLE_RESPONSE: dict[str, Any] = {
    "model": "xiangxin-2.0.0",
    "answers": {
        "is_urgent": {"type": "noul", "noul": 0.95},
        "department": {
            "type": "choice",
            "choice": "billing",
            "probabilities": {"billing": 0.88, "technical": 0.12, "sales": 0.0},
            "confidence": 0.81,
        },
        "frustration": {
            "type": "score",
            "score": 1.05,
            "legend": {"0": "平静", "1": "不满", "2": "非常愤怒"},
            "probabilities": {"0": 0.0, "1": 0.95, "2": 0.05},
            "confidence": 0.92,
        },
    },
    "usage": {"input_tokens": 296, "output_tokens": 20},
}

SAMPLE_HEADERS = {
    "x-request-id": "req_123",
    "x-xiangxin-model-ms": "53",
    "x-xiangxin-total-ms": "71",
}


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("XIANGXIN_API_KEY", "XIANGXIN_BASE_URL", "XIANGXIN_DEFAULT_MODEL", "XIANGXIN_LOG"):
        monkeypatch.delenv(name, raising=False)
    # 测试不应受本机代理设置影响 / keep tests independent of local proxy settings
    for name in ("ALL_PROXY", "HTTP_PROXY", "HTTPS_PROXY", "all_proxy", "http_proxy", "https_proxy"):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def sleeps(monkeypatch: pytest.MonkeyPatch) -> list[float]:
    """把重试等待替换为记录，不真正休眠。 / Record retry delays instead of sleeping."""
    recorded: list[float] = []

    def fake_sleep(seconds: float) -> None:
        recorded.append(seconds)

    async def fake_async_sleep(seconds: float) -> None:
        recorded.append(seconds)

    monkeypatch.setattr(client_module, "_sleep", fake_sleep)
    monkeypatch.setattr(client_module, "_async_sleep", fake_async_sleep)
    return recorded
