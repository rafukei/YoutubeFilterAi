"""
Video processing & message endpoints.

POST /api/process   – fetch transcript → AI → route to telegram/web views
GET  /api/messages  – list messages for a web view
PATCH /api/messages/{id}/visibility – toggle visibility
DELETE /api/messages/{id}           – delete a message
"""

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
from app.services.ai_service import parse_ai_routing, query_ai
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

    # 1. Resolve prompt text
    prompt_text = body.prompt_text
    if body.prompt_id:
        result = await db.execute(select(Prompt).where(Prompt.id == body.prompt_id, Prompt.user_id == user.id))
        prompt = result.scalar_one_or_none()
        if not prompt or not prompt.body:
            raise HTTPException(404, "Prompt not found or empty")
        prompt_text = prompt.body

    if not prompt_text:
        raise HTTPException(400, "Provide prompt_id or prompt_text")

    # 2. Fetch transcript
    video_id = extract_video_id(body.video_url)
    transcript = fetch_transcript(video_id)

    # 3. Call AI
    ai_response = await query_ai(
        prompt=prompt_text,
        transcript=transcript,
        api_token=user.openrouter_api_token,
        user_id=str(user.id),
        redis_client=redis,
    )

    # 4. Parse routing JSON from AI response
    routing = parse_ai_routing(ai_response)

    # 5. Store message for each target web view
    source_url = f"https://www.youtube.com/watch?v={video_id}"
    messages_created = []

    target_views = routing.get("web_views", [])
    if target_views:
        for view_name in target_views:
            wv_result = await db.execute(
                select(WebView).where(WebView.user_id == user.id, WebView.name == view_name)
            )
            wv = wv_result.scalar_one_or_none()
            if wv:
                msg = Message(
                    user_id=user.id,
                    web_view_id=wv.id,
                    prompt_id=body.prompt_id,
                    source_video_url=source_url,
                    transcript_text=transcript,
                    ai_response=routing.get("message", ai_response),
                    visibility=routing.get("visibility", True),
                )
                db.add(msg)
                messages_created.append(msg)
    else:
        # No web view specified – store without view
        msg = Message(
            user_id=user.id,
            prompt_id=body.prompt_id,
            source_video_url=source_url,
            transcript_text=transcript,
            ai_response=routing.get("message", ai_response),
            visibility=routing.get("visibility", True),
        )
        db.add(msg)
        messages_created.append(msg)

    await db.flush()

    # 6. Send to Telegram bots
    target_bots = routing.get("telegram_bots", [])
    if target_bots:
        bots_result = await db.execute(
            select(TelegramBot).where(TelegramBot.user_id == user.id, TelegramBot.bot_name.in_(target_bots))
        )
        for bot in bots_result.scalars():
            if bot.chat_id:
                sent = await send_telegram_message(
                    bot_token=bot.bot_token,
                    chat_id=bot.chat_id,
                    text=routing.get("message", ai_response),
                    video_url=source_url,
                )
                if sent:
                    for m in messages_created:
                        m.sent_to_telegram = True

    await db.flush()
    for m in messages_created:
        await db.refresh(m)

    return ProcessVideoResponse(
        message=messages_created[0],
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
