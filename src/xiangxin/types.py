"""请求与响应类型：问题（Noul / Choice / Score）、答案、用量、模型列表与条件反射。

Request and response types: questions (Noul / Choice / Score), answers,
token usage, the model listing and reflexes.
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
    # reflexes
    "ReflexLabel",
    "ReflexExample",
    "ReflexStatus",
    "REFLEX_FINAL_STATUSES",
    "ReflexQuestionMetrics",
    "ReflexEvaluation",
    "ReflexMetrics",
    "Reflex",
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
    """实际响应的模型版本，如 ``xiangxin-1.0.0``。 / Resolved model, e.g. ``xiangxin-1.0.0``."""
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



# ---------------------------------------------------------------------------
# 条件反射 / Reflexes
# ---------------------------------------------------------------------------

ReflexLabel: TypeAlias = Union[bool, str, int]
"""一条标注：Noul 为 ``True/False``，Choice 为选项名，Score 为档位下标（从 0 起）。

One label: ``True/False`` for noul, the option label for choice, the level index for score.
"""


class ReflexExample(TypedDict):
    """练反射用的一条样本。 / One training example for a reflex.

    ``answers`` 可以只标部分问题。 / ``answers`` may label only some of the questions.

    Example::

        {"state": "我被重复扣费了两次", "answers": {"department": "billing", "is_urgent": True}}
    """

    state: JSONContent
    """样本内容。 / The example's state."""
    answers: Mapping[str, ReflexLabel]
    """问题名 → 标注。 / Question name → label."""


ReflexStatus: TypeAlias = Literal["queued", "training", "ready", "failed", "cancelled"]
"""反射状态。 / Reflex status."""

REFLEX_FINAL_STATUSES: frozenset[str] = frozenset({"ready", "failed", "cancelled"})
"""训练结束的状态，``reflexes.wait`` 等到其中之一即返回。 / Final statuses awaited by ``reflexes.wait``."""

_METRICS_CONFIG = ConfigDict(frozen=True, extra="ignore")


class ReflexQuestionMetrics(BaseModel):
    """单个问题上的成绩。 / Scores on one question."""

    model_config = _METRICS_CONFIG

    accuracy: float | None = None
    """准确率（0–1）。 / Accuracy (0–1)."""
    n: int | None = None
    """参与评测的标注条数。 / Number of labels evaluated."""


class ReflexEvaluation(BaseModel):
    """一组评测成绩（练之前或练之后）。 / One set of evaluation scores (before or after training)."""

    model_config = _METRICS_CONFIG

    accuracy: float | None = None
    """准确率（0–1）。 / Accuracy (0–1)."""
    log_loss: float | None = None
    """对数损失，越小越好。 / Log loss; lower is better."""
    ece: float | None = None
    """期望校准误差，越小越好。 / Expected calibration error; lower is better."""
    per_question: dict[str, ReflexQuestionMetrics] = Field(default_factory=dict)
    """问题名 → 该问题的成绩。 / Question name → its scores."""


class ReflexMetrics(BaseModel):
    """训练结果。样本 ≥ 20 条时按留出的验证集计，否则按训练集计（见 ``evaluated_on``）。

    Training results, measured on a held-out validation split when there are at
    least 20 examples, otherwise on the training set (see ``evaluated_on``).
    """

    model_config = _METRICS_CONFIG

    examples: int | None = None
    """样本总数。 / Total examples."""
    train_examples: int | None = None
    """训练集条数。 / Training examples."""
    val_examples: int | None = None
    """验证集条数。 / Validation examples."""
    evaluated_on: str | None = None
    """``"val"`` 或 ``"train"``。 / ``"val"`` or ``"train"``."""
    epochs: float | None = None
    """实际训练轮数。 / Epochs trained."""
    duration_s: float | None = None
    """训练耗时（秒）。 / Training time in seconds."""
    before: ReflexEvaluation | None = None
    """基础条件反射在同一评测集上的成绩（练之前）。 / Base reflex on the same split (before training)."""
    after: ReflexEvaluation | None = None
    """练之后的成绩。 / Scores after training."""


class Reflex(XiangxinResponse):
    """一个练出来的条件反射。推理时把 :attr:`model` 传给 ``system_one`` 的 ``model``。

    A trained reflex. Pass :attr:`model` as ``model=`` to ``system_one`` for inference.
    """

    id: str
    """反射 ID，如 ``rf_…``。 / Reflex ID, e.g. ``rf_…``."""
    name: str
    """反射名。 / Reflex name."""
    model: str = ""
    """推理用模型名 ``xiangxin-reflex:<name>``。 / Model name for inference."""
    description: str = ""
    """说明。 / Description."""
    status: str
    """``queued`` / ``training`` / ``ready`` / ``failed`` / ``cancelled``（见 :data:`ReflexStatus`）。"""
    usable: bool = False
    """已有练好的版本可用于推理（重练期间旧版本照常可用）。

    A trained version is available for inference (the old one stays live during a retrain).
    """
    progress: float = 0.0
    """当前训练进度（0–1）。 / Progress of the current training (0–1)."""
    stage: str | None = None
    """当前阶段。 / Current stage."""
    queue_position: int | None = None
    """排队位置（仅 ``queued`` 时）。 / Queue position, only while ``queued``."""
    questions: dict[str, Any] = Field(default_factory=dict)
    """问题定义。 / Question definitions."""
    examples: int | None = None
    """最近一次提交的样本条数。 / Number of examples last submitted."""
    metrics: ReflexMetrics | None = None
    """最近一次成功训练的成绩。 / Results of the last successful training."""
    error: str | None = None
    """失败原因。 / Failure reason."""
    created_at: str | None = None
    """创建时间（ISO 8601）。 / Creation time (ISO 8601)."""
    updated_at: str | None = None
    """最近一次状态变化时间。 / Time of the last status change."""
    trained_at: str | None = None
    """最近一次训练完成时间。 / Time the last training finished."""

    @property
    def done(self) -> bool:
        """训练已结束（``ready`` / ``failed`` / ``cancelled``）。 / Training reached a final status."""
        return self.status in REFLEX_FINAL_STATUSES


class ListReflexesResponse(XiangxinResponse):
    """``GET /v1/reflexes`` 的响应。 / Response of ``GET /v1/reflexes``."""

    reflexes: list[Reflex]
    """本组织的反射，新建的在前。 / The organization's reflexes, newest first."""


class DeleteReflexResponse(XiangxinResponse):
    """``DELETE /v1/reflexes/{name}`` 的响应。 / Response of ``DELETE /v1/reflexes/{name}``."""

    ok: bool = True
