"""请求与响应类型：问题（Noul / Choice / Score）、答案、用量与模型列表。

Request and response types: questions (Noul / Choice / Score), answers,
token usage and the model listing.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping, Sequence
from typing import Annotated, Any, ClassVar, Literal, Union

import httpx
from pydantic import BaseModel, ConfigDict, Field, PrivateAttr, field_validator, model_validator
from typing_extensions import NotRequired, TypeAlias, TypedDict

from .constants import MODEL_MS_HEADER, REQUEST_ID_HEADER, TOTAL_MS_HEADER

__all__ = [
    "JSONValue",
    "JSONContent",
    # questions
    "NoulCriteria",
    "Noul",
    "Choice",
    "Score",
    "NoulDict",
    "ChoiceDict",
    "ScoreDict",
    "QuestionDict",
    "Question",
    "Questions",
    # answers / responses
    "NoulAnswer",
    "ChoiceAnswer",
    "ScoreAnswer",
    "Answer",
    "Usage",
    "XiangxinResponse",
    "SystemOneResponse",
    "ModelInfo",
    "ListModelsResponse",
]

logger = logging.getLogger("xiangxin")

# ---------------------------------------------------------------------------
# JSON 基础类型 / JSON primitives
# ---------------------------------------------------------------------------

JSONValue: TypeAlias = Union[str, int, float, bool, None, Sequence[Any], Mapping[str, Any]]
"""任意可 JSON 序列化的值（可嵌套、可含 ``None``）。 / Any JSON-serializable value."""

JSONContent: TypeAlias = Union[str, Mapping[str, Any], Sequence[Any]]
"""文本、JSON 对象或数组；用于 state、instructions 与 criteria 描述。

Text, a JSON object, or an array; used for state, instructions and criteria descriptions.
"""

# pydantic 字段用的具体类型（避免把 str 当作 Sequence 拆开）
# Concrete field type for pydantic (so a str is never treated as a Sequence).
_Content = Union[str, dict[str, Any], list[Any]]


# ---------------------------------------------------------------------------
# 问题 / Questions
# ---------------------------------------------------------------------------


class NoulCriteria(TypedDict, total=False):
    """Noul 问题中"是 / 否"两种结果的可选描述。

    Optional descriptions of the true and false outcomes of a noul question.
    """

    true: JSONContent | None
    """"是 / 成立"时的含义。 / What a true (yes) outcome means."""

    false: JSONContent | None
    """"否 / 不成立"时的含义。 / What a false (no) outcome means."""


class _Question(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    type: str

    def to_dict(self) -> dict[str, Any]:
        """转换为请求体中的 JSON 字典（省略值为 ``None`` 的顶层字段）。

        Serialize to the wire dictionary, omitting top-level fields that are ``None``.
        """
        data = self.model_dump(mode="json")
        return {k: v for k, v in data.items() if v is not None}


class Noul(_Question):
    """是非题（noul = "no or yes"）：返回"成立"的概率 0–1。

    A yes/no question; the answer is the probability (0–1) that it is true.

    Example::

        Noul(instructions="用户是否要求退款？")
        Noul(
            instructions="这条评论是否包含人身攻击？",
            criteria={"true": "辱骂、贬低他人", "false": "正常批评或中性表达"},
        )
    """

    type: Literal["noul"] = "noul"
    instructions: _Content | None = None
    """要问的问题（文本、对象或数组）。 / The question, as text, object or array."""
    criteria: NoulCriteria | None = None
    """"是 / 否"的可选描述。 / Optional descriptions of the true/false outcomes."""


class Choice(_Question):
    """单选题：在若干命名选项中选出最可能的一个。

    A single-choice question selecting among named options.

    ``criteria`` 的键是选项名，值是该选项的描述（可为 ``None``）；最多 255 个选项。
    Keys of ``criteria`` are option labels; values describe them (or ``None``).
    At most 255 options are accepted by the API.

    Example::

        Choice(
            instructions="工单应分派到哪个部门？",
            criteria={"billing": "扣费、发票、退款", "technical": "报错与故障", "sales": None},
        )
    """

    type: Literal["choice"] = "choice"
    instructions: _Content | None = None
    """要问的问题。 / The question."""
    criteria: dict[str, _Content | None]
    """选项名 → 描述。 / Option label → description."""

    @field_validator("criteria")
    @classmethod
    def _non_empty(cls, value: dict[str, Any]) -> dict[str, Any]:
        if not value:
            raise ValueError("Choice criteria must contain at least one option")
        return value


class Score(_Question):
    """打分题：按有序量表给出 0..n-1 的期望分数。

    A score question: rates the state on an ordered rubric, returning an
    expected score between ``0`` and ``len(criteria) - 1``.

    ``criteria`` 按从低到高排列，每一档一个描述；API 接受 2–10 档。
    ``criteria`` lists one description per level, lowest first; the API accepts 2–10 levels.

    Example::

        Score(instructions="用户的情绪有多激动？", criteria=["平静", "不满", "非常愤怒"])
    """

    type: Literal["score"] = "score"
    instructions: _Content | None = None
    """要问的问题。 / The question."""
    criteria: list[_Content]
    """从 0 分起、依次递增的各档描述。 / Level descriptions starting from score 0."""

    @field_validator("criteria")
    @classmethod
    def _non_empty(cls, value: list[Any]) -> list[Any]:
        if not value:
            raise ValueError("Score criteria must contain at least one level")
        return value


class NoulDict(TypedDict):
    """以字典形式表达的 Noul 问题。 / A noul question written as a dict."""

    type: Literal["noul"]
    instructions: NotRequired[JSONContent | None]
    criteria: NotRequired[NoulCriteria | None]


class ChoiceDict(TypedDict):
    """以字典形式表达的 Choice 问题。 / A choice question written as a dict."""

    type: Literal["choice"]
    instructions: NotRequired[JSONContent | None]
    criteria: Mapping[str, JSONContent | None]


class ScoreDict(TypedDict):
    """以字典形式表达的 Score 问题。 / A score question written as a dict."""

    type: Literal["score"]
    instructions: NotRequired[JSONContent | None]
    criteria: Sequence[JSONContent]


QuestionDict: TypeAlias = Union[NoulDict, ChoiceDict, ScoreDict]
"""以 ``type`` 键区分的问题字典。 / A question dict discriminated by its ``type`` key."""

Question: TypeAlias = Union[Noul, Choice, Score, QuestionDict]
"""问题对象或问题字典，两者可在同一请求中混用。

A question object or a question dict; both may be mixed in one request.
"""

Questions: TypeAlias = Mapping[str, Question]
"""问题名 → 问题。答案以相同的名字返回。 / Question name → question; answers use the same names."""


# ---------------------------------------------------------------------------
# 答案 / Answers
# ---------------------------------------------------------------------------

_ANSWER_CONFIG = ConfigDict(frozen=True, extra="ignore")


class NoulAnswer(BaseModel):
    """是非题的答案。 / Answer to a noul question."""

    model_config = _ANSWER_CONFIG

    type: Literal["noul"] = "noul"
    noul: float
    """"成立"的概率（0–1）。接近 1 倾向"是"，接近 0 倾向"否"，0.5 附近表示不确定。

    Probability (0–1) that the statement is true. Near 1 means yes, near 0
    means no, around 0.5 means uncertain.
    """


class ChoiceAnswer(BaseModel):
    """单选题的答案。 / Answer to a choice question."""

    model_config = _ANSWER_CONFIG

    type: Literal["choice"] = "choice"
    choice: str
    """概率最高的选项名。 / The option with the highest probability."""
    probabilities: dict[str, float]
    """每个选项的概率，总和约为 1。 / Probability of each option; sums to about 1."""
    confidence: float
    """对所选选项的置信度（0–1），可用于把低置信样本转人工。

    Confidence (0–1) in the selected option; route low values to review.
    """


class ScoreAnswer(BaseModel):
    """打分题的答案。 / Answer to a score question."""

    model_config = _ANSWER_CONFIG

    type: Literal["score"] = "score"
    score: float
    """期望分数 Σ i·pᵢ，可能落在两个整数档之间。

    Expected score Σ i·pᵢ; may fall between integer levels.
    """
    legend: dict[int, Any] = Field(default_factory=dict)
    """整数分数 → 该档描述。 / Integer level → its rubric description."""
    probabilities: dict[int, float]
    """整数分数 → 概率。 / Integer level → probability."""
    confidence: float
    """对分数的置信度（0–1），即最高档概率。 / Confidence (0–1): the peak level probability."""


Answer: TypeAlias = Annotated[Union[NoulAnswer, ChoiceAnswer, ScoreAnswer], Field(discriminator="type")]
"""按 ``type`` 区分的单个答案。 / A single answer discriminated by ``type``."""

_KNOWN_ANSWER_TYPES = frozenset({"noul", "choice", "score"})


class Usage(BaseModel):
    """本次请求的 token 用量。 / Token usage of a request."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    input_tokens: int | None = None
    """输入 token 数（计费依据）。 / Input tokens (billed)."""
    output_tokens: int | None = None
    """输出 token 数（免费）。 / Output tokens (free)."""


# ---------------------------------------------------------------------------
# 响应 / Responses
# ---------------------------------------------------------------------------


class XiangxinResponse(BaseModel):
    """所有 SDK 响应模型的基类，附带底层 HTTP 响应。

    Base of SDK response models; carries the underlying HTTP response.
    """

    model_config = ConfigDict(frozen=True, extra="ignore")

    _http_response: httpx.Response | None = PrivateAttr(default=None)

    @property
    def raw_http_response(self) -> httpx.Response | None:
        """底层 ``httpx.Response``（状态码、响应头、原始 JSON）。

        The underlying ``httpx.Response`` (status, headers, raw JSON).
        """
        return self._http_response

    @property
    def request_id(self) -> str | None:
        """``x-request-id`` 响应头。 / The ``x-request-id`` response header."""
        if self._http_response is None:
            return None
        return self._http_response.headers.get(REQUEST_ID_HEADER)


def _header_float(response: httpx.Response | None, name: str) -> float | None:
    if response is None:
        return None
    raw = response.headers.get(name)
    if raw is None:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


class SystemOneResponse(XiangxinResponse):
    """``POST /v1/systemone`` 的响应：按问题名索引的答案、实际模型与用量。

    Response of ``POST /v1/systemone``: answers keyed by question name, the
    resolved model, and token usage.

    可以继承本类并声明与问题同名的字段，以获得带类型的属性访问::

    Subclass it and declare fields named after your questions for typed access::

        class TicketResult(SystemOneResponse):
            is_urgent: NoulAnswer
            department: ChoiceAnswer

        r = client.system_one(state, questions, response_model=TicketResult)
        r.is_urgent.noul
    """

    model: str
    """实际响应的模型版本，如 ``xiangxin-2.0.0``。 / Resolved model, e.g. ``xiangxin-2.0.0``."""
    answers: dict[str, Answer]
    """全部答案，键为问题名。 / All answers keyed by question name."""
    usage: Usage = Field(default_factory=Usage)
    """token 用量。 / Token usage."""

    _BASE_FIELDS: ClassVar[frozenset[str]] = frozenset({"model", "answers", "usage"})

    @model_validator(mode="before")
    @classmethod
    def _prepare(cls, data: Any) -> Any:
        if not isinstance(data, Mapping):
            return data
        data = dict(data)
        answers = data.get("answers")
        if isinstance(answers, Mapping):
            kept: dict[str, Any] = {}
            for name, answer in answers.items():
                kind = answer.get("type") if isinstance(answer, Mapping) else None
                if kind in _KNOWN_ANSWER_TYPES:
                    kept[name] = answer
                else:
                    logger.warning("Skipping answer %r with unrecognized type %r", name, kind)
            data["answers"] = kept
            # 子类中与问题同名的字段自动填充 / Populate subclass fields named after questions.
            for field_name in cls.model_fields:
                if field_name not in cls._BASE_FIELDS and field_name not in data and field_name in kept:
                    data[field_name] = kept[field_name]
        return data

    def __getitem__(self, name: str) -> NoulAnswer | ChoiceAnswer | ScoreAnswer:
        """``resp["x"]`` 等价于 ``resp.answers["x"]``。 / Shorthand for ``resp.answers[name]``."""
        return self.answers[name]

    @property
    def nouls(self) -> dict[str, NoulAnswer]:
        """所有是非题答案。 / All noul answers."""
        return {k: v for k, v in self.answers.items() if isinstance(v, NoulAnswer)}

    @property
    def choices(self) -> dict[str, ChoiceAnswer]:
        """所有单选题答案。 / All choice answers."""
        return {k: v for k, v in self.answers.items() if isinstance(v, ChoiceAnswer)}

    @property
    def scores(self) -> dict[str, ScoreAnswer]:
        """所有打分题答案。 / All score answers."""
        return {k: v for k, v in self.answers.items() if isinstance(v, ScoreAnswer)}

    @property
    def model_ms(self) -> float | None:
        """模型推理耗时（毫秒，来自 ``x-xiangxin-model-ms``）。 / Model latency in ms."""
        return _header_float(self._http_response, MODEL_MS_HEADER)

    @property
    def total_ms(self) -> float | None:
        """网关总耗时（毫秒，来自 ``x-xiangxin-total-ms``）。 / Total gateway latency in ms."""
        return _header_float(self._http_response, TOTAL_MS_HEADER)


class ModelInfo(BaseModel):
    """单个可用模型的元数据。 / Metadata of one available model."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    name: str
    """可用于请求 ``model`` 字段的名称或别名。 / Name or alias accepted by ``model``."""
    description: str = ""
    """模型说明。 / Human-readable description."""
    release_date: str | None = None
    """发布日期 ``YYYY-MM-DD``。 / Release date ``YYYY-MM-DD``."""


class ListModelsResponse(XiangxinResponse):
    """``GET /v1/models`` 的响应。 / Response of ``GET /v1/models``."""

    models: list[ModelInfo]
    """可用模型列表。 / Available models."""
