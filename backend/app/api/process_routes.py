"""
Video processing & message endpoints.

POST /api/process   – fetch transcript → AI → route to telegram/web views
GET  /api/messages  – list messages for a web view
PATCH /api/messages/{id}/visibility – toggle visibility
DELETE /api/messages/{id}           – delete a message
"""

import asyncio
import logging
from uuid import UUID

import redis.asyncio as aioredis
from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models import Message, Prompt, TelegramBot, WebView, User
from app.schemas import MessageRead, ProcessVideoRequest, ProcessVideoResponse
from app.services import extract_video_id, fetch_transcript
from app.services.ai_service import parse_ai_routing, query_ai, resolve_folder_prompts
from app.services.log_service import log_activity

logger = logging.getLogger(__name__)
from app.services.telegram_service import send_telegram_message

router = APIRouter(prefix="/api", tags=["processing"])


def _get_redis(request: Request) -> aioredis.Redis:
    """Extract the Redis client from the FastAPI app state.

    Args:
        request: The incoming HTTP request (injected by FastAPI).

    Returns:
        aioredis.Redis: Async Redis connection for rate limiting.
    """
    return request.app.state.redis


@router.post("/process", response_model=ProcessVideoResponse)
async def process_video(
    body: ProcessVideoRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    redis: aioredis.Redis = Depends(_get_redis),
):
    """Process a YouTube video through the AI pipeline.

    Full pipeline: extract video ID → fetch transcript → call OpenRouter AI
    → parse routing JSON → store message(s) → send to Telegram bots.

    Args:
        body: ProcessVideoRequest with video_url and either prompt_id or prompt_text.
        user: Current authenticated user (injected via JWT).
        db: Async database session (injected).
        redis: Redis client for AI rate limiting (injected).

    Returns:
        ProcessVideoResponse: The created message and raw transcript text.

    Raises:
        HTTPException 400: Missing OpenRouter API token or prompt text.
        HTTPException 404: Referenced prompt not found or empty.
    """
    if not user.openrouter_api_token:
        raise HTTPException(400, "Set your OpenRouter API token in settings first")

    # 1. Resolve prompt(s) — supports single prompts, folders, or ad-hoc text
    prompts_to_run = []  # list of (prompt_text, ai_model, fallback_model, prompt_id)

    if body.prompt_id:
        resolved = await resolve_folder_prompts(body.prompt_id, user.id, db)
        if not resolved:
            raise HTTPException(404, "Prompt/folder not found or contains no executable prompts")
        for p in resolved:
            prompts_to_run.append((p.body, p.ai_model or "openai/gpt-4.1-mini", p.fallback_ai_model, p.id))
    elif body.prompt_text:
        prompts_to_run.append((body.prompt_text, "openai/gpt-4.1-mini", None, None))
    else:
        raise HTTPException(400, "Provide prompt_id or prompt_text")

    # 2. Fetch transcript
    video_id = extract_video_id(body.video_url)
    try:
        transcript = fetch_transcript(video_id)
    except Exception as e:
        err = str(e).lower()
        await log_activity(db, user.id, "ERROR", "transcript", f"Failed to fetch transcript for {video_id}: {e}")
        if "no subtitles" in err or "no transcript" in err:
            raise HTTPException(
                400,
                "This video has no subtitles/captions available. "
                "The AI needs text to process — only videos with subtitles (auto-generated or manual) can be analyzed."
            )
        raise HTTPException(400, f"Could not fetch video transcript: {e}")

    source_url = f"https://www.youtube.com/watch?v={video_id}"
    await log_activity(db, user.id, "INFO", "transcript", f"Fetched transcript for {video_id} ({len(transcript)} chars)")
    all_messages_created = []

    # 3. Process each prompt against the transcript (with delay between calls)
    for idx, (prompt_text, ai_model, fallback_model, prompt_id) in enumerate(prompts_to_run):
        if idx > 0:
            await asyncio.sleep(2)  # Rate-limit delay between AI calls

        try:
            # Debug: log which model and prompt are about to be used
            prompt_id_debug = str(prompt_id) if prompt_id else "<ad-hoc>"
            logger.info("AI call: user=%s prompt_id=%s model=%s fallback=%s prompt_len=%s transcript_chars=%d",
                        str(user.id), prompt_id_debug, ai_model, fallback_model, len(prompt_text) if prompt_text else "N/A", len(transcript))
            await log_activity(db, user.id, "DEBUG", "ai", f"Calling query_ai prompt_id={prompt_id_debug} model={ai_model} fallback={fallback_model} transcript_chars={len(transcript)}")

            ai_response = await query_ai(
                prompt=prompt_text,
                transcript=transcript,
                api_token=user.openrouter_api_token,
                user_id=str(user.id),
                redis_client=redis,
                model=ai_model,
                fallback_model=fallback_model,
            )
        except RuntimeError as e:
            await log_activity(db, user.id, "ERROR", "ai", f"AI query failed (model={ai_model}): {e}")
            raise HTTPException(502, str(e))

        await log_activity(db, user.id, "INFO", "ai", f"AI response received (model={ai_model}, {len(ai_response)} chars)")

        # Parse the prompt's own routing JSON to use as fallback
        prompt_routing = parse_ai_routing(prompt_text) if prompt_text else {}
        routing = parse_ai_routing(ai_response, prompt_routing=prompt_routing)
        messages_created = []

        target_views = routing.get("web_views", [])
        if target_views:
            for view_name in target_views:
                wv_result = await db.execute(
                    select(WebView).where(WebView.user_id == user.id, WebView.name == view_name)
                )
                wv = wv_result.scalar_one_or_none()
                if not wv:
                    wv = WebView(user_id=user.id, name=view_name)
                    db.add(wv)
                    await db.flush()
                    await db.refresh(wv)
                msg = Message(
                    user_id=user.id,
                    web_view_id=wv.id,
                    prompt_id=prompt_id,
                    source_video_url=source_url,
                    transcript_text=transcript,
                    ai_response=routing.get("message", ai_response),
                    visibility=routing.get("visibility", True),
                )
                db.add(msg)
                messages_created.append(msg)
        else:
            msg = Message(
                user_id=user.id,
                prompt_id=prompt_id,
                source_video_url=source_url,
                transcript_text=transcript,
                ai_response=routing.get("message", ai_response),
                visibility=routing.get("visibility", True),
            )
            db.add(msg)
            messages_created.append(msg)

        await db.flush()

        # Send to Telegram bots (only if visibility is true)
        target_bots = routing.get("telegram_bots", [])
        if target_bots and routing.get("visibility", True):
            bots_result = await db.execute(
                select(TelegramBot).where(TelegramBot.user_id == user.id, TelegramBot.bot_name.in_(target_bots))
            )
            for bot in bots_result.scalars():
                if bot.chat_id:
                    try:
                        sent = await send_telegram_message(
                            bot_token=bot.bot_token,
                            chat_id=bot.chat_id,
                            text=routing.get("message", ai_response),
                            video_url=source_url,
                        )
                    except Exception as e:
                        # Network or HTTP client errors can happen — record
                        # them in activity logs but don't raise an exception
                        # that would abort the surrounding DB work and return
                        # a 502 to the caller.
                        await log_activity(db, user.id, "ERROR", "telegram",
                                           f"Failed to send via bot '{bot.bot_name}': {e}")
                        sent = False

                    if sent:
                        for m in messages_created:
                            m.sent_to_telegram = True
                        await log_activity(db, user.id, "INFO", "telegram", f"Message sent via bot '{bot.bot_name}'")
                    else:
                        await log_activity(db, user.id, "WARNING", "telegram", f"Failed to send via bot '{bot.bot_name}'")

        all_messages_created.extend(messages_created)

    await db.flush()
    for m in all_messages_created:
        await db.refresh(m)

    return ProcessVideoResponse(
        message=all_messages_created[0],
        raw_transcript=transcript,
    )


@router.get("/messages", response_model=list[MessageRead])
async def list_messages(
    web_view_id: UUID | None = None,
    show_hidden: bool = False,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """List AI-generated messages for the authenticated user.

    Supports filtering by web view and visibility. Hidden messages are
    excluded by default unless ``show_hidden=True``.

    Args:
        web_view_id: Optional UUID to filter messages by web view.
        show_hidden: If True, include messages with visibility=False.
        user: Current authenticated user (injected via JWT).
        db: Async database session (injected).

    Returns:
        list[MessageRead]: Messages ordered by creation time (newest first).
    """
    q = select(Message).where(Message.user_id == user.id)
    if web_view_id:
        q = q.where(Message.web_view_id == web_view_id)
    if not show_hidden:
        q = q.where(Message.visibility == True)  # noqa: E712
    q = q.order_by(Message.created_at.desc())
    result = await db.execute(q)
    return result.scalars().all()


@router.patch("/messages/{message_id}/visibility", response_model=MessageRead)
async def toggle_visibility(message_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Toggle a message's visibility between shown and hidden.

    Args:
        message_id: UUID of the message to toggle.
        user: Current authenticated user (injected via JWT).
        db: Async database session (injected).

    Returns:
        MessageRead: The updated message with new visibility state.

    Raises:
        HTTPException 404: Message not found or not owned by user.
    """
    result = await db.execute(select(Message).where(Message.id == message_id, Message.user_id == user.id))
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(404, "Message not found")
    msg.visibility = not msg.visibility
    await db.flush()
    await db.refresh(msg)
    return msg


@router.delete("/messages/{message_id}", status_code=204)
async def delete_message(message_id: UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Permanently delete a message.

    Args:
        message_id: UUID of the message to delete.
        user: Current authenticated user (injected via JWT).
        db: Async database session (injected).

    Raises:
        HTTPException 404: Message not found or not owned by user.
    """
    result = await db.execute(select(Message).where(Message.id == message_id, Message.user_id == user.id))
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(404, "Message not found")
    await db.delete(msg)
