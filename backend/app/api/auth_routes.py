"""
Authentication endpoints: login, register, Google OAuth, profile.

POST  /api/auth/register – create new user (requires admin approval)
POST  /api/auth/login    – email + password login → JWT
POST  /api/auth/google   – Google id_token login → JWT
GET   /api/auth/me       – get current user profile
PATCH /api/auth/me       – update current user profile (OpenRouter token)
"""

from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import create_access_token, hash_password, verify_password, get_current_user
from app.database import get_db
from app.models import User, AppSettings
from app.schemas import LoginRequest, TokenResponse, UserCreate, GoogleLoginRequest, UserRead

router = APIRouter(prefix="/api/auth", tags=["auth"])


async def get_app_settings(db: AsyncSession) -> AppSettings:
    """Get or create the default AppSettings row.

    Args:
        db: Async database session.

    Returns:
        AppSettings: The singleton settings row (created with defaults if missing).
    """
    result = await db.execute(select(AppSettings).where(AppSettings.key == "default"))
    settings = result.scalar_one_or_none()
    if not settings:
        settings = AppSettings(key="default")
        db.add(settings)
        await db.commit()
        await db.refresh(settings)
    return settings


@router.post("/register", response_model=TokenResponse, status_code=201)
async def register(body: UserCreate, db: AsyncSession = Depends(get_db)):
    """Register a new user account.

    Checks that registration is enabled in app settings.
    Auto-approves the user if ``require_approval`` is disabled.

    Args:
        body: UserCreate schema with email and password (min 8 chars).
        db: Async database session (injected).

    Returns:
        TokenResponse: JWT access token for the newly created user.

    Raises:
        HTTPException 403: Registration is disabled.
        HTTPException 409: Email already registered.
    """
    # Check if registration is enabled
    app_settings = await get_app_settings(db)
    if not app_settings.registration_enabled:
        raise HTTPException(status_code=403, detail="Registration is currently disabled")
    
    existing = await db.execute(select(User).where(User.email == body.email))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=409, detail="Email already registered")

    # Auto-approve if require_approval is disabled
    auto_approve = not app_settings.require_approval
    
    user = User(
        email=body.email,
        hashed_password=hash_password(body.password),
        is_approved=auto_approve,
    )
    db.add(user)
    await db.commit()
    await db.refresh(user)
    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(access_token=token)


@router.post("/login", response_model=TokenResponse)
async def login(body: LoginRequest, db: AsyncSession = Depends(get_db)):
    """Authenticate a user with email and password.

    Args:
        body: LoginRequest with email and password.
        db: Async database session (injected).

    Returns:
        TokenResponse: JWT access token.

    Raises:
        HTTPException 401: Invalid email or password.
        HTTPException 403: Account is disabled by admin.
    """
    result = await db.execute(select(User).where(User.email == body.email))
    user = result.scalar_one_or_none()
    if not user or not user.hashed_password or not verify_password(body.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Invalid credentials")
    if not user.is_active:
        raise HTTPException(status_code=403, detail="Account disabled")
    token = create_access_token({"sub": str(user.id)})
    return TokenResponse(access_token=token)


# ── Profile endpoints ────────────────────────────────────────────────────────

class ProfileUpdate(BaseModel):
    """Fields a user can update in their profile."""
    openrouter_api_token: Optional[str] = None


class ProfileResponse(BaseModel):
    """User profile data (safe to expose to the user)."""
    id: str
    email: str
    openrouter_api_token: Optional[str] = None  # Masked
    has_openrouter_token: bool
    gdpr_consent_at: Optional[str] = None
    created_at: str


@router.get("/me", response_model=ProfileResponse)
async def get_profile(current_user: User = Depends(get_current_user)):
    """Get the authenticated user's profile.

    Args:
        current_user: User ORM object (injected via JWT dependency).

    Returns:
        ProfileResponse: User profile with masked API token and timestamps.
    """
    return ProfileResponse(
        id=str(current_user.id),
        email=current_user.email,
        openrouter_api_token="sk-or-***" if current_user.openrouter_api_token else None,
        has_openrouter_token=current_user.openrouter_api_token is not None,
        gdpr_consent_at=current_user.gdpr_consent_at.isoformat() if current_user.gdpr_consent_at else None,
        created_at=current_user.created_at.isoformat() if current_user.created_at else "",
    )


@router.patch("/me", response_model=ProfileResponse)
async def update_profile(
    body: ProfileUpdate,
    current_user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Update the authenticated user's profile settings.

    Currently supports updating the OpenRouter API token.
    Sending an empty string or "null" removes the token.

    Args:
        body: ProfileUpdate with optional openrouter_api_token.
        current_user: User ORM object (injected via JWT dependency).
        db: Async database session (injected).

    Returns:
        ProfileResponse: Updated user profile.

    Raises:
        HTTPException 400: Invalid OpenRouter token format (must start with 'sk-or-').
    """
    # Handle explicit null to remove token
    if body.openrouter_api_token is not None:
        if body.openrouter_api_token == "" or body.openrouter_api_token.lower() == "null":
            current_user.openrouter_api_token = None
        else:
            # Validate token format (basic check)
            if not body.openrouter_api_token.startswith("sk-or-"):
                raise HTTPException(400, "Invalid OpenRouter token format. Should start with 'sk-or-'")
            current_user.openrouter_api_token = body.openrouter_api_token
    
    await db.commit()
    await db.refresh(current_user)
    
    return ProfileResponse(
        id=str(current_user.id),
        email=current_user.email,
        openrouter_api_token="sk-or-***" if current_user.openrouter_api_token else None,
        has_openrouter_token=current_user.openrouter_api_token is not None,
        gdpr_consent_at=current_user.gdpr_consent_at.isoformat() if current_user.gdpr_consent_at else None,
        created_at=current_user.created_at.isoformat() if current_user.created_at else "",
    )
