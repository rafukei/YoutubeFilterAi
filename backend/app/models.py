"""
SQLAlchemy ORM models – single source of truth for the DB schema.

Tables:
    users          – credentials, role, GDPR consent timestamp
    prompts        – user-created prompt templates (tree/folder structure)
    youtube_channels – channels a user follows
    telegram_bots  – per-user Telegram bot config
    web_views      – named web summary pages per user
    messages       – AI-generated summaries linked to prompts & sources
"""

import uuid
from datetime import datetime

from sqlalchemy import (
    Boolean, Column, DateTime, Enum as SAEnum, ForeignKey,
    Integer, String, Text, UniqueConstraint,
)
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import relationship

from app.database import Base


# ── Users ────────────────────────────────────────────────────────────────────

class User(Base):
    """Application user. Passwords are bcrypt-hashed; Google users have google_id set."""
    __tablename__ = "users"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    email = Column(String(320), unique=True, nullable=False, index=True)
    hashed_password = Column(String(128), nullable=True)  # null for Google-only users
    google_id = Column(String(64), unique=True, nullable=True)
    is_active = Column(Boolean, default=True)
    is_approved = Column(Boolean, default=False)  # admin must approve
    openrouter_api_token = Column(String(256), nullable=True)
    gdpr_consent_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    prompts = relationship("Prompt", back_populates="owner", cascade="all, delete-orphan")
    channels = relationship("YouTubeChannel", back_populates="owner", cascade="all, delete-orphan")
    telegram_bots = relationship("TelegramBot", back_populates="owner", cascade="all, delete-orphan")
    web_views = relationship("WebView", back_populates="owner", cascade="all, delete-orphan")
    messages = relationship("Message", back_populates="owner", cascade="all, delete-orphan")


# ── Prompts ──────────────────────────────────────────────────────────────────

class Prompt(Base):
    """
    User-created prompt template. Supports folder/tree via parent_id.
    The body MUST end with the JSON routing block (telegram_bots, web_views, visibility).
    Each prompt can use a different AI model from OpenRouter.
    """
    __tablename__ = "prompts"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    parent_id = Column(UUID(as_uuid=True), ForeignKey("prompts.id", ondelete="SET NULL"), nullable=True)
    name = Column(String(200), nullable=False)
    is_folder = Column(Boolean, default=False)
    body = Column(Text, nullable=True)  # null for folders
    ai_model = Column(String(128), nullable=True, default="openai/gpt-3.5-turbo")  # OpenRouter model ID
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    owner = relationship("User", back_populates="prompts")
    children = relationship("Prompt", backref="parent", remote_side=[id])


# ── YouTube Channels ─────────────────────────────────────────────────────────

class YouTubeChannel(Base):
    """
    A YouTube channel the user follows for transcript processing.
    Includes scheduling for automatic video checking.
    """
    __tablename__ = "youtube_channels"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    channel_id = Column(String(64), nullable=False)  # YouTube channel ID
    channel_name = Column(String(200), nullable=False)
    
    # Scheduling settings
    check_interval_minutes = Column(Integer, default=60)  # How often to check for new videos
    is_active = Column(Boolean, default=True)  # Enable/disable monitoring
    last_checked_at = Column(DateTime, nullable=True)  # When was last checked
    last_video_id = Column(String(64), nullable=True)  # Last processed video ID
    
    # Processing settings
    prompt_id = Column(UUID(as_uuid=True), ForeignKey("prompts.id", ondelete="SET NULL"), nullable=True)  # Which prompt to use
    
    added_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="channels")
    prompt = relationship("Prompt")

    __table_args__ = (UniqueConstraint("user_id", "channel_id", name="uq_user_channel"),)


# ── Telegram Bots ────────────────────────────────────────────────────────────

class TelegramBot(Base):
    """Per-user Telegram bot. The user provides their own BotFather token."""
    __tablename__ = "telegram_bots"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    bot_name = Column(String(100), nullable=False)
    bot_token = Column(String(256), nullable=False)  # encrypted at rest in prod
    chat_id = Column(String(64), nullable=True)  # target chat/channel
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="telegram_bots")


# ── Web Views ────────────────────────────────────────────────────────────────

class WebView(Base):
    """Named web summary page where AI messages are displayed."""
    __tablename__ = "web_views"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    name = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="web_views")
    messages = relationship("Message", back_populates="web_view", cascade="all, delete-orphan")

    __table_args__ = (UniqueConstraint("user_id", "name", name="uq_user_webview"),)


# ── Messages ─────────────────────────────────────────────────────────────────

class Message(Base):
    """
    AI-generated summary/compilation message.
    Always stores the source video URL so the user can verify.
    """
    __tablename__ = "messages"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    user_id = Column(UUID(as_uuid=True), ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    web_view_id = Column(UUID(as_uuid=True), ForeignKey("web_views.id", ondelete="SET NULL"), nullable=True)
    prompt_id = Column(UUID(as_uuid=True), ForeignKey("prompts.id", ondelete="SET NULL"), nullable=True)
    source_video_url = Column(String(512), nullable=False)
    source_video_title = Column(String(500), nullable=True)
    transcript_text = Column(Text, nullable=True)  # raw transcript (for test page)
    ai_response = Column(Text, nullable=False)
    visibility = Column(Boolean, default=True)
    sent_to_telegram = Column(Boolean, default=False)
    created_at = Column(DateTime, default=datetime.utcnow)

    owner = relationship("User", back_populates="messages")
    web_view = relationship("WebView", back_populates="messages")


# ── App Settings ─────────────────────────────────────────────────────────────

class AppSettings(Base):
    """
    Runtime application settings stored in database.
    Singleton table (only one row with key='default').
    Allows admin to toggle features without restarting the app.
    """
    __tablename__ = "app_settings"

    key = Column(String(50), primary_key=True, default="default")
    registration_enabled = Column(Boolean, default=True)
    require_approval = Column(Boolean, default=True)
    allow_gmail_auth = Column(Boolean, default=False)
    google_client_id = Column(String(256), nullable=True)
    google_client_secret = Column(String(256), nullable=True)
    openrouter_rate_limit = Column(Integer, default=10)  # requests per minute
    channel_request_delay = Column(Integer, default=5)  # seconds between YouTube requests
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
