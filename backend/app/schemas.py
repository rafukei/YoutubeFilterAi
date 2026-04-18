"""
Pydantic schemas for request/response validation.

Naming convention:
    <Entity>Create  – POST body
    <Entity>Update  – PATCH body
    <Entity>Read    – response model (includes id, timestamps)
"""

from datetime import datetime
from typing import Optional
from uuid import UUID

from pydantic import BaseModel, EmailStr, Field


# ── Auth ─────────────────────────────────────────────────────────────────────

class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class LoginRequest(BaseModel):
    email: EmailStr
    password: str


class GoogleLoginRequest(BaseModel):
    id_token: str


class AdminLoginRequest(BaseModel):
    """Admin login payload (username + password from .env)."""
    username: str
    password: str


# ── User ─────────────────────────────────────────────────────────────────────

class UserCreate(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8)


class UserRead(BaseModel):
    id: UUID
    email: EmailStr
    is_active: bool
    is_approved: bool
    openrouter_api_token: Optional[str] = None
    gdpr_consent_at: Optional[datetime] = None
    created_at: datetime

    class Config:
        from_attributes = True


class UserUpdate(BaseModel):
    openrouter_api_token: Optional[str] = None
    gdpr_consent_at: Optional[datetime] = None


# ── Prompt ───────────────────────────────────────────────────────────────────

class PromptCreate(BaseModel):
    name: str = Field(max_length=200)
    parent_id: Optional[UUID] = None
    is_folder: bool = False
    body: Optional[str] = None
    ai_model: Optional[str] = "openai/gpt-3.5-turbo"
    fallback_ai_model: Optional[str] = None


class PromptRead(BaseModel):
    id: UUID
    name: str
    parent_id: Optional[UUID]
    is_folder: bool
    body: Optional[str]
    ai_model: Optional[str]
    fallback_ai_model: Optional[str]
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True


class PromptUpdate(BaseModel):
    name: Optional[str] = None
    parent_id: Optional[UUID] = None
    body: Optional[str] = None
    ai_model: Optional[str] = None
    fallback_ai_model: Optional[str] = None


# ── YouTube Channel ──────────────────────────────────────────────────────────

class YouTubeChannelCreate(BaseModel):
    channel_id: str = Field(max_length=64)
    channel_name: str = Field(max_length=200)
    check_interval_minutes: int = Field(default=60, ge=5, le=1440)  # 5min to 24h
    prompt_id: Optional[UUID] = None


class YouTubeChannelRead(BaseModel):
    id: UUID
    channel_id: str
    channel_name: str
    check_interval_minutes: int
    is_active: bool
    last_checked_at: Optional[datetime]
    last_video_id: Optional[str]
    prompt_id: Optional[UUID]
    added_at: datetime

    class Config:
        from_attributes = True


class YouTubeChannelUpdate(BaseModel):
    channel_name: Optional[str] = None
    check_interval_minutes: Optional[int] = Field(default=None, ge=5, le=1440)
    is_active: Optional[bool] = None
    prompt_id: Optional[UUID] = None


# ── Telegram Bot ─────────────────────────────────────────────────────────────

class TelegramBotCreate(BaseModel):
    bot_name: Optional[str] = Field(default=None, max_length=100)
    bot_token: str
    chat_id: Optional[str] = None


class TelegramBotRead(BaseModel):
    id: UUID
    bot_name: str
    chat_id: Optional[str]
    created_at: datetime

    class Config:
        from_attributes = True


# ── Web View ─────────────────────────────────────────────────────────────────

class WebViewCreate(BaseModel):
    name: str = Field(max_length=100)


class WebViewRead(BaseModel):
    id: UUID
    name: str
    created_at: datetime

    class Config:
        from_attributes = True


# ── Message ──────────────────────────────────────────────────────────────────

class MessageRead(BaseModel):
    id: UUID
    source_video_url: str
    source_video_title: Optional[str]
    transcript_text: Optional[str]
    ai_response: str
    visibility: bool
    sent_to_telegram: bool
    created_at: datetime

    class Config:
        from_attributes = True


# ── Process request (Test page / normal flow) ────────────────────────────────

class ProcessVideoRequest(BaseModel):
    """Submit a YouTube video URL + prompt for AI processing."""
    video_url: str
    prompt_id: Optional[UUID] = None  # use saved prompt
    prompt_text: Optional[str] = None  # or ad-hoc prompt text (test page)


class ProcessVideoResponse(BaseModel):
    """Result of AI processing."""
    message: MessageRead
    raw_transcript: str


# ── App Settings (Admin) ─────────────────────────────────────────────────────

class AppSettingsRead(BaseModel):
    """Current application settings (safe to expose to admin)."""
    registration_enabled: bool
    require_approval: bool
    allow_gmail_auth: bool
    google_client_id: Optional[str] = None  # Masked for security
    openrouter_rate_limit: int
    channel_request_delay: int = 5
    max_message_history: int = 1000
    updated_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class AppSettingsUpdate(BaseModel):
    """Fields admin can update."""
    registration_enabled: Optional[bool] = None
    require_approval: Optional[bool] = None
    allow_gmail_auth: Optional[bool] = None
    google_client_id: Optional[str] = None
    google_client_secret: Optional[str] = None
    openrouter_rate_limit: Optional[int] = None
    channel_request_delay: Optional[int] = None
    max_message_history: Optional[int] = None


# ── Admin Stats ──────────────────────────────────────────────────────────────

class AdminStatsResponse(BaseModel):
    """System statistics for admin dashboard."""
    total_users: int
    active_users: int
    approved_users: int
    pending_approval: int
    total_prompts: int
    total_messages: int
    total_channels: int
    total_bots: int


# ── User Data Export ─────────────────────────────────────────────────────────

class UserDataExport(BaseModel):
    """Complete export of user's prompts and channel subscriptions."""
    exported_at: datetime
    email: str
    prompts: list[PromptRead]
    channels: list[YouTubeChannelRead]


class UserDataImport(BaseModel):
    """Import payload for user's prompts and channel subscriptions."""
    prompts: list[PromptCreate] = []
    channels: list[YouTubeChannelCreate] = []


class ImportResult(BaseModel):
    """Result of a data import operation."""
    prompts_imported: int
    channels_imported: int
    prompts_skipped: int
    channels_skipped: int
