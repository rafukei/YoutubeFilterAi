"""
Admin-only endpoints (authenticated via .env ADMIN_USERNAME / ADMIN_PASSWORD).

POST  /api/admin/login   – admin login → JWT with admin claim
GET   /api/admin/users   – list all users
POST  /api/admin/users   – create new user
PATCH /api/admin/users/{id} – approve/deactivate users
DELETE /api/admin/users/{id} – delete user (GDPR)
GET   /api/admin/settings – read app settings
PATCH /api/admin/settings – update app settings
GET   /api/admin/stats   – system statistics
"""

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, update, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token, verify_password, oauth2_scheme, hash_password
from app.config import get_settings
from app.database import get_db
from app.models import User, AppSettings, Prompt, Message, YouTubeChannel, TelegramBot
from app.schemas import (
    AdminLoginRequest, TokenResponse, UserRead, UserCreate,
    AppSettingsRead, AppSettingsUpdate, AdminStatsResponse
)

from jose import jwt, JWTError

router = APIRouter(prefix="/api/admin", tags=["admin"])
settings = get_settings()


async def get_admin(token: str = Depends(oauth2_scheme)):
    """FastAPI dependency: verify the JWT contains the ``is_admin`` claim.

    Args:
        token: Bearer token from Authorization header (injected).

    Raises:
        HTTPException 403: Token is valid but missing admin claim.
        HTTPException 401: Token is invalid or expired.
    """
    try:
        payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        if not payload.get("is_admin"):
            raise HTTPException(status_code=403, detail="Admin access required")
    except JWTError:
        raise HTTPException(status_code=401, detail="Invalid token")


@router.post("/login", response_model=TokenResponse)
async def admin_login(body: AdminLoginRequest):
    """Authenticate as admin using credentials from environment variables.

    Compares against ADMIN_USERNAME and ADMIN_PASSWORD from ``.env``.
    Returns a JWT with ``is_admin: true`` claim.

    Args:
        body: AdminLoginRequest with username and password.

    Returns:
        TokenResponse: JWT access token with admin claim.

    Raises:
        HTTPException 401: Invalid admin credentials.
    """
    if body.username != settings.ADMIN_USERNAME or body.password != settings.ADMIN_PASSWORD:
        raise HTTPException(status_code=401, detail="Invalid admin credentials")
    token = create_access_token({"sub": "admin", "is_admin": True})
    return TokenResponse(access_token=token)


@router.get("/users", response_model=list[UserRead], dependencies=[Depends(get_admin)])
async def list_users(db: AsyncSession = Depends(get_db)):
    """List all registered users ordered by creation date.

    Args:
        db: Async database session (injected).

    Returns:
        list[UserRead]: All users with profile info, approval status, and timestamps.
    """
    result = await db.execute(select(User).order_by(User.created_at))
    return result.scalars().all()


@router.post("/users", response_model=UserRead, status_code=201, dependencies=[Depends(get_admin)])
async def create_user(body: UserCreate, db: AsyncSession = Depends(get_db)):
    """Create a new user as admin (pre-approved and active).

    Args:
        body: UserCreate with email and password (min 8 chars).
        db: Async database session (injected).

    Returns:
        UserRead: The newly created, pre-approved user.

    Raises:
        HTTPException 409: Email already registered.
    """
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")
    
    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        is_approved=True,  # Admin-created users are pre-approved
        is_active=True,
    )
    db.add(user)
    await db.flush()
    await db.refresh(user)
    return user


@router.delete("/users/{user_id}", status_code=204, dependencies=[Depends(get_admin)])
async def delete_user(user_id: UUID, db: AsyncSession = Depends(get_db)):
    """Delete a user and all associated data (GDPR-compliant cascade delete).

    Removes the user and all their prompts, channels, bots, web views, and messages.

    Args:
        user_id: UUID of the user to delete.
        db: Async database session (injected).

    Raises:
        HTTPException 404: User not found.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    await db.delete(user)
    await db.commit()


@router.patch("/users/{user_id}", response_model=UserRead, dependencies=[Depends(get_admin)])
async def update_user(user_id: UUID, is_approved: bool | None = None, is_active: bool | None = None, db: AsyncSession = Depends(get_db)):
    """Update a user's approval or active status.

    Args:
        user_id: UUID of the user to update.
        is_approved: Set to True to approve the user's account.
        is_active: Set to False to deactivate the user.
        db: Async database session (injected).

    Returns:
        UserRead: The updated user.

    Raises:
        HTTPException 404: User not found.
    """
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        raise HTTPException(404, "User not found")
    if is_approved is not None:
        user.is_approved = is_approved
    if is_active is not None:
        user.is_active = is_active
    await db.flush()
    await db.refresh(user)
    return user


@router.get("/settings", response_model=AppSettingsRead, dependencies=[Depends(get_admin)])
async def get_app_settings(db: AsyncSession = Depends(get_db)):
    """Return current application settings.

    Creates default settings row if not yet initialized.
    Sensitive fields (Google client ID) are masked in the response.

    Args:
        db: Async database session (injected).

    Returns:
        AppSettingsRead: Current settings with masked secrets.
    """
    result = await db.execute(select(AppSettings).where(AppSettings.key == "default"))
    app_settings = result.scalar_one_or_none()
    
    # Create default settings if not exists
    if not app_settings:
        app_settings = AppSettings(
            key="default",
            registration_enabled=True,
            require_approval=True,
            allow_gmail_auth=settings.ALLOW_GMAIL_AUTH,
            google_client_id=settings.GOOGLE_CLIENT_ID,
            openrouter_rate_limit=settings.OPENROUTER_FREE_RPM,
        )
        db.add(app_settings)
        await db.commit()
        await db.refresh(app_settings)
    
    # Mask sensitive data
    masked_client_id = None
    if app_settings.google_client_id:
        masked_client_id = app_settings.google_client_id[:8] + "..." if len(app_settings.google_client_id) > 8 else "***"
    
    return AppSettingsRead(
        registration_enabled=app_settings.registration_enabled,
        require_approval=app_settings.require_approval,
        allow_gmail_auth=app_settings.allow_gmail_auth,
        google_client_id=masked_client_id,
        openrouter_rate_limit=app_settings.openrouter_rate_limit,
        updated_at=app_settings.updated_at,
    )


@router.patch("/settings", response_model=AppSettingsRead, dependencies=[Depends(get_admin)])
async def update_app_settings(body: AppSettingsUpdate, db: AsyncSession = Depends(get_db)):
    """Update application settings (partial update).

    Only fields included in the request body are changed.
    Creates default settings row if not yet initialized.

    Args:
        body: AppSettingsUpdate with optional fields to change.
        db: Async database session (injected).

    Returns:
        AppSettingsRead: Updated settings with masked secrets.
    """
    result = await db.execute(select(AppSettings).where(AppSettings.key == "default"))
    app_settings = result.scalar_one_or_none()
    
    # Create default settings if not exists
    if not app_settings:
        app_settings = AppSettings(key="default")
        db.add(app_settings)
    
    # Update only provided fields
    if body.registration_enabled is not None:
        app_settings.registration_enabled = body.registration_enabled
    if body.require_approval is not None:
        app_settings.require_approval = body.require_approval
    if body.allow_gmail_auth is not None:
        app_settings.allow_gmail_auth = body.allow_gmail_auth
    if body.google_client_id is not None:
        app_settings.google_client_id = body.google_client_id
    if body.google_client_secret is not None:
        app_settings.google_client_secret = body.google_client_secret
    if body.openrouter_rate_limit is not None:
        app_settings.openrouter_rate_limit = body.openrouter_rate_limit
    
    await db.commit()
    await db.refresh(app_settings)
    
    # Mask sensitive data for response
    masked_client_id = None
    if app_settings.google_client_id:
        masked_client_id = app_settings.google_client_id[:8] + "..." if len(app_settings.google_client_id) > 8 else "***"
    
    return AppSettingsRead(
        registration_enabled=app_settings.registration_enabled,
        require_approval=app_settings.require_approval,
        allow_gmail_auth=app_settings.allow_gmail_auth,
        google_client_id=masked_client_id,
        openrouter_rate_limit=app_settings.openrouter_rate_limit,
        updated_at=app_settings.updated_at,
    )


@router.get("/stats", response_model=AdminStatsResponse, dependencies=[Depends(get_admin)])
async def get_admin_stats(db: AsyncSession = Depends(get_db)):
    """Return system-wide statistics for the admin dashboard.

    Args:
        db: Async database session (injected).

    Returns:
        AdminStatsResponse: Counts of users (total, active, approved, pending),
            prompts, messages, channels, and Telegram bots.
    """
    # User counts
    total_users = await db.scalar(select(func.count(User.id)))
    active_users = await db.scalar(select(func.count(User.id)).where(User.is_active == True))
    approved_users = await db.scalar(select(func.count(User.id)).where(User.is_approved == True))
    pending_approval = await db.scalar(
        select(func.count(User.id)).where(User.is_active == True, User.is_approved == False)
    )
    
    # Resource counts
    total_prompts = await db.scalar(select(func.count(Prompt.id)))
    total_messages = await db.scalar(select(func.count(Message.id)))
    total_channels = await db.scalar(select(func.count(YouTubeChannel.id)))
    total_bots = await db.scalar(select(func.count(TelegramBot.id)))
    
    return AdminStatsResponse(
        total_users=total_users or 0,
        active_users=active_users or 0,
        approved_users=approved_users or 0,
        pending_approval=pending_approval or 0,
        total_prompts=total_prompts or 0,
        total_messages=total_messages or 0,
        total_channels=total_channels or 0,
        total_bots=total_bots or 0,
    )
