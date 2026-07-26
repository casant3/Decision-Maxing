"""Provider adapter tests against mocked HTTP transports."""

from __future__ import annotations

import pytest

from app.providers.anthropic import AnthropicProvider
from app.providers.base import ProviderError, ProviderRequest
from app.providers.gemini import GeminiProvider
from app.providers.openai_compat import OpenAICompatProvider


class FakeResponse:
    def __init__(self, status_code: int, payload: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._payload = payload or {}
        self.text = text or str(payload)

    def json(self):
        return self._payload


class FakeClient:
    """Stands in for httpx.AsyncClient; pops one scripted response per call."""

    script: list[FakeResponse] = []
    requests: list[dict] = []

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        return False

    async def post(self, url, **kwargs):
        FakeClient.requests.append({"url": url, **kwargs})
        return FakeClient.script.pop(0)


@pytest.fixture(autouse=True)
def patch_httpx(monkeypatch):
    FakeClient.script = []
    FakeClient.requests = []
    for module in ("app.providers.anthropic", "app.providers.openai_compat", "app.providers.gemini"):
        monkeypatch.setattr(f"{module}.httpx.AsyncClient", FakeClient)


def req(**kw) -> ProviderRequest:
    return ProviderRequest(prompt="hello", model=kw.pop("model", "m"), **kw)


async def test_anthropic_parses_response_and_usage():
    FakeClient.script = [FakeResponse(200, {
        "content": [{"type": "text", "text": "hi there"}],
        "model": "claude-sonnet-5",
        "usage": {"input_tokens": 10, "output_tokens": 5},
    })]
    p = AnthropicProvider("key")
    result = await p.generate_text(req(model="claude-sonnet-5"))
    assert result.text == "hi there"
    assert result.usage.input_tokens == 10
    assert result.usage.cost_usd > 0
    assert FakeClient.requests[0]["headers"]["x-api-key"] == "key"


async def test_anthropic_retries_on_500_then_succeeds():
    FakeClient.script = [
        FakeResponse(500, text="server error"),
        FakeResponse(200, {"content": [{"type": "text", "text": "recovered"}],
                           "usage": {"input_tokens": 1, "output_tokens": 1}}),
    ]
    p = AnthropicProvider("key", max_retries=1)
    p.backoff_base_s = 0.0
    result = await p.generate_text(req())
    assert result.text == "recovered"
    assert len(FakeClient.requests) == 2


async def test_anthropic_does_not_retry_client_errors():
    FakeClient.script = [FakeResponse(400, text="bad request")]
    p = AnthropicProvider("key", max_retries=2)
    p.backoff_base_s = 0.0
    with pytest.raises(ProviderError):
        await p.generate_text(req())
    assert len(FakeClient.requests) == 1  # non-retryable: exactly one attempt


async def test_openai_compat_parses_response():
    FakeClient.script = [FakeResponse(200, {
        "choices": [{"message": {"content": "openai says hi"}}],
        "model": "gpt-5.2",
        "usage": {"prompt_tokens": 7, "completion_tokens": 3},
    })]
    p = OpenAICompatProvider("key", "https://api.openai.com/v1", "openai")
    result = await p.generate_text(req(model="gpt-5.2"))
    assert result.text == "openai says hi"
    assert result.usage.input_tokens == 7
    assert "Bearer key" in FakeClient.requests[0]["headers"]["Authorization"]


async def test_openai_compat_requests_json_mode_for_structured():
    FakeClient.script = [FakeResponse(200, {
        "choices": [{"message": {"content": "{}"}}], "usage": {},
    })]
    p = OpenAICompatProvider("key", "https://api.x.ai/v1", "xai")
    await p.generate_structured(req(json_schema={"type": "object"}))
    assert FakeClient.requests[0]["json"]["response_format"] == {"type": "json_object"}


async def test_gemini_parses_response():
    FakeClient.script = [FakeResponse(200, {
        "candidates": [{"content": {"parts": [{"text": "gemini reply"}]}}],
        "usageMetadata": {"promptTokenCount": 4, "candidatesTokenCount": 2},
    })]
    p = GeminiProvider("key")
    result = await p.generate_text(req(model="gemini-2.5-pro"))
    assert result.text == "gemini reply"
    assert result.usage.output_tokens == 2
    assert FakeClient.requests[0]["params"] == {"key": "key"}


async def test_circuit_breaker_opens_after_failures():
    p = AnthropicProvider("key", max_retries=0)
    p.backoff_base_s = 0.0
    p.breaker.threshold = 2
    for _ in range(2):
        FakeClient.script = [FakeResponse(500, text="down")]
        with pytest.raises(ProviderError):
            await p.generate_text(req())
    # Breaker now open: fails fast without any HTTP call.
    FakeClient.requests = []
    with pytest.raises(ProviderError, match="circuit open"):
        await p.generate_text(req())
    assert FakeClient.requests == []
