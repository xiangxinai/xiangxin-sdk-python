from __future__ import annotations

import pydantic
import pytest

from xiangxin import Choice, ChoiceAnswer, Noul, NoulAnswer, Score, ScoreAnswer, SystemOneResponse


def test_question_to_dict() -> None:
    assert Noul().to_dict() == {"type": "noul"}
    assert Noul(instructions={"q": "是否紧急"}).to_dict() == {"type": "noul", "instructions": {"q": "是否紧急"}}
    assert Choice(criteria={"a": None}).to_dict() == {"type": "choice", "criteria": {"a": None}}
    assert Score(criteria=["低", {"label": "高"}]).to_dict() == {"type": "score", "criteria": ["低", {"label": "高"}]}


def test_question_validation() -> None:
    with pytest.raises(pydantic.ValidationError):
        Choice(criteria={})
    with pytest.raises(pydantic.ValidationError):
        Score(criteria=[])
    with pytest.raises(pydantic.ValidationError):
        Noul(instrutions="typo")  # type: ignore[call-arg]


def test_models_are_frozen() -> None:
    q = Noul(instructions="x")
    with pytest.raises(pydantic.ValidationError):
        q.instructions = "y"  # type: ignore[misc]


def test_direct_response_validation() -> None:
    resp = SystemOneResponse.model_validate(
        {
            "model": "xiangxin-s1-1.0.0",
            "answers": {
                "n": {"type": "noul", "noul": 0.1},
                "c": {"type": "choice", "choice": "a", "probabilities": {"a": 1.0}, "confidence": 1.0},
                "s": {"type": "score", "score": 0.5, "probabilities": {"0": 0.5, "1": 0.5}, "confidence": 0.5},
            },
        }
    )
    assert isinstance(resp.answers["n"], NoulAnswer)
    assert isinstance(resp.answers["c"], ChoiceAnswer)
    assert isinstance(resp.answers["s"], ScoreAnswer)
    assert resp.answers["s"].legend == {}
    assert resp.usage.input_tokens is None
    assert resp.request_id is None
