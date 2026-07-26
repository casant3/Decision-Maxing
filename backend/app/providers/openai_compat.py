"""Adapter for OpenAI-compatible chat-completions APIs.

OpenAI, xAI (Grok) and Perplexity all speak this dialect, so one adapter
class covers three providers; only base URL, key and quirks differ.
"""

from __future__ import annotations

import httpx

from app.providers.base import (
    ProviderAdapter,
    ProviderError,
    ProviderRequest,
    ProviderResult,
    ResearchProvider,
    Usage,
)


class OpenAICompatProvider(ProviderAdapter):
    name = "openai_compat"

    def __init__(self, api_key: str, base_url: str, name: str,
                 supports_json_mode: bool = True, max_retries: int = 2):
        super().__init__(max_retries=max_retries)
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.name = name
        self.supports_json_mode = supports_json_mode

    def default_model(self) -> str:
        return {"openai": "gpt-5.2-mini", "xai": "grok-4", "perplexity": "sonar-pro"}.get(
            self.name, "gpt-5.2-mini"
        )

    async def _chat(self, req: ProviderRequest, extra_body: dict | None = None) -> ProviderResult:
        messages = []
        if req.system:
            messages.append({"role": "system", "content": req.system})
        messages.append({"role": "user", "content": req.prompt})
        body: dict = {
            "model": req.model,
            "messages": messages,
            "max_tokens": req.max_tokens,
            "temperature": req.temperature,
        }
        if req.json_schema is not None and self.supports_json_mode:
            body["response_format"] = {"type": "json_object"}
        if extra_body:
            body.update(extra_body)
        async with httpx.AsyncClient(timeout=req.timeout_s) as client:
            resp = await client.post(
                f"{self.base_url}/chat/completions",
                headers={"Authorization": f"Bearer {self.api_key}"},
                json=body,
            )
        if resp.status_code == 429 or resp.status_code >= 500:
            raise ProviderError(f"{self.name} {resp.status_code}: {resp.text[:200]}", retryable=True)
        if resp.status_code != 200:
            raise ProviderError(f"{self.name} {resp.status_code}: {resp.text[:200]}", retryable=False)
        data = resp.json()
        choice = (data.get("choices") or [{}])[0]
        text = (choice.get("message") or {}).get("content") or ""
        usage = data.get("usage", {})
        return ProviderResult(
            text=text,
            model=data.get("model", req.model),
            provider=self.name,
            usage=Usage(
                input_tokens=usage.get("prompt_tokens", 0),
                output_tokens=usage.get("completion_tokens", 0),
            ),
        )

    async def _call(self, req: ProviderRequest) -> ProviderResult:
        return await self._chat(req)


class PerplexityProvider(OpenAICompatProvider, ResearchProvider):
    """Perplexity: OpenAI-compatible chat plus live web research capability."""

    def __init__(self, api_key: str, max_retries: int = 2):
        super().__init__(api_key=api_key, base_url="https://api.perplexity.ai",
                         name="perplexity", supports_json_mode=False, max_retries=max_retries)

    async def research(self, query: str, mode: str, timeout_s: float = 120.0) -> ProviderResult:
        model = "sonar-deep-research" if mode == "deep" else "sonar-pro"
        req = ProviderRequest(
            system=("You are a research assistant. Report current, sourced findings. "
                    "For every finding include the source title, URL, publisher and "
                    "publication date when available. Report facts, do not make the decision."),
            prompt=query,
            model=model,
            max_tokens=2048,
            temperature=0.2,
            timeout_s=timeout_s,
        )
        result = await self._with_retries(req)
        return result
