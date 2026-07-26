"""Google Gemini generateContent adapter."""

from __future__ import annotations

import httpx

from app.providers.base import ProviderAdapter, ProviderError, ProviderRequest, ProviderResult, Usage

BASE_URL = "https://generativelanguage.googleapis.com/v1beta/models"


class GeminiProvider(ProviderAdapter):
    name = "gemini"

    def __init__(self, api_key: str, max_retries: int = 2):
        super().__init__(max_retries=max_retries)
        self.api_key = api_key

    def default_model(self) -> str:
        return "gemini-2.5-pro"

    async def _call(self, req: ProviderRequest) -> ProviderResult:
        body: dict = {
            "contents": [{"role": "user", "parts": [{"text": req.prompt}]}],
            "generationConfig": {
                "maxOutputTokens": req.max_tokens,
                "temperature": req.temperature,
            },
        }
        if req.system:
            body["systemInstruction"] = {"parts": [{"text": req.system}]}
        if req.json_schema is not None:
            body["generationConfig"]["responseMimeType"] = "application/json"
        async with httpx.AsyncClient(timeout=req.timeout_s) as client:
            resp = await client.post(
                f"{BASE_URL}/{req.model}:generateContent",
                params={"key": self.api_key},
                json=body,
            )
        if resp.status_code == 429 or resp.status_code >= 500:
            raise ProviderError(f"gemini {resp.status_code}: {resp.text[:200]}", retryable=True)
        if resp.status_code != 200:
            raise ProviderError(f"gemini {resp.status_code}: {resp.text[:200]}", retryable=False)
        data = resp.json()
        candidates = data.get("candidates") or []
        text = ""
        if candidates:
            parts = (candidates[0].get("content") or {}).get("parts") or []
            text = "".join(p.get("text", "") for p in parts)
        meta = data.get("usageMetadata", {})
        return ProviderResult(
            text=text,
            model=req.model,
            provider=self.name,
            usage=Usage(
                input_tokens=meta.get("promptTokenCount", 0),
                output_tokens=meta.get("candidatesTokenCount", 0),
            ),
        )
