from __future__ import annotations

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.config import Settings, WorkflowBudget
from app.models import Base
from app.providers.mock import MockProvider
from app.providers.registry import ProviderRegistry
from app.repo import CaseRepository
from app.workflow.engine import WorkflowEngine


@pytest.fixture
async def db_session():
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False}
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    async with factory() as session:
        yield session
    await engine.dispose()


@pytest.fixture
def settings() -> Settings:
    return Settings(use_mock_providers=True, _env_file=None)


@pytest.fixture
def mock_provider() -> MockProvider:
    return MockProvider()


@pytest.fixture
def registry(settings, mock_provider) -> ProviderRegistry:
    return ProviderRegistry(settings, mock_provider)


@pytest.fixture
def repo(db_session) -> CaseRepository:
    return CaseRepository(db_session)


@pytest.fixture
def engine(repo, registry, settings) -> WorkflowEngine:
    return WorkflowEngine(repo, registry, settings)


def tight_budget(**overrides) -> Settings:
    budget = WorkflowBudget(**overrides)
    return Settings(use_mock_providers=True, budget=budget, _env_file=None)


async def make_ready_case(engine: WorkflowEngine):
    """Standard two-turn intake: question, then constraints answer -> READY."""
    case = await engine.create_case(
        "Should I quit my job to start a meal-prep delivery business in Austin?"
    )
    if case.status.value == "intake":
        case = await engine.handle_user_message(
            case, "I have $5000 budget and 10 hours/week. I want to keep my job for now."
        )
    return case
