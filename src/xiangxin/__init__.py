"""象信 AI 官方 Python SDK。 / Official Python SDK for 象信 AI.

象信（xiangxin）是一个"系统一"模型：给定状态（state）与一组带类型的问题
（Noul 是非题 / Choice 单选题 / Score 打分题），一次前向即返回带校准概率的结构化答案。

Xiangxin is a "System One" model: given a state and typed questions
(Noul / Choice / Score), it returns calibrated, structured answers in one forward pass.

Example::

    from xiangxin import XiangxinClient, Choice, Noul, Score

    client = XiangxinClient()  # 读取 XIANGXIN_API_KEY / reads XIANGXIN_API_KEY
    resp = client.system_one(
        state="我被重复扣费了两次，请尽快处理！",
        questions={
            "is_urgent": Noul(instructions="是否需要紧急处理？"),
            "department": Choice(instructions="分派部门", criteria={"billing": None, "technical": None}),
            "anger": Score(instructions="情绪激动程度", criteria=["平静", "不满", "愤怒"]),
        },
    )
    resp.answers["is_urgent"].noul
    resp.usage.input_tokens
"""

from . import constants
from ._base import RawResponse
from ._client import AsyncModels, AsyncXiangxinClient, Models, XiangxinClient
from ._logging import setup_logging_from_env
from ._version import __version__
from .exceptions import (
    APIConnectionError,
    APIError,
    APIResponseValidationError,
    APITimeoutError,
    AuthenticationError,
    BadRequestError,
    ConflictError,
    InsufficientBalanceError,
    InternalServerError,
    NotFoundError,
    OverloadedError,
    PermissionDeniedError,
    RateLimitError,
    RequestTooLargeError,
    UnprocessableEntityError,
    XiangxinError,
)
from .retries import RetryPolicy
from .types import (
    Answer,
    Choice,
    ChoiceAnswer,
    ChoiceDict,
    JSONContent,
    JSONValue,
    ListModelsResponse,
    ModelInfo,
    Noul,
    NoulAnswer,
    NoulCriteria,
    NoulDict,
    Question,
    QuestionDict,
    Questions,
    Score,
    ScoreAnswer,
    ScoreDict,
    SystemOneResponse,
    Usage,
    XiangxinResponse,
)

setup_logging_from_env()

__all__ = [
    "__version__",
    "constants",
    # clients
    "XiangxinClient",
    "AsyncXiangxinClient",
    "Models",
    "AsyncModels",
    "RawResponse",
    "RetryPolicy",
    # questions
    "Noul",
    "Choice",
    "Score",
    "NoulCriteria",
    "NoulDict",
    "ChoiceDict",
    "ScoreDict",
    "Question",
    "QuestionDict",
    "Questions",
    "JSONValue",
    "JSONContent",
    # responses
    "NoulAnswer",
    "ChoiceAnswer",
    "ScoreAnswer",
    "Answer",
    "Usage",
    "XiangxinResponse",
    "SystemOneResponse",
    "ModelInfo",
    "ListModelsResponse",
    # errors
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
]
