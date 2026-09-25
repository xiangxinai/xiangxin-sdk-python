"""SDK 日志：记录器名为 ``xiangxin``。 / SDK logging under the ``xiangxin`` logger."""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping

from .constants import LOG_ENV

logger = logging.getLogger("xiangxin")

_LEVELS = {
    "debug": logging.DEBUG,
    "info": logging.INFO,
    "warning": logging.WARNING,
    "warn": logging.WARNING,
    "error": logging.ERROR,
    "off": logging.CRITICAL + 10,
}

_SECRET_HEADERS = frozenset({"authorization", "proxy-authorization", "cookie", "set-cookie", "x-api-key", "api-key"})


def setup_logging_from_env() -> None:
    """根据 ``XIANGXIN_LOG`` 设置日志级别（导入时调用一次）。

    Apply ``XIANGXIN_LOG`` to the ``xiangxin`` logger (called once at import).
    """
    raw = os.environ.get(LOG_ENV, "").strip().lower()
    if not raw or raw not in _LEVELS:
        return
    logger.setLevel(_LEVELS[raw])
    if raw != "off" and not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(logging.Formatter("[%(asctime)s %(name)s %(levelname)s] %(message)s"))
        logger.addHandler(handler)


def redact_headers(headers: Mapping[str, str]) -> dict[str, str]:
    """隐去鉴权类请求头。 / Redact secret headers for logging."""
    out: dict[str, str] = {}
    for key, value in headers.items():
        lower = key.lower()
        if lower in _SECRET_HEADERS or "token" in lower or "secret" in lower:
            out[key] = "<redacted>"
        else:
            out[key] = value
    return out
