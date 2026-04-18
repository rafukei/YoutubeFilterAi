"""
Async SQLAlchemy engine & session factory.

Usage:
    from app.database import get_db
    async def my_endpoint(db: AsyncSession = Depends(get_db)): ...
"""

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings

settings = get_settings()

engine = create_async_engine(settings.DATABASE_URL, echo=settings.DEBUG, future=True)

async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


class Base(DeclarativeBase):
    """Declarative base for all ORM models."""
    pass


async def get_db() -> AsyncSession:
    """FastAPI dependency that provides an async database session.

    Yields an AsyncSession, auto-commits on success and rolls back
    on exception. The session is always closed after use.

    Yields:
        AsyncSession: Active database session bound to the async engine.

    Raises:
        Exception: Re-raises any exception after rolling back the transaction.
    """
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()
