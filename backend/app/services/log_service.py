"""
Activity logging service for user-visible monitoring.

Provides a simple async helper to write structured log entries
to the activity_logs table. These logs are displayed in the
user's Logs page for monitoring application behavior.

Functions:
    log_activity(db, user_id, level, source, message, details) -> None
"""

from typing import Optional
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivityLog


async def log_activity(
    db: AsyncSession,
    user_id: UUID,
    level: str,
    source: str,
    message: str,
    details: Optional[str] = None,
) -> None:
    """Write a structured log entry to the database.

    Args:
        db: Async database session.
        user_id: UUID of the user this log belongs to.
        level: Log level – "DEBUG", "INFO", "WARNING", or "ERROR".
        source: Component name – e.g. "ai", "telegram", "transcript", "scheduler".
        message: Human-readable log message.
        details: Optional extra context (JSON string, traceback, etc.).

    Returns:
        None
    """
    entry = ActivityLog(
        user_id=user_id,
        level=level.upper(),
        source=source,
        message=message,
        details=details,
    )
    db.add(entry)
    # Don't commit here — let the caller's transaction handle it.
    # Use merge/flush if needed for immediate visibility.
    try:
        await db.flush()
    except Exception:
        pass  # Never let logging break the main flow
