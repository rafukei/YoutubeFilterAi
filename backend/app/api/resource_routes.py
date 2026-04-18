"""
CRUD endpoints for user resources: prompts, channels, telegram bots, web views.

All endpoints require a valid JWT (get_current_user dependency).
"""

from uuid import UUID
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import Prompt, YouTubeChannel, TelegramBot, WebView, User
from app.schemas import (
    PromptCreate, PromptRead, PromptUpdate,
    YouTubeChannelCreate, YouTubeChannelRead, YouTubeChannelUpdate,
    TelegramBotCreate, TelegramBotRead,
    WebViewCreate, WebViewRead,
    UserDataExport, UserDataImport, ImportResult,
)
from app.services.ai_service import get_available_models

router = APIRouter(prefix="/api", tags=["resources"])


# ── Prompts ──────────────────────────────────────────────────────────────────

@router.get("/prompts", response_model=list[PromptRead])
async def list_prompts(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """List all prompts and folders for the authenticated user, ordered by name.

    Args:
        user: Current authenticated user (injected via JWT).
        db: Async database session (injected).

    Returns:
        list[PromptRead]: All user's prompts/folders sorted alphabetically.
    """
    result = await db.execute(select(Prompt).where(Prompt.user_id == user.id).order_by(Prompt.name))
    return result.scalars().all()


@router.post("/prompts", response_model=PromptRead, status_code=201)
async def create_prompt(body: PromptCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Create a new prompt template or folder.

    Args:
        body: PromptCreate with name, optional parent_id, is_folder flag, body text, and ai_model.
        user: Current authenticated user (injected via JWT).
        db: Async database session (injected).

    Returns:
        PromptRead: The newly created prompt/folder with generated id and timestamps.
    """
    prompt = Prompt(user_id=user.id, **body.model_dump())
    db.add(prompt)
    await db.commit()
    await db.refresh(prompt)
    return prompt


@router.patch("/prompts/{prompt_id}", response_model=PromptRead)
async def update_prompt(prompt_id: UUID, body: PromptUpdate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Update an existing prompt's name, body, parent, or AI model.

    Only fields included in the request body are updated (partial update).

    Args:
        prompt_id: UUID of the prompt to update.
        body: PromptUpdate with optional name, parent_id, body, ai_model.
        user: Current authenticated user (injected via JWT).
        db: Async database session (injected).

    Returns:
        PromptRead: The updated prompt.

    Raises:
        HTTPException 404: Prompt not found or not owned by the user.
    """
    result = await db.execute(select(Prompt).where(Prompt.id == prompt_id, Prompt.user_id == user.id))
    prompt = result.scalar_one_or_none()
    if not prompt:
        raise HTTPException(404, "Prompt not found")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(prompt, field, value)
    await db.commit()
    await db.refresh(prompt)
    return prompt


@router.delete("/prompts/{prompt_id}", status_code=204)
async def delete_prompt(prompt_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Delete a prompt or folder permanently.

    Args:
        prompt_id: UUID of the prompt to delete.
        user: Current authenticated user (injected via JWT).
        db: Async database session (injected).

    Raises:
        HTTPException 404: Prompt not found or not owned by the user.
    """
    result = await db.execute(select(Prompt).where(Prompt.id == prompt_id, Prompt.user_id == user.id))
    prompt = result.scalar_one_or_none()
    if not prompt:
        raise HTTPException(404, "Prompt not found")
    await db.delete(prompt)
    await db.commit()


# ── YouTube Channels ─────────────────────────────────────────────────────────

@router.get("/channels", response_model=list[YouTubeChannelRead])
async def list_channels(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """List all YouTube channels the authenticated user is monitoring.

    Args:
        user: Current authenticated user (injected via JWT).
        db: Async database session (injected).

    Returns:
        list[YouTubeChannelRead]: All user's channels with scheduling info.
    """
    result = await db.execute(select(YouTubeChannel).where(YouTubeChannel.user_id == user.id))
    return result.scalars().all()


@router.post("/channels", response_model=YouTubeChannelRead, status_code=201)
async def add_channel(body: YouTubeChannelCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Add a new YouTube channel to monitor.

    The channel_id can be a real channel ID (UCxxxx) or an @handle.
    The scheduler will resolve handles to real IDs on first run.

    Args:
        body: YouTubeChannelCreate with channel_id, channel_name, check_interval, and optional prompt_id.
        user: Current authenticated user (injected via JWT).
        db: Async database session (injected).

    Returns:
        YouTubeChannelRead: The newly created channel subscription.
    """
    ch = YouTubeChannel(user_id=user.id, **body.model_dump())
    db.add(ch)
    await db.commit()
    await db.refresh(ch)
    return ch


@router.delete("/channels/{channel_db_id}", status_code=204)
async def remove_channel(channel_db_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Stop monitoring a YouTube channel and delete the subscription.

    Args:
        channel_db_id: UUID of the channel record (not the YouTube channel ID).
        user: Current authenticated user (injected via JWT).
        db: Async database session (injected).

    Raises:
        HTTPException 404: Channel not found or not owned by the user.
    """
    result = await db.execute(select(YouTubeChannel).where(YouTubeChannel.id == channel_db_id, YouTubeChannel.user_id == user.id))
    ch = result.scalar_one_or_none()
    if not ch:
        raise HTTPException(404, "Channel not found")
    await db.delete(ch)
    await db.commit()


# ── Telegram Bots ────────────────────────────────────────────────────────────

@router.get("/telegram-bots", response_model=list[TelegramBotRead])
async def list_bots(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """List all Telegram bots registered by the authenticated user.

    Args:
        user: Current authenticated user (injected via JWT).
        db: Async database session (injected).

    Returns:
        list[TelegramBotRead]: User's bots with name, chat_id, and creation time.
    """
    result = await db.execute(select(TelegramBot).where(TelegramBot.user_id == user.id))
    return result.scalars().all()


@router.post("/telegram-bots", response_model=TelegramBotRead, status_code=201)
async def create_bot(body: TelegramBotCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Register a new Telegram bot.

    Validates the bot token via Telegram's getMe API, auto-detects the bot
    username, and attempts to fetch the chat_id from recent messages.

    Args:
        body: TelegramBotCreate with bot_token (required), optional bot_name and chat_id.
        user: Current authenticated user (injected via JWT).
        db: Async database session (injected).

    Returns:
        TelegramBotRead: The registered bot with auto-detected name and chat_id.

    Raises:
        HTTPException 400: Invalid bot token (Telegram getMe failed).
    """
    from app.services.telegram_service import validate_bot_token, fetch_chat_id

    # Validate token and get bot info
    try:
        bot_info = await validate_bot_token(body.bot_token)
    except ValueError as e:
        raise HTTPException(400, str(e))

    bot_username = bot_info.get("username", bot_info.get("first_name", "unknown_bot"))

    # Auto-detect chat_id if not provided
    chat_id = body.chat_id
    if not chat_id:
        chat_id = await fetch_chat_id(body.bot_token)

    bot = TelegramBot(
        user_id=user.id,
        bot_name=body.bot_name or bot_username,
        bot_token=body.bot_token,
        chat_id=chat_id,
    )
    db.add(bot)
    await db.commit()
    await db.refresh(bot)
    return bot


@router.post("/telegram-bots/{bot_id}/refresh", response_model=TelegramBotRead)
async def refresh_bot_chat_id(bot_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Re-fetch the chat_id for a Telegram bot.

    The user should send /start to the bot in Telegram before calling this.

    Args:
        bot_id: UUID of the bot record.
        user: Current authenticated user (injected via JWT).
        db: Async database session (injected).

    Returns:
        TelegramBotRead: Updated bot with new chat_id.

    Raises:
        HTTPException 404: Bot not found, not owned by user, or no chat_id detected.
    """
    from app.services.telegram_service import fetch_chat_id

    result = await db.execute(select(TelegramBot).where(TelegramBot.id == bot_id, TelegramBot.user_id == user.id))
    bot = result.scalar_one_or_none()
    if not bot:
        raise HTTPException(404, "Bot not found")

    chat_id = await fetch_chat_id(bot.bot_token)
    if not chat_id:
        raise HTTPException(404, "Chat ID not found — send /start to the bot in Telegram first")

    bot.chat_id = chat_id
    await db.commit()
    await db.refresh(bot)
    return bot


@router.post("/telegram-bots/{bot_id}/test")
async def test_bot_message(bot_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Send a test message to verify the Telegram bot is configured correctly.

    Args:
        bot_id: UUID of the bot record.
        user: Current authenticated user (injected via JWT).
        db: Async database session (injected).

    Returns:
        dict: ``{"detail": "Test message sent!"}`` on success.

    Raises:
        HTTPException 404: Bot not found or not owned by user.
        HTTPException 400: Chat ID not set (user must send /start first).
        HTTPException 502: Telegram API rejected the message.
    """
    from app.services.telegram_service import send_telegram_message

    result = await db.execute(select(TelegramBot).where(TelegramBot.id == bot_id, TelegramBot.user_id == user.id))
    bot = result.scalar_one_or_none()
    if not bot:
        raise HTTPException(404, "Bot not found")
    if not bot.chat_id:
        raise HTTPException(400, "Chat ID not set — send /start to the bot and click Refresh first")

    success = await send_telegram_message(
        bot_token=bot.bot_token,
        chat_id=bot.chat_id,
        text="✅ <b>Test message from YoutubeFilterAi</b>\n\nYour bot is configured correctly!",
        video_url="https://youtube.com",
    )
    if not success:
        raise HTTPException(502, "Failed to send message — check bot token and chat ID")
    return {"detail": "Test message sent!"}


@router.delete("/telegram-bots/{bot_id}", status_code=204)
async def delete_bot(bot_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Remove a registered Telegram bot.

    Args:
        bot_id: UUID of the bot record.
        user: Current authenticated user (injected via JWT).
        db: Async database session (injected).

    Raises:
        HTTPException 404: Bot not found or not owned by user.
    """
    result = await db.execute(select(TelegramBot).where(TelegramBot.id == bot_id, TelegramBot.user_id == user.id))
    bot = result.scalar_one_or_none()
    if not bot:
        raise HTTPException(404, "Bot not found")
    await db.delete(bot)
    await db.commit()


# ── Web Views ────────────────────────────────────────────────────────────────

@router.get("/web-views", response_model=list[WebViewRead])
async def list_web_views(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """List all web summary pages for the authenticated user.

    Args:
        user: Current authenticated user (injected via JWT).
        db: Async database session (injected).

    Returns:
        list[WebViewRead]: User's web views with name and creation time.
    """
    result = await db.execute(select(WebView).where(WebView.user_id == user.id))
    return result.scalars().all()


@router.post("/web-views", response_model=WebViewRead, status_code=201)
async def create_web_view(body: WebViewCreate, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Create a new web summary page.

    Args:
        body: WebViewCreate with name (max 100 chars).
        user: Current authenticated user (injected via JWT).
        db: Async database session (injected).

    Returns:
        WebViewRead: The created web view with generated id.
    """
    wv = WebView(user_id=user.id, **body.model_dump())
    db.add(wv)
    await db.commit()
    await db.refresh(wv)
    return wv


@router.delete("/web-views/{view_id}", status_code=204)
async def delete_web_view(view_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Delete a web summary page and all its messages (cascade).

    Args:
        view_id: UUID of the web view to delete.
        user: Current authenticated user (injected via JWT).
        db: Async database session (injected).

    Raises:
        HTTPException 404: Web view not found or not owned by user.
    """
    result = await db.execute(select(WebView).where(WebView.id == view_id, WebView.user_id == user.id))
    wv = result.scalar_one_or_none()
    if not wv:
        raise HTTPException(404, "Web view not found")
    await db.delete(wv)
    await db.commit()


# ── AI Models ────────────────────────────────────────────────────────────────

@router.get("/ai-models")
async def list_ai_models(user: User = Depends(get_current_user)) -> List[dict]:
    """Fetch available AI models from OpenRouter.

    Uses the user's API token if available for personalized model list.

    Args:
        user: Current authenticated user (injected via JWT).

    Returns:
        list[dict]: Models with keys: id, name, context_length, pricing, description.
            Falls back to curated default list if OpenRouter API is unreachable.
    """
    models = await get_available_models(user.openrouter_api_token)
    return models


# ── Channel Update ───────────────────────────────────────────────────────────

@router.patch("/channels/{channel_db_id}", response_model=YouTubeChannelRead)
async def update_channel(
    channel_db_id: UUID,
    body: YouTubeChannelUpdate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db)
):
    """Update a YouTube channel's settings (partial update).

    Supports changing name, check interval, active status, and prompt assignment.

    Args:
        channel_db_id: UUID of the channel record.
        body: YouTubeChannelUpdate with optional fields to change.
        user: Current authenticated user (injected via JWT).
        db: Async database session (injected).

    Returns:
        YouTubeChannelRead: The updated channel.

    Raises:
        HTTPException 404: Channel not found or not owned by user.
    """
    result = await db.execute(
        select(YouTubeChannel).where(YouTubeChannel.id == channel_db_id, YouTubeChannel.user_id == user.id)
    )
    ch = result.scalar_one_or_none()
    if not ch:
        raise HTTPException(404, "Channel not found")
    
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(ch, field, value)
    
    await db.commit()
    await db.refresh(ch)
    return ch


# ── Data Export ──────────────────────────────────────────────────────────────

@router.get("/export", response_model=UserDataExport)
async def export_user_data(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Export all user's prompts and channel subscriptions as JSON.

    Allows the user to download a backup of their own data (prompts + channels).

    Args:
        user: Current authenticated user (injected via JWT).
        db: Async database session (injected).

    Returns:
        UserDataExport: User's prompts and channel subscriptions.
    """
    from datetime import datetime

    prompts_result = await db.execute(
        select(Prompt).where(Prompt.user_id == user.id).order_by(Prompt.name)
    )
    channels_result = await db.execute(
        select(YouTubeChannel).where(YouTubeChannel.user_id == user.id).order_by(YouTubeChannel.channel_name)
    )

    return UserDataExport(
        exported_at=datetime.utcnow(),
        email=user.email,
        prompts=prompts_result.scalars().all(),
        channels=channels_result.scalars().all(),
    )


@router.post("/import", response_model=ImportResult)
async def import_user_data(body: UserDataImport, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Import prompts and channel subscriptions from a previously exported JSON.

    Duplicate prompts (same name) and channels (same channel_id) are skipped.

    Args:
        body: UserDataImport with lists of prompts and channels to import.
        user: Current authenticated user (injected via JWT).
        db: Async database session (injected).

    Returns:
        ImportResult: Counts of imported and skipped items.
    """
    prompts_imported = 0
    prompts_skipped = 0
    channels_imported = 0
    channels_skipped = 0

    # Import prompts (skip duplicates by name)
    for p in body.prompts:
        existing = await db.execute(
            select(Prompt).where(Prompt.user_id == user.id, Prompt.name == p.name)
        )
        if existing.scalar_one_or_none():
            prompts_skipped += 1
            continue
        prompt = Prompt(user_id=user.id, **p.model_dump(exclude={"parent_id"}))
        db.add(prompt)
        prompts_imported += 1

    # Import channels (skip duplicates by channel_id)
    for c in body.channels:
        existing = await db.execute(
            select(YouTubeChannel).where(
                YouTubeChannel.user_id == user.id,
                YouTubeChannel.channel_id == c.channel_id,
            )
        )
        if existing.scalar_one_or_none():
            channels_skipped += 1
            continue
        channel = YouTubeChannel(user_id=user.id, **c.model_dump())
        db.add(channel)
        channels_imported += 1

    await db.commit()

    return ImportResult(
        prompts_imported=prompts_imported,
        channels_imported=channels_imported,
        prompts_skipped=prompts_skipped,
        channels_skipped=channels_skipped,
    )
