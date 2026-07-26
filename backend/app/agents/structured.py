"""Structured agent-call core.

One place implements the required failure ladder for every agent:
  1. validate the model output against the strict Pydantic schema
  2. on failure: one structured repair attempt (errors fed back)
  3. one retry with a reduced prompt
  4. the configured fallback model
  5. caller may continue without the agent when safe (skip is the
     caller's decision — this module raises StructuredCallError)
Every failure is recorded; malformed data is never silently accepted.
"""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel, ValidationError

from app.agents.jsonutil import extract_json
from app.config import RoleConfig
from app.prompts.shared import json_output_instruction
from app.providers.base import ProviderError, ProviderRequest, ProviderResult
from app.providers.registry import ProviderRegistry
from app.workflow.budget import BudgetTracker

T = TypeVar("T", bound=BaseModel)

REDUCED_PROMPT_CHARS = 6000


class StructuredCallError(Exception):
    def __init__(self, role: str, detail: str):
        super().__init__(f"structured call failed for role '{role}': {detail}")
        self.role = role
        self.detail = detail


class CallMeta(BaseModel):
    role: str
    provider: str = ""
    model: str = ""
    attempts: int = 0
    repairs: int = 0
    fallback_used: bool = False
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0
    latency_ms: int = 0
    errors: list[str] = []


class AgentCaller:
    def __init__(self, registry: ProviderRegistry, roles: dict[str, RoleConfig],
                 budget: BudgetTracker):
        self.registry = registry
        self.roles = roles
        self.budget = budget

    async def structured(self, role: str, schema: type[T], system: str, prompt: str) -> tuple[T, CallMeta]:
        cfg = self.roles[role]
        meta = CallMeta(role=role)
        schema_json = json_output_instruction(str(schema.model_json_schema()))
        json_schema = schema.model_json_schema()

        async def attempt(provider_name: str, model: str, user_prompt: str) -> T:
            self.budget.check_hard_limits()
            provider = self.registry.get(provider_name)
            req = ProviderRequest(
                system=system,
                prompt=user_prompt + schema_json,
                model=model,
                json_schema=json_schema,
                schema_name=schema.__name__,
                timeout_s=cfg.timeout_s,
            )
            result = await provider.generate_structured(req)
            self._account(meta, result)
            meta.provider, meta.model = result.provider, result.model
            meta.attempts += 1
            return self._parse(schema, result.text)

        async def attempt_with_repair(provider_name: str, model: str) -> T:
            try:
                return await attempt(provider_name, model, prompt)
            except (ValidationError, ValueError) as e:
                meta.errors.append(f"{provider_name}/{model} invalid output: {str(e)[:300]}")
                # 1) structured repair: feed the errors back once
                meta.repairs += 1
                repair_prompt = (
                    prompt
                    + "\n\nYour previous output was invalid JSON for the required schema. "
                    + f"Validation errors:\n{str(e)[:1500]}\n"
                    + "Return ONLY corrected JSON."
                )
                try:
                    return await attempt(provider_name, model, repair_prompt)
                except (ValidationError, ValueError) as e2:
                    meta.errors.append(f"repair failed: {str(e2)[:200]}")
                # 2) retry once with a reduced prompt
                reduced = prompt[:REDUCED_PROMPT_CHARS] + "\n\n(Context truncated. Respond with JSON only.)"
                return await attempt(provider_name, model, reduced)

        try:
            return await attempt_with_repair(cfg.provider, cfg.model), meta
        except (ValidationError, ValueError, ProviderError) as e:
            meta.errors.append(f"primary exhausted: {str(e)[:200]}")
            # 3) configured fallback model
            if cfg.fallback_provider and cfg.fallback_model:
                meta.fallback_used = True
                try:
                    return await attempt_with_repair(cfg.fallback_provider, cfg.fallback_model), meta
                except (ValidationError, ValueError, ProviderError) as e2:
                    meta.errors.append(f"fallback exhausted: {str(e2)[:200]}")
                    raise StructuredCallError(role, "; ".join(meta.errors)) from e2
            raise StructuredCallError(role, "; ".join(meta.errors)) from e

    async def text(self, role: str, system: str, prompt: str) -> tuple[str, CallMeta]:
        cfg = self.roles[role]
        meta = CallMeta(role=role)
        self.budget.check_hard_limits()
        provider = self.registry.get(cfg.provider)
        req = ProviderRequest(system=system, prompt=prompt, model=cfg.model, timeout_s=cfg.timeout_s)
        try:
            result = await provider.generate_text(req)
        except ProviderError:
            if not (cfg.fallback_provider and cfg.fallback_model):
                raise
            meta.fallback_used = True
            provider = self.registry.get(cfg.fallback_provider)
            req.model = cfg.fallback_model
            result = await provider.generate_text(req)
        self._account(meta, result)
        meta.provider, meta.model = result.provider, result.model
        return result.text, meta

    def _parse(self, schema: type[T], text: str) -> T:
        return schema.model_validate(extract_json(text))

    def _account(self, meta: CallMeta, result: ProviderResult) -> None:
        self.budget.add(result.usage)
        meta.input_tokens += result.usage.input_tokens
        meta.output_tokens += result.usage.output_tokens
        meta.cost_usd = round(meta.cost_usd + result.usage.cost_usd, 6)
        meta.latency_ms += result.latency_ms
