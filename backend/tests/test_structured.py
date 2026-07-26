"""Repair chain, retries and fallback for structured agent calls."""

from __future__ import annotations

import pytest
from pydantic import BaseModel

from app.agents.jsonutil import extract_json
from app.agents.structured import AgentCaller, StructuredCallError
from app.config import RoleConfig, WorkflowBudget
from app.providers.base import ProviderError
from app.providers.registry import ProviderRegistry
from app.schemas.workflow import BudgetUsage
from app.workflow.budget import BudgetExceededError, BudgetTracker


class Toy(BaseModel):
    answer: str
    score: int


@pytest.fixture
def caller(settings, mock_provider):
    registry = ProviderRegistry(settings, mock_provider)
    roles = {"toy": RoleConfig(provider="mock", model="mock-model",
                               fallback_provider="mock", fallback_model="mock-fallback")}
    budget = BudgetTracker(WorkflowBudget(), BudgetUsage())
    return AgentCaller(registry, roles, budget), mock_provider


async def test_valid_output_first_try(caller):
    c, mock = caller
    mock.queue_response("Toy", {"answer": "yes", "score": 5})
    result, meta = await c.structured("toy", Toy, "sys", "prompt")
    assert result.answer == "yes"
    assert meta.attempts == 1
    assert not meta.fallback_used


async def test_repair_after_invalid_output(caller):
    c, mock = caller
    mock.queue_response("Toy", {"wrong_field": True})
    mock.queue_response("Toy", {"answer": "repaired", "score": 1})
    result, meta = await c.structured("toy", Toy, "sys", "prompt")
    assert result.answer == "repaired"
    assert meta.repairs == 1
    assert meta.attempts == 2
    assert not meta.fallback_used
    # The repair prompt must feed the validation errors back to the model.
    assert "Validation errors" in mock.calls[-1].prompt


async def test_reduced_prompt_after_failed_repair(caller):
    c, mock = caller
    mock.queue_response("Toy", {"wrong": 1})
    mock.queue_response("Toy", {"still_wrong": 2})
    mock.queue_response("Toy", {"answer": "third time", "score": 3})
    result, meta = await c.structured("toy", Toy, "sys", "long prompt " * 50)
    assert result.answer == "third time"
    assert meta.attempts == 3
    assert "truncated" in mock.calls[-1].prompt.lower()


async def test_fallback_model_used_after_primary_exhausted(caller):
    c, mock = caller
    for _ in range(3):
        mock.queue_response("Toy", {"never": "valid"})
    mock.queue_response("Toy", {"answer": "from fallback", "score": 9})
    result, meta = await c.structured("toy", Toy, "sys", "prompt")
    assert result.answer == "from fallback"
    assert meta.fallback_used
    assert mock.calls[-1].model == "mock-fallback"


async def test_provider_error_falls_back(caller):
    c, mock = caller
    mock.queue_response("Toy", ProviderError("boom", retryable=False))
    mock.queue_response("Toy", {"answer": "ok", "score": 1})
    result, meta = await c.structured("toy", Toy, "sys", "prompt")
    assert result.answer == "ok"
    assert meta.fallback_used


async def test_total_failure_raises_structured_error(caller):
    c, mock = caller
    for _ in range(6):
        mock.queue_response("Toy", {"never": "valid"})
    with pytest.raises(StructuredCallError) as exc:
        await c.structured("toy", Toy, "sys", "prompt")
    assert "toy" in str(exc.value)
    # Failures are recorded, not silently swallowed.
    assert exc.value.detail


async def test_budget_stops_calls(settings, mock_provider):
    registry = ProviderRegistry(settings, mock_provider)
    roles = {"toy": RoleConfig(provider="mock", model="mock-model")}
    usage = BudgetUsage(model_calls=100)
    budget = BudgetTracker(WorkflowBudget(max_model_calls=10), usage)
    c = AgentCaller(registry, roles, budget)
    with pytest.raises(BudgetExceededError):
        await c.structured("toy", Toy, "sys", "prompt")
    assert mock_provider.calls == []


# ------------------------------------------------------------- extract_json

def test_extract_json_plain():
    assert extract_json('{"a": 1}') == {"a": 1}


def test_extract_json_fenced():
    assert extract_json('```json\n{"a": 1}\n```') == {"a": 1}


def test_extract_json_with_prose():
    assert extract_json('Here you go:\n{"a": {"b": 2}}\nHope that helps!') == {"a": {"b": 2}}


def test_extract_json_with_braces_in_strings():
    assert extract_json('{"text": "a } tricky { case"}') == {"text": "a } tricky { case"}


def test_extract_json_rejects_garbage():
    with pytest.raises(ValueError):
        extract_json("no json here at all")
