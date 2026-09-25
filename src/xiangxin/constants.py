"""公开常量：环境变量名与客户端默认值。

Public constants: environment variable names and client defaults.
"""

from __future__ import annotations

API_KEY_ENV = "XIANGXIN_API_KEY"
"""API 密钥所在的环境变量。 / Environment variable holding the API key."""

BASE_URL_ENV = "XIANGXIN_BASE_URL"
"""API 根地址所在的环境变量。 / Environment variable holding the API root URL."""

DEFAULT_MODEL_ENV = "XIANGXIN_DEFAULT_MODEL"
"""默认模型所在的环境变量。 / Environment variable holding the default model."""

LOG_ENV = "XIANGXIN_LOG"
"""日志级别环境变量（debug/info/warning/error/off），导入时生效一次。

Logging level environment variable (debug/info/warning/error/off), applied once at import.
"""

DEFAULT_BASE_URL = "https://api.xiangxinai.cn"
"""默认 API 根地址。 / Default API root URL."""

DEFAULT_MODEL = "xiangxin-latest"
"""默认模型名。 / Default model name."""

DEFAULT_TIMEOUT = 120.0  # 长 state（32k token）+ 多问题的请求可达约 60 秒
"""单次 HTTP 操作的默认超时（秒）。 / Default timeout per HTTP operation, in seconds."""

REQUEST_ID_HEADER = "x-request-id"
"""服务端返回的请求 ID 响应头。 / Response header carrying the request ID."""

MODEL_MS_HEADER = "x-xiangxin-model-ms"
"""模型推理耗时（毫秒）响应头。 / Response header with model latency in ms."""

TOTAL_MS_HEADER = "x-xiangxin-total-ms"
"""网关总耗时（毫秒）响应头。 / Response header with total gateway latency in ms."""

__all__ = [
    "API_KEY_ENV",
    "BASE_URL_ENV",
    "DEFAULT_MODEL_ENV",
    "LOG_ENV",
    "DEFAULT_BASE_URL",
    "DEFAULT_MODEL",
    "DEFAULT_TIMEOUT",
    "REQUEST_ID_HEADER",
    "MODEL_MS_HEADER",
    "TOTAL_MS_HEADER",
]
