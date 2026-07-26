"""Provider abstraction. Everything above this layer sees only
ProviderRequest/ProviderResult — no provider-specific code elsewhere."""

from __future__ import annotations

import asyncio
import time
from abc import ABC, abstractmethod
from typing import Any

from pydantic import BaseModel, Field

from app.config import estimate_cost


class ProviderError(Exception):
    def __init__(self, message: str, retryable: bool = True):
        super().__init__(message)
        self.retryable = retryable


class CircuitOpenError(ProviderError):
    def __init__(self, provider: str):
        super().__init__(f"circuit open for provider {provider}", retryable=False)


class Usage(BaseModel):
    input_tokens: int = 0
    output_tokens: int = 0
    cost_usd: float = 0.0


class ProviderRequest(BaseModel):
    system: str = ""
    prompt: str
    model: str
    max_tokens: int = 4096
    temperature: float = 0.3
    # When set, the provider is asked for JSON conforming to this schema.
    json_schema: dict[str, Any] | None = None
    schema_name: str = ""
    timeout_s: float = 90.0


class ProviderResult(BaseModel):
    text: str
    model: str
    provider: str
    usage: Usage = Field(default_factory=Usage)
    latency_ms: int = 0


class CircuitBreaker:
    """Opens after `threshold` consecutive failures; half-opens after `cooldown_s`."""

    def __init__(self, threshold: int = 4, cooldown_s: float = 60.0):
        self.threshold = threshold
        self.cooldown_s = cooldown_s
        self.consecutive_failures = 0
        self.opened_at: float | None = None

    @property
    def is_open(self) -> bool:
        if self.opened_at is None:
            return False
        if time.monotonic() - self.opened_at >= self.cooldown_s:
            return False  # half-open: allow a probe call
        return True

    def record_success(self) -> None:
        self.consecutive_failures = 0
        self.opened_at = None

    def record_failure(self) -> None:
        self.consecutive_failures += 1
        if self.consecutive_failures >= self.threshold:
            self.opened_at = time.monotonic()


class ProviderAdapter(ABC):
    """Base adapter: retry with exponential backoff, timeout, circuit breaker
    and cost accounting are shared here; subclasses implement only `_call`."""

    name: str = "base"

    def __init__(self, max_retries: int = 2, backoff_base_s: float = 1.0):
        self.max_retries = max_retries
        self.backoff_base_s = backoff_base_s
        self.breaker = CircuitBreaker()

    @abstractmethod
    async def _call(self, req: ProviderRequest) -> ProviderResult:
        """Single API call; raise ProviderError on failure."""

    async def generate_text(self, req: ProviderRequest) -> ProviderResult:
        return await self._with_retries(req)

    async def generate_structured(self, req: ProviderRequest) -> ProviderResult:
        if req.json_schema is None:
            raise ValueError("generate_structured requires json_schema")
        return await self._with_retries(req)

    async def health_check(self) -> bool:
        try:
            req = ProviderRequest(prompt="Reply with OK", model=self.default_model(), max_tokens=8, timeout_s=15)
            await self._call(req)
            return True
        except Exception:
            return False

    def default_model(self) -> str:
        return "mock-model"

    async def _with_retries(self, req: ProviderRequest) -> ProviderResult:
        if self.breaker.is_open:
            raise CircuitOpenError(self.name)
        last_err: Exception | None = None
        for attempt in range(self.max_retries + 1):
            start = time.monotonic()
            try:
                result = await asyncio.wait_for(self._call(req), timeout=req.timeout_s)
                result.latency_ms = int((time.monotonic() - start) * 1000)
                if result.usage.cost_usd == 0.0:
                    result.usage.cost_usd = estimate_cost(
                        req.model, result.usage.input_tokens, result.usage.output_tokens
                    )
                self.breaker.record_success()
                return result
            except TimeoutError:
                last_err = ProviderError(f"{self.name} timed out after {req.timeout_s}s")
                self.breaker.record_failure()
            except ProviderError as e:
                last_err = e
                self.breaker.record_failure()
                if not e.retryable:
                    break
            except Exception as e:  # noqa: BLE001 — normalise unexpected errors
                last_err = ProviderError(f"{self.name}: {e}")
                self.breaker.record_failure()
            if attempt < self.max_retries:
                await asyncio.sleep(self.backoff_base_s * (2**attempt))
        raise last_err if last_err else ProviderError(f"{self.name}: unknown failure")


class ResearchProvider(ABC):
    """Separate capability: only some providers can research the live web."""

    @abstractmethod
    async def research(self, query: str, mode: str, timeout_s: float = 120.0) -> ProviderResult:
        ...
