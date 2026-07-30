"""Shared pytest fixtures.

Sets DATABASE_URL to a dedicated SQLite test file *before* any app module is
imported, so the engine app.database.session builds points at the test
database rather than whatever `.env` configures for local dev.
"""

import os
from pathlib import Path

TEST_DB_PATH = Path(__file__).parent / "test_supply_chain.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{TEST_DB_PATH}"
os.environ["APP_ENV"] = "test"

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings

get_settings.cache_clear()

from app.database import session as db_session_module  # noqa: E402
from app.database.base import Base  # noqa: E402
from app.models import entities  # noqa: E402,F401 (registers all tables on Base.metadata)


requires_llm_configured = pytest.mark.skipif(
    not (
        get_settings().groq_api_key
        or get_settings().gemini_api_key
        or get_settings().llm_provider == "ollama"
    ),
    reason="requires a real GROQ_API_KEY or GEMINI_API_KEY, or LLM_PROVIDER=ollama with a "
    "local Ollama server running (this test calls the configured reasoning engine - see "
    "app/core/llm.py)",
)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _prepare_test_database():
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()

    async with db_session_module.engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    yield

    await db_session_module.engine.dispose()
    if TEST_DB_PATH.exists():
        TEST_DB_PATH.unlink()


@pytest_asyncio.fixture
async def db_session() -> AsyncSession:
    """A session bound to a single connection/transaction, rolled back after the test."""
    async with db_session_module.engine.connect() as conn:
        trans = await conn.begin()
        session_factory = async_sessionmaker(bind=conn, class_=AsyncSession, expire_on_commit=False)
        session = session_factory()
        try:
            yield session
        finally:
            await session.close()
            if trans.is_active:
                await trans.rollback()


@pytest_asyncio.fixture
async def committed_db():
    """Commits real rows on the shared engine/session factory.

    Needed for anything (like the Master Data Agent, which opens its own
    session per graph run) that reads through a *different* connection than
    the test's — data must actually be committed to be visible there, unlike
    the `db_session` fixture's roll-back-at-teardown transaction. Cleans up
    by deleting every row it created.
    """
    from sqlalchemy import delete

    from app.database.session import AsyncSessionLocal
    from app.models.entities import (
        DemandHistory,
        DistanceMatrix,
        Fleet,
        Inventory,
        Product,
        Shipment,
        Store,
        Terminal,
    )

    yield AsyncSessionLocal

    async with AsyncSessionLocal() as session:
        for model in (Shipment, DistanceMatrix, DemandHistory, Inventory, Fleet, Product, Terminal, Store):
            await session.execute(delete(model))
        await session.commit()
