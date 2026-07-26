"""Provider registry: resolves a provider name to a live adapter.

Falls back to the shared mock provider when mock mode is on or the
provider's API key is missing — so the system always runs.
"""

from __future__ import annotations

from app.config import Settings
from app.providers.anthropic import AnthropicProvider
from app.providers.base import ProviderAdapter, ResearchProvider
from app.providers.gemini import GeminiProvider
from app.providers.mock import MockProvider
from app.providers.openai_compat import OpenAICompatProvider, PerplexityProvider


class ProviderRegistry:
    def __init__(self, settings: Settings, mock: MockProvider | None = None):
        self.settings = settings
        self.mock = mock or MockProvider()
        self._adapters: dict[str, ProviderAdapter] = {}

    def _build(self, name: str) -> ProviderAdapter | None:
        s = self.settings
        if name == "anthropic" and s.anthropic_api_key:
            return AnthropicProvider(s.anthropic_api_key)
        if name == "openai" and s.openai_api_key:
            return OpenAICompatProvider(s.openai_api_key, "https://api.openai.com/v1", "openai")
        if name == "xai" and s.xai_api_key:
            return OpenAICompatProvider(s.xai_api_key, "https://api.x.ai/v1", "xai")
        if name == "perplexity" and s.perplexity_api_key:
            return PerplexityProvider(s.perplexity_api_key)
        if name == "gemini" and s.gemini_api_key:
            return GeminiProvider(s.gemini_api_key)
        return None

    def get(self, name: str) -> ProviderAdapter:
        if self.settings.use_mock_providers or name == "mock":
            return self.mock
        if name not in self._adapters:
            adapter = self._build(name)
            if adapter is None:
                # Missing key: degrade to mock rather than failing the workflow.
                return self.mock
            self._adapters[name] = adapter
        return self._adapters[name]

    def get_research(self, name: str) -> ResearchProvider:
        adapter = self.get(name)
        if isinstance(adapter, ResearchProvider):
            return adapter
        return self.mock

    async def health(self) -> dict[str, bool]:
        out: dict[str, bool] = {"mock": True}
        if self.settings.use_mock_providers:
            return out
        for name in ("anthropic", "openai", "xai", "perplexity", "gemini"):
            adapter = self._build(name)
            out[name] = await adapter.health_check() if adapter else False
        return out
