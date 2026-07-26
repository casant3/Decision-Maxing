"""Async database engine/session. SQLite by default (zero infrastructure);
PostgreSQL via DATABASE_URL. JSON columns are portable across both."""

from __future__ import annotations

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import get_settings

_engine = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def get_engine():
    global _engine, _session_factory
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(settings.database_url, echo=False)
        _session_factory = async_sessionmaker(_engine, expire_on_commit=False)
    return _engine


def session_factory() -> async_sessionmaker[AsyncSession]:
    get_engine()
    assert _session_factory is not None
    return _session_factory


async def get_session() -> AsyncIterator[AsyncSession]:
    async with session_factory()() as session:
        yield session


async def init_db() -> None:
    """Create tables if missing (dev convenience; alembic owns real migrations)."""
    from app.models import Base

    engine = get_engine()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def reset_engine() -> None:
    """Test helper: force re-creation of the engine after settings change."""
    global _engine, _session_factory
    _engine = None
    _session_factory = None
