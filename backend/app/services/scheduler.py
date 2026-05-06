"""
Background scheduler that periodically checks YouTube channels for new videos.

Uses YouTube RSS feeds (no API key needed) to detect new uploads.
When a new video is found, it runs the configured prompt through the AI pipeline
and routes the result to Telegram bots / web views.

Started on FastAPI lifespan startup; runs as an asyncio background task.
"""

import asyncio
import time
import logging
from datetime import datetime, timedelta
from xml.etree import ElementTree
from uuid import UUID

import httpx
from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session as async_session_factory
from app.models import YouTubeChannel, TelegramBot, WebView, Message, User
from app.services import extract_video_id, fetch_transcript
from app.services.ai_service import query_ai, parse_ai_routing, resolve_folder_prompts
from app.services.log_service import log_activity
from app.services.telegram_service import send_telegram_message

logger = logging.getLogger("scheduler")
logging.basicConfig(level=logging.INFO)

# How often the scheduler loop wakes up to scan channels (seconds)
SCAN_INTERVAL_SECONDS = 60

# YouTube RSS feed URL template
YT_RSS_URL = "https://www.youtube.com/feeds/videos.xml?channel_id={channel_id}"

# ── Global YouTube request throttle ────────────────────────────────
# Shared across ALL YouTube HTTP requests (RSS, scrape, transcript)
# to guarantee a minimum gap between requests from this process.
_last_yt_request: float = 0.0
_YT_MIN_DELAY: float = 2.0  # seconds between any two YouTube requests

# ── IP block handling ──────────────────────────────────────────────
# Consecutive IP blocks trigger progressively longer cooldowns.
_IP_BLOCK_THRESHOLD = 3          # pause after this many consecutive blocks
_IP_BLOCK_BASE_MINUTES = 15      # initial cooldown: 15 min
_IP_BLOCK_MAX_MINUTES = 60       # max cooldown: 60 min
_ip_block_count: int = 0
_ip_block_cooldown_until: datetime | None = None

# Transcript retry limit — a video with no subtitles is retried this many times
# before giving up and marking it as the channel's last_video_id so it doesn't
# block the entire channel indefinitely.
_TRANSCRIPT_RETRY_MAX = 3

# ── Defensive assertions ─────────────────────────────────────────────────────
# These are self-healing checks that run at the START of process_channel()
# to detect and auto-correct stuck states before they become infinite loops.


async def _assert_channel_not_stuck(channel_id: UUID, db: AsyncSession, new_video_id: str) -> None:
    """Defensive check: verify channel is not in a stuck retry state.

    A channel is considered "stuck" if transcript_retry_count > 0 but the
    last_checked_at is older than _TRANSCRIPT_RETRY_MAX * SCAN_INTERVAL_SECONDS * 2.
    This would indicate the scheduler crashed mid-retry and the counter was
    left elevated.

    This is self-healing: if stuck, we log the issue and reset the counter.

    Args:
        channel_id: The channel UUID to check.
        db: Active async DB session.
        new_video_id: The video ID we're about to process (for logging).
    """
    result = await db.execute(
        select(YouTubeChannel).where(YouTubeChannel.id == channel_id)
    )
    ch = result.scalar_one_or_none()
    if not ch:
        return

    if ch.transcript_retry_count and ch.transcript_retry_count > 0:
        # Check how long it's been stuck
        if ch.last_checked_at:
            stuck_duration = (datetime.utcnow() - ch.last_checked_at).total_seconds()
            max_expected = _TRANSCRIPT_RETRY_MAX * SCAN_INTERVAL_SECONDS * 2
            if stuck_duration > max_expected:
                logger.warning(
                    "DEFENSIVE: Channel '%s' has stuck retry_count=%d (last_checked=%ds ago). "
                    "Resetting counter — previous fix may have been incomplete.",
                    ch.channel_name, ch.transcript_retry_count, int(stuck_duration)
                )
                await _update_channel(db, channel_id, transcript_retry_count=0)
                await db.commit()


async def _throttle_yt(min_delay: float | None = None) -> None:
    """Ensure at least `min_delay` seconds since the last YouTube request.

    This is module-level so the delay persists across channels and functions.
    """
    global _last_yt_request
    delay = min_delay if min_delay is not None else _YT_MIN_DELAY
    now = time.monotonic()
    elapsed = now - _last_yt_request
    if elapsed < delay and _last_yt_request != 0.0:
        await asyncio.sleep(delay - elapsed)
    _last_yt_request = time.monotonic()


async def resolve_channel_id(channel_id_or_handle: str) -> str | None:
    """Resolve a YouTube @handle or custom URL to a real channel ID.

    If input already looks like a channel ID (starts with UC), returns it as-is.
    Uses multiple fallback methods to handle consent/cookie issues.

    Args:
        channel_id_or_handle: Either a real channel ID or @handle.

    Returns:
        The real channel ID, or None if resolution fails.
    """
    import re

    if channel_id_or_handle.startswith("UC") and len(channel_id_or_handle) == 24:
        return channel_id_or_handle

    handle = channel_id_or_handle.lstrip("@")

    # Method 1: Try YouTube's oembed endpoint (no consent required)
    oembed_url = f"https://www.youtube.com/oembed?url=https://www.youtube.com/@{handle}&format=json"
    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.get(oembed_url)
            if resp.status_code == 200:
                data = resp.json()
                # Extract channel ID from author_url
                author_url = data.get("author_url", "")
                match = re.search(r'/channel/(UC[a-zA-Z0-9_-]{22})', author_url)
                if match:
                    return match.group(1)
    except Exception as e:
        logger.debug("Oembed method failed for %s: %s", handle, e)

    # Method 2: Scrape the channel page with proper headers/cookies
    url = f"https://www.youtube.com/@{handle}"
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    # SOCS cookie is the newer consent cookie format
    cookies = {
        "CONSENT": "PENDING+987",
        "SOCS": "CAESEwgDEgk2MjQyMjk0NzQaAmVuIAEaBgiA_LyaBg",
    }

    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=headers, cookies=cookies) as client:
            resp = await client.get(url)
            resp.raise_for_status()

            # Check if we got the consent page instead
            if "consent.youtube.com" in str(resp.url) or "Before you continue" in resp.text:
                logger.debug("Got consent page for %s, trying alternative method", handle)
            else:
                # Look for channel ID in various places
                match = re.search(r'"channelId"\s*:\s*"(UC[a-zA-Z0-9_-]{22})"', resp.text)
                if match:
                    return match.group(1)
                match = re.search(r'"externalId"\s*:\s*"(UC[a-zA-Z0-9_-]{22})"', resp.text)
                if match:
                    return match.group(1)
                match = re.search(r'channel_id=(UC[a-zA-Z0-9_-]{22})', resp.text)
                if match:
                    return match.group(1)
    except Exception as e:
        logger.debug("Scrape method failed for %s: %s", handle, e)

    # Method 3: Try fetching a video from search and extract channel from there
    search_url = f"https://www.youtube.com/results?search_query=%40{handle}&sp=EgIQAg%253D%253D"
    try:
        async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=headers, cookies=cookies) as client:
            resp = await client.get(search_url)
            if resp.status_code == 200:
                # Look for channel link in search results
                match = re.search(rf'"channelId"\s*:\s*"(UC[a-zA-Z0-9_-]{{22}})".*?"@{re.escape(handle)}"', resp.text, re.IGNORECASE)
                if match:
                    return match.group(1)
                # Simpler fallback
                match = re.search(r'"channelId"\s*:\s*"(UC[a-zA-Z0-9_-]{22})"', resp.text)
                if match:
                    return match.group(1)
    except Exception as e:
        logger.debug("Search method failed for %s: %s", handle, e)

    logger.warning("Could not resolve channel ID for %s (@%s)", channel_id_or_handle, handle)
    return None


async def fetch_latest_video(channel_id: str, handle: str | None = None) -> dict | None:
    """Fetch the most recent video from a YouTube channel's RSS feed.

    Falls back to scraping channel page if RSS is unavailable.

    Args:
        channel_id: YouTube channel ID (e.g. UCxxxxxx).
        handle: Optional @handle for fallback scraping.

    Returns:
        Dict with keys 'video_id', 'title', 'published', or None if unavailable.
    """
    import re

    # Method 1: Try RSS feed first (most reliable when available)
    url = YT_RSS_URL.format(channel_id=channel_id)
    try:
        await _throttle_yt()
        async with httpx.AsyncClient(timeout=20) as client:
            resp = await client.get(url)
            if resp.status_code == 200:
                try:
                    ns = {
                        "atom": "http://www.w3.org/2005/Atom",
                        "yt": "http://www.youtube.com/xml/schemas/2015",
                    }
                    root = ElementTree.fromstring(resp.text)
                    entry = root.find("atom:entry", ns)
                    if entry is not None:
                        video_id_el = entry.find("yt:videoId", ns)
                        title_el = entry.find("atom:title", ns)
                        published_el = entry.find("atom:published", ns)
                        if video_id_el is not None and video_id_el.text:
                            return {
                                "video_id": video_id_el.text,
                                "title": title_el.text if title_el is not None else "",
                                "published": published_el.text if published_el is not None else "",
                            }
                except Exception as e:
                    logger.debug("RSS parse failed for %s: %s", channel_id, e)
    except Exception as e:
        logger.debug("RSS fetch failed for %s: %s", channel_id, e)

    # Method 2: Scrape channel videos page
    logger.debug("RSS unavailable for %s, trying scrape method", channel_id)
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    }
    cookies = {
        "CONSENT": "PENDING+987",
        "SOCS": "CAESEwgDEgk2MjQyMjk0NzQaAmVuIAEaBgiA_LyaBg",
    }

    # Try both /channel/ID/videos and /@handle/videos URLs
    urls_to_try = [f"https://www.youtube.com/channel/{channel_id}/videos"]
    if handle:
        h = handle.lstrip("@")
        urls_to_try.append(f"https://www.youtube.com/@{h}/videos")

    # Reuse a single AsyncClient for all URLs to preserve connection pooling
    # and make throttling (1s between requests) consistent.
    async with httpx.AsyncClient(timeout=20, follow_redirects=True, headers=headers, cookies=cookies) as client:
        for channel_url in urls_to_try:
            try:
                await _throttle_yt()
                resp = await client.get(channel_url)
                if resp.status_code != 200:
                    continue

                body = resp.text

                # Check if we got consent page instead of real content
                if "consent.youtube.com" in str(resp.url) or "Before you continue" in body or '"videoId"' not in body:
                    logger.debug("Got consent page or no video data for %s from %s", channel_id, channel_url)
                    continue

                # Find video IDs in the page - skip shorts by looking for standard video renderer
                # First try to find videos in the "richItemRenderer" / "gridVideoRenderer" section
                matches = re.findall(r'"videoId"\s*:\s*"([a-zA-Z0-9_-]{11})"', body)
                if not matches:
                    continue

                # Deduplicate while preserving order
                seen = set()
                unique_ids = []
                for vid in matches:
                    if vid not in seen:
                        seen.add(vid)
                        unique_ids.append(vid)

                video_id = unique_ids[0]

                # Try to extract the title
                title = ""
                # Pattern: "videoId":"XXX"..."title":{"runs":[{"text":"..."}]}
                title_match = re.search(
                    r'"videoId"\s*:\s*"' + re.escape(video_id) + r'".*?"title"\s*:\s*\{\s*"runs"\s*:\s*\[\s*\{\s*"text"\s*:\s*"([^"]*)"',
                    body[:body.index(video_id) + 2000] if video_id in body else body,
                    re.DOTALL
                )
                if title_match:
                    title = title_match.group(1)

                if not title:
                    # Simpler fallback pattern
                    title_match = re.search(
                        r'"videoId"\s*:\s*"' + re.escape(video_id) + r'"[^}]*?"title"\s*:\s*"([^"]*)"',
                        body
                    )
                    if title_match:
                        title = title_match.group(1)

                return {
                    "video_id": video_id,
                    "title": title,
                    "published": "",
                }
            except Exception as e:
                logger.debug("Scrape failed for %s at %s: %s", channel_id, channel_url, e)

    logger.warning("Could not fetch latest video for channel %s", channel_id)
    return None


class IPBlockedError(Exception):
    """Raised when YouTube blocks requests due to IP ban."""
    pass


async def _update_channel(db: AsyncSession, ch_id: UUID, **kwargs) -> None:
    """Update YouTubeChannel fields using an explicit UPDATE statement.

    Avoids ORM mutation which triggers greenlet errors in async context.
    """
    if not kwargs:
        return
    stmt = update(YouTubeChannel).where(YouTubeChannel.id == ch_id).values(**kwargs)
    await db.execute(stmt)


async def process_channel(channel_id: UUID, db: AsyncSession, redis_client) -> None:
    """Check a single channel for new videos and process if found.

    Raises:
        IPBlockedError: If YouTube blocks requests (IP ban detected).
            The caller should pause the entire queue.

    Args:
        channel_id: The UUID of the YouTubeChannel to process.
        db: Active async DB session.
        redis_client: Redis connection for rate limiting.
    """
    # Fetch fresh channel object — never use ORM objects from outer loops
    result = await db.execute(
        select(YouTubeChannel).where(YouTubeChannel.id == channel_id)
    )
    channel = result.scalar_one_or_none()
    if not channel:
        return

    channel_name = channel.channel_name
    stored_channel_id = channel.channel_id
    last_video_id = channel.last_video_id
    prompt_id = channel.prompt_id
    user_id = channel.user_id

    # ── Defensive: detect and heal stuck retry state ──────────────────────
    # This runs every cycle so a crashed scheduler can't leave the channel
    # in an infinite retry loop permanently.
    await _assert_channel_not_stuck(channel_id, db, last_video_id or "?")

    # Resolve channel ID if it's a handle
    real_channel_id = await resolve_channel_id(stored_channel_id)
    if not real_channel_id:
        logger.warning("Could not resolve channel ID for %s (%s)", channel_name, stored_channel_id)
        await _update_channel(db, channel_id, last_checked_at=datetime.utcnow())
        await db.commit()
        return

    # Update stored channel_id if we resolved a handle
    original_handle = None
    if real_channel_id != stored_channel_id:
        logger.info("Resolved %s → %s", stored_channel_id, real_channel_id)
        original_handle = stored_channel_id
        try:
            await _update_channel(db, channel_id, channel_id=real_channel_id)
            await db.commit()
        except IntegrityError:
            # Another row already has this channel_id for this user — the handle
            # was already resolved by a concurrent run. Silently skip.
            await db.rollback()
            return

    handle_for_fallback = original_handle or channel_name

    latest = await fetch_latest_video(real_channel_id, handle=handle_for_fallback)
    if not latest:
        # Feed is empty (no public videos) — mark checked so we don't hammer
        # the same empty feed every cycle. Respect check_interval on next run.
        logger.debug("No videos found for channel %s", channel_name)
        await _update_channel(db, channel_id, last_checked_at=datetime.utcnow())
        await db.commit()
        return

    new_video_id = latest["video_id"]

    if last_video_id == new_video_id:
        # Already processed this video — mark checked to respect check_interval
        logger.debug("No new video for %s (latest: %s)", channel_name, new_video_id)
        await _update_channel(db, channel_id, last_checked_at=datetime.utcnow())
        await db.commit()
        return

    logger.info("New video on %s: %s (%s)", channel_name, latest["title"], new_video_id)
    await log_activity(db, user_id, "INFO", "scheduler",
                       f"New video on {channel_name}: {latest['title']}")

    # Load the user
    user_result = await db.execute(select(User).where(User.id == user_id))
    user = user_result.scalar_one_or_none()
    if not user or not user.openrouter_api_token:
        logger.warning("User %s missing or no API token – skipping", user_id)
        await _update_channel(db, channel_id, last_checked_at=datetime.utcnow(), last_video_id=new_video_id)
        await db.commit()
        return

    # Load the prompt(s) — supports both single prompts and folders
    if not prompt_id:
        logger.warning("Channel %s has no prompt assigned – skipping", channel_name)
        await _update_channel(db, channel_id, last_checked_at=datetime.utcnow(), last_video_id=new_video_id)
        await db.commit()
        return

    prompts_to_run = await resolve_folder_prompts(prompt_id, user_id, db)
    if not prompts_to_run:
        logger.warning("Prompt/folder %s has no executable prompts – skipping", prompt_id)
        await _update_channel(db, channel_id, last_checked_at=datetime.utcnow(), last_video_id=new_video_id)
        await db.commit()
        return

    # Fetch transcript — throttle first to respect YouTube rate limits.
    # Move last_video_id forward immediately so a crashed/restarted scheduler
    # does NOT re-process the same video.  If transcript fails we will retry
    # up to _TRANSCRIPT_RETRY_MAX times before giving up.
    await _throttle_yt()
    await _update_channel(db, channel_id, last_video_id=new_video_id, last_checked_at=datetime.utcnow())
    await db.commit()

    try:
        transcript = fetch_transcript(new_video_id)
    except Exception as e:
        error_msg = str(e).lower()
        if any(kw in error_msg for kw in ("blocking", "ip", "blocked", "429", "too many", "rate")):
            raise IPBlockedError(f"Rate limited/IP blocked fetching transcript for {new_video_id}")

        # Retry-limit check: track consecutive failures per video.
        # We can't read current count inside the except block without re-fetching,
        # so we do it here before incrementing.
        ch_result = await db.execute(
            select(YouTubeChannel).where(YouTubeChannel.id == channel_id)
        )
        ch = ch_result.scalar_one_or_none()
        retry_count = (ch.transcript_retry_count or 0) + 1 if ch else 1

        if retry_count >= _TRANSCRIPT_RETRY_MAX:
            # Exhausted retries — log permanently and move on so the channel isn't blocked
            logger.warning(
                "Transcript fetch exhausted (%d attempts) for video %s on channel %s — giving up",
                retry_count, new_video_id, channel_name
            )
            await log_activity(db, user_id, "WARNING", "transcript",
                               f"Giving up on video {new_video_id} after {retry_count} failed attempts: {str(e)[:100]}")
            # Reset retry counter; this video is now the channel's last_video_id
            await _update_channel(db, channel_id, transcript_retry_count=0, last_checked_at=datetime.utcnow())
            await db.commit()
            return

        logger.warning(
            "Transcript fetch failed for video %s on channel %s (attempt %d/%d): %s",
            new_video_id, channel_name, retry_count, _TRANSCRIPT_RETRY_MAX, str(e)[:200]
        )
        await log_activity(db, user_id, "WARNING", "transcript",
                           f"Retrying video {new_video_id} (attempt {retry_count}/{_TRANSCRIPT_RETRY_MAX}): {str(e)[:150]}")
        await _update_channel(db, channel_id, transcript_retry_count=retry_count)
        await db.commit()
        return  # next cycle will retry; last_video_id already set so we don't re-process

    # Reset retry counter on success
    await _update_channel(db, channel_id, transcript_retry_count=0)

    # Process each prompt against the same transcript (with delay between AI calls)
    source_url = f"https://www.youtube.com/watch?v={new_video_id}"

    for prompt_idx, prompt in enumerate(prompts_to_run):
        # Delay between AI calls to avoid rate limiting (skip first)
        if prompt_idx > 0:
            await asyncio.sleep(3)

        # Call AI (retry up to 3 times on 503 errors), with fallback model support
        ai_response = None
        max_retries = 3
        retry_delay = 10
        try:
            ai_model = prompt.ai_model or "openai/gpt-4.1-mini"
            fallback_model = prompt.fallback_ai_model
            for attempt in range(1, max_retries + 1):
                try:
                    logger.info("Scheduler AI call: channel=%s user=%s prompt=%s model=%s fallback=%s transcript_chars=%d",
                                channel_id, str(user.id), prompt.name, ai_model, fallback_model, len(transcript))
                    await log_activity(db, user_id, "DEBUG", "ai", f"Scheduler calling query_ai prompt={prompt.name} model={ai_model} fallback={fallback_model} transcript_chars={len(transcript)}")

                    ai_response = await query_ai(
                        prompt=prompt.body,
                        transcript=transcript,
                        api_token=user.openrouter_api_token,
                        user_id=str(user.id),
                        redis_client=redis_client,
                        model=ai_model,
                        fallback_model=fallback_model,
                    )
                    break  # success
                except Exception as e:
                    if "503" in str(e) and attempt < max_retries:
                        logger.warning("AI 503 for video %s prompt %s (attempt %d/%d), retrying in %ds…",
                                       new_video_id, prompt.name, attempt, max_retries, retry_delay)
                        await asyncio.sleep(retry_delay)
                    else:
                        raise
        except Exception as e:
            logger.error("AI query failed for video %s prompt %s: %s", new_video_id, prompt.name, e)
            await log_activity(db, user_id, "ERROR", "ai",
                               f"AI failed for {prompt.name}: {str(e)[:200]}")
            continue  # Skip this prompt, try the next one

        # Parse routing — use prompt's own routing JSON as fallback
        prompt_routing = parse_ai_routing(prompt.body) if prompt.body else {}
        routing = parse_ai_routing(ai_response, prompt_routing=prompt_routing)

        # Store messages
        target_views = routing.get("web_views", [])
        messages_created = []
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
                        prompt_id=prompt.id,
                        source_video_url=source_url,
                        source_video_title=latest["title"],
                        transcript_text=transcript,
                        ai_response=routing.get("message", ai_response),
                        visibility=routing.get("visibility", True),
                    )
                    db.add(msg)
                    messages_created.append(msg)
        else:
            msg = Message(
                user_id=user.id,
                prompt_id=prompt.id,
                source_video_url=source_url,
                source_video_title=latest["title"],
                transcript_text=transcript,
                ai_response=routing.get("message", ai_response),
                visibility=routing.get("visibility", True),
            )
            db.add(msg)
            messages_created.append(msg)

        await db.flush()

        # Send to Telegram (only if visibility is true)
        target_bots = routing.get("telegram_bots", [])
        if target_bots and routing.get("visibility", True):
            bots_result = await db.execute(
                select(TelegramBot).where(
                    TelegramBot.user_id == user.id,
                    TelegramBot.bot_name.in_(target_bots),
                )
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
                        await log_activity(db, user_id, "ERROR", "telegram",
                                           f"Failed to send via bot '{bot.bot_name}': {e}")
                        sent = False

                    if sent:
                        for m in messages_created:
                            m.sent_to_telegram = True
                        await log_activity(db, user_id, "INFO", "telegram",
                                           f"Sent via bot '{bot.bot_name}' for {channel_name}")
                    else:
                        await log_activity(db, user_id, "WARNING", "telegram",
                                           f"Failed to send via bot '{bot.bot_name}' for {channel_name}")

        logger.info("Processed prompt '%s' for video %s on channel %s",
                     prompt.name, new_video_id, channel_name)
        await log_activity(db, user_id, "INFO", "ai",
                           f"Processed '{prompt.name}' for {channel_name} ({new_video_id})")

    # Channel state already updated: last_video_id set before transcript fetch,
    # transcript_retry_count reset on success. Just update last_checked_at.
    await _update_channel(db, channel_id, last_checked_at=datetime.utcnow())
    await db.commit()

    logger.info("Processed video %s for channel %s", new_video_id, channel_name)


async def scheduler_loop(redis_client) -> None:
    """Main scheduler loop – runs forever, checking due channels every SCAN_INTERVAL_SECONDS.

    All YouTube requests are sequential. If any request triggers an IP ban,
    the entire queue pauses for the configured delay before retrying.

    Args:
        redis_client: Redis connection for AI rate limiting.
    """
    global _ip_block_count, _ip_block_cooldown_until
    logger.info("Scheduler started (scan interval: %ds)", SCAN_INTERVAL_SECONDS)

    while True:
        try:
            # ── IP block cooldown check ────────────────────────────────
            now = datetime.utcnow()
            if _ip_block_cooldown_until and now < _ip_block_cooldown_until:
                remaining = (_ip_block_cooldown_until - now).total_seconds()
                logger.info(
                    "⏸ IP block cooldown active — pausing for %.0f more seconds (%d consecutive blocks, next retry in %dm)",
                    remaining, _ip_block_count, int(remaining / 60)
                )
                await asyncio.sleep(min(remaining, SCAN_INTERVAL_SECONDS))
                continue
            elif _ip_block_cooldown_until:
                # Cooldown expired — reset block count on next successful request
                logger.info("⏹ IP block cooldown ended, block count reset")
                _ip_block_count = 0
                _ip_block_cooldown_until = None

            async with async_session_factory() as db:
                now = datetime.utcnow()

                # Load configurable delay from app_settings
                from app.models import AppSettings
                settings_row = await db.execute(select(AppSettings).where(AppSettings.key == "default"))
                app_settings = settings_row.scalar_one_or_none()
                request_delay = app_settings.channel_request_delay if app_settings and app_settings.channel_request_delay else 5

                result = await db.execute(
                    select(YouTubeChannel).where(YouTubeChannel.is_active == True)
                )
                channels = result.scalars().all()

                # Materialize all ORM data into plain dicts BEFORE any processing.
                # This prevents greenlet_spawn errors from lazy-loading ORM attributes
                # after process_channel() calls rollback() on the session.
                channel_data = [
                    {
                        "id": ch.id,
                        "name": ch.channel_name,
                        "last_checked_at": ch.last_checked_at,
                        "check_interval_minutes": ch.check_interval_minutes,
                    }
                    for ch in channels
                ]

                for cd in channel_data:
                    # Check if enough time has passed since last check
                    if cd["last_checked_at"]:
                        next_check = cd["last_checked_at"] + timedelta(minutes=cd["check_interval_minutes"])
                        if now < next_check:
                            continue

                    # Delay BEFORE processing each channel to spread requests
                    if request_delay > 0:
                        logger.debug("Waiting %ds before channel %s…", request_delay, cd["name"])
                        await asyncio.sleep(request_delay)

                    try:
                        await process_channel(cd["id"], db, redis_client)
                        # Successful request — reset consecutive block counter
                        if _ip_block_count > 0:
                            logger.info("✓ YouTube request succeeded after %d block(s) — resetting block counter", _ip_block_count)
                            _ip_block_count = 0
                            _ip_block_cooldown_until = None
                    except IPBlockedError as ipb:
                        # IP ban on THIS channel — skip it and move to the next.
                        # Do NOT abort the whole cycle; other channels may have
                        # unprocessed videos.
                        _ip_block_count += 1
                        logger.warning(
                            "⚠ IP blocked for channel %s (%s) — consecutive block #%d",
                            cd["name"], ipb, _ip_block_count
                        )
                        if _ip_block_count >= _IP_BLOCK_THRESHOLD:
                            # Calculate cooldown: 15 → 30 → 60 min
                            cooldown_minutes = min(
                                _IP_BLOCK_BASE_MINUTES * (2 ** (_ip_block_count - _IP_BLOCK_THRESHOLD)),
                                _IP_BLOCK_MAX_MINUTES
                            )
                            _ip_block_cooldown_until = datetime.utcnow() + timedelta(minutes=cooldown_minutes)
                            logger.error(
                                "🔒 IP block threshold (%d) reached — pausing scheduler for %d minutes",
                                _IP_BLOCK_THRESHOLD, cooldown_minutes
                            )
                        continue
                    except Exception as e:
                        logger.error("Error processing channel %s: %s", cd["name"], e)
                        try:
                            await _update_channel(db, cd["id"], last_checked_at=now)
                            await db.commit()
                        except Exception:
                            pass

        except Exception as e:
            logger.error("Scheduler loop error: %s", e)
            # Ensure the session is rolled back on any unhandled exception
            # so the next iteration starts with a clean session.
            try:
                await db.rollback()
            except Exception:
                pass

        await asyncio.sleep(SCAN_INTERVAL_SECONDS)
