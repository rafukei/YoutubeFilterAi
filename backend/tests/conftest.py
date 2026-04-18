"""
Pytest fixtures for testing YoutubeFilterAi backend.

Provides:
- Test database (SQLite in-memory for speed)
- Mock Redis client
- FastAPI AsyncClient with dependency overrides
- Pre-configured test users (regular + admin)
"""

import asyncio
from typing import AsyncGenerator, Generator
from unittest.mock import AsyncMock, MagicMock

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.main import app
from app.database import Base, get_db
from app.auth import create_access_token, hash_password
from app.models import User
from app.config import get_settings

# Use SQLite for tests
TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture(scope="session")
def event_loop():
    """Create event loop for async tests."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="function")
async def test_engine():
    """Create async test database engine."""
    engine = create_async_engine(
        TEST_DATABASE_URL,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def test_session(test_engine) -> AsyncGenerator[AsyncSession, None]:
    """Create test database session."""
    async_session = async_sessionmaker(
        test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with async_session() as session:
        yield session


@pytest.fixture
def mock_redis():
    """Mock Redis client for rate limiting tests."""
    redis = AsyncMock()
    redis.get = AsyncMock(return_value=None)
    redis.incr = AsyncMock(return_value=1)
    redis.expire = AsyncMock()
    redis.pipeline = MagicMock(return_value=AsyncMock(
        incr=AsyncMock(),
        expire=AsyncMock(),
        execute=AsyncMock(return_value=[1, True])
    ))
    return redis


@pytest_asyncio.fixture
async def client(test_session, mock_redis) -> AsyncGenerator[AsyncClient, None]:
    """Create AsyncClient with overridden dependencies for async endpoint testing."""
    
    async def override_get_db() -> AsyncGenerator[AsyncSession, None]:
        """Override FastAPI's get_db dependency with test session."""
        yield test_session
    
    app.dependency_overrides[get_db] = override_get_db
    app.state.redis = mock_redis
    
    async with AsyncClient(app=app, base_url="http://test") as ac:
        yield ac
    
    app.dependency_overrides.clear()


@pytest_asyncio.fixture
async def test_user(test_session) -> User:
    """Create a test user in the database."""
    user = User(
        email="testuser@example.com",
        hashed_password=hash_password("testpassword123"),
        is_active=True,
        is_approved=True,
    )
    test_session.add(user)
    await test_session.commit()
    await test_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def unapproved_user(test_session) -> User:
    """Create an unapproved test user."""
    user = User(
        email="unapproved@example.com",
        hashed_password=hash_password("password123"),
        is_active=True,
        is_approved=False,
    )
    test_session.add(user)
    await test_session.commit()
    await test_session.refresh(user)
    return user


@pytest_asyncio.fixture
async def user_token(test_user) -> str:
    """Generate JWT token for test user."""
    return create_access_token({"sub": str(test_user.id)})


@pytest.fixture
def admin_token() -> str:
    """Generate JWT token for admin."""
    return create_access_token({"sub": "admin", "is_admin": True})


@pytest_asyncio.fixture
async def auth_headers(user_token) -> dict:
    """Authorization headers for regular user."""
    # Note: This implicitly depends on test_user through user_token
    return {"Authorization": f"Bearer {user_token}"}


@pytest.fixture
def admin_headers(admin_token) -> dict:
    """Authorization headers for admin."""
    return {"Authorization": f"Bearer {admin_token}"}
