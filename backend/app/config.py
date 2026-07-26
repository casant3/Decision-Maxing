"""Application configuration.

Model↔role assignments are configuration, not code: defaults below are
hypotheses and can be overridden with a JSON file (ROLE_CONFIG_PATH) or
individual env vars, without touching application logic.
"""

from __future__ import annotations

import json
from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class RoleConfig(BaseModel):
    provider: str
    model: str
    fallback_provider: str | None = None
    fallback_model: str | None = None
    timeout_s: float = 90.0
    max_retries: int = 2
    cost_limit_usd: float = 1.0
    context_limit_tokens: int = 100_000


# Initial configuration from the product spec — configurable hypotheses.
DEFAULT_ROLES: dict[str, RoleConfig] = {
    "chief_of_staff": RoleConfig(provider="anthropic", model="claude-sonnet-5",
                                 fallback_provider="openai", fallback_model="gpt-5.2"),
    "context_gate": RoleConfig(provider="anthropic", model="claude-haiku-4-5-20251001",
                               fallback_provider="openai", fallback_model="gpt-5.2-mini"),
    "router": RoleConfig(provider="anthropic", model="claude-haiku-4-5-20251001",
                         fallback_provider="openai", fallback_model="gpt-5.2-mini"),
    "researcher": RoleConfig(provider="perplexity", model="sonar-pro"),
    "contrarian": RoleConfig(provider="xai", model="grok-4",
                             fallback_provider="anthropic", fallback_model="claude-sonnet-5"),
    "first_principles": RoleConfig(provider="openai", model="o4-mini",
                                   fallback_provider="anthropic", fallback_model="claude-sonnet-5"),
    "expansionist": RoleConfig(provider="anthropic", model="claude-sonnet-5",
                               fallback_provider="openai", fallback_model="gpt-5.2"),
    "outsider": RoleConfig(provider="gemini", model="gemini-2.5-pro",
                           fallback_provider="anthropic", fallback_model="claude-sonnet-5"),
    "customer_advocate": RoleConfig(provider="openai", model="gpt-5.2",
                                    fallback_provider="anthropic", fallback_model="claude-sonnet-5"),
    "argument_mapper": RoleConfig(provider="anthropic", model="claude-sonnet-5",
                                  fallback_provider="openai", fallback_model="gpt-5.2"),
    # Chairman: strongest available reasoning model.
    "chairman": RoleConfig(provider="anthropic", model="claude-opus-5",
                           fallback_provider="openai", fallback_model="o3"),
    # Auditor: a different model family from the Chairman.
    "auditor": RoleConfig(provider="openai", model="o3",
                          fallback_provider="gemini", fallback_model="gemini-2.5-pro"),
    "executor": RoleConfig(provider="anthropic", model="claude-sonnet-5",
                           fallback_provider="openai", fallback_model="gpt-5.2-mini"),
    "direct_answer": RoleConfig(provider="anthropic", model="claude-sonnet-5",
                                fallback_provider="openai", fallback_model="gpt-5.2"),
}

# USD per 1M tokens (input, output). Estimates for cost *tracking*, kept in
# config so they can be updated without code changes.
MODEL_PRICES: dict[str, tuple[float, float]] = {
    "claude-opus-5": (15.0, 75.0),
    "claude-sonnet-5": (3.0, 15.0),
    "claude-haiku-4-5-20251001": (1.0, 5.0),
    "gpt-5.2": (5.0, 15.0),
    "gpt-5.2-mini": (0.6, 2.4),
    "o3": (10.0, 40.0),
    "o4-mini": (1.1, 4.4),
    "gemini-2.5-pro": (1.25, 10.0),
    "grok-4": (3.0, 15.0),
    "sonar-pro": (3.0, 15.0),
    "mock-model": (0.0, 0.0),
}


class WorkflowBudget(BaseModel):
    max_clarification_rounds: int = 3
    max_model_calls: int = 40
    max_research_queries: int = 6
    max_input_tokens: int = 400_000
    max_output_tokens: int = 100_000
    max_cost_usd: float = 5.0
    max_duration_s: float = 900.0


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    app_name: str = "decision-council"
    debug: bool = False
    database_url: str = "sqlite+aiosqlite:///./decision_council.db"
    cors_origins: str = "http://localhost:3000"

    # Provider API keys — server-side only, never sent to the client.
    anthropic_api_key: str = ""
    openai_api_key: str = ""
    gemini_api_key: str = ""
    xai_api_key: str = ""
    perplexity_api_key: str = ""

    # When true (or when a role's provider has no API key), the mock provider
    # is used, so the whole system runs offline.
    use_mock_providers: bool = True

    role_config_path: str = ""  # optional JSON overriding DEFAULT_ROLES
    budget: WorkflowBudget = Field(default_factory=WorkflowBudget)

    # Data retention: 0 = keep forever (MVP default).
    retention_days: int = 0

    def roles(self) -> dict[str, RoleConfig]:
        roles = dict(DEFAULT_ROLES)
        if self.role_config_path:
            path = Path(self.role_config_path)
            if path.exists():
                overrides = json.loads(path.read_text())
                for name, cfg in overrides.items():
                    roles[name] = RoleConfig(**{**roles.get(name, roles["direct_answer"]).model_dump(), **cfg})
        return roles


@lru_cache
def get_settings() -> Settings:
    return Settings()


def estimate_cost(model: str, input_tokens: int, output_tokens: int) -> float:
    inp, out = MODEL_PRICES.get(model, (2.0, 8.0))
    return round((input_tokens * inp + output_tokens * out) / 1_000_000, 6)
