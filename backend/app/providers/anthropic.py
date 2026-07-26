"""Anthropic Messages API adapter (thin HTTP translation only)."""

from __future__ import annotations

import httpx

from app.providers.base import (
    ProviderAdapter,
    ProviderError,
    ProviderRequest,
    ProviderResult,
    Usage,
)

API_URL = "https://api.anthropic.com/v1/messages"
API_VERSION = "2023-06-01"


class AnthropicProvider(ProviderAdapter):
    name = "anthropic"

    def __init__(self, api_key: str, max_retries: int = 2):
        super().__init__(max_retries=max_retries)
        self.api_key = api_key

    def default_model(self) -> str:
        return "claude-haiku-4-5-20251001"

    async def _call(self, req: ProviderRequest) -> ProviderResult:
        body: dict = {
            "model": req.model,
            "max_tokens": req.max_tokens,
            "temperature": req.temperature,
            "messages": [{"role": "user", "content": req.prompt}],
        }
        if req.system:
            body["system"] = req.system
        async with httpx.AsyncClient(timeout=req.timeout_s) as client:
            resp = await client.post(
                API_URL,
                headers={
                    "x-api-key": self.api_key,
                    "anthropic-version": API_VERSION,
                    "content-type": "application/json",
                },
                json=body,
            )
        if resp.status_code == 429 or resp.status_code >= 500:
            raise ProviderError(f"anthropic {resp.status_code}: {resp.text[:200]}", retryable=True)
        if resp.status_code != 200:
            raise ProviderError(f"anthropic {resp.status_code}: {resp.text[:200]}", retryable=False)
        data = resp.json()
        text = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
        usage = data.get("usage", {})
        return ProviderResult(
            text=text,
            model=data.get("model", req.model),
            provider=self.name,
            usage=Usage(
                input_tokens=usage.get("input_tokens", 0),
                output_tokens=usage.get("output_tokens", 0),
            ),
        )
