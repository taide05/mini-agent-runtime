from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator, Generator
from typing import Any
from unittest.mock import AsyncMock, MagicMock
from uuid import uuid4

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import create_app


TEST_DB_URL = "postgresql+psycopg2://agent:agent@localhost:5432/agent_runtime_test"


@pytest.fixture(scope="session")
def engine():
    eng = create_engine(TEST_DB_URL)
    Base.metadata.create_all(bind=eng)
    yield eng
    Base.metadata.drop_all(bind=eng)


@pytest.fixture
def db_session(engine) -> Generator:
    SessionLocal = sessionmaker(bind=engine)
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@pytest_asyncio.fixture
async def client(db_session) -> AsyncGenerator[AsyncClient, None]:
    app = create_app()

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def sample_session_id() -> str:
    return str(uuid4())
