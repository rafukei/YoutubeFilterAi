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

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import async_session as async_session_factory
from app.models import YouTubeChannel, Prompt, TelegramBot, WebView, Message, User
from app.services import extract_video_id, fetch_transcript
from app.services.ai_service import query_ai, parse_ai_routing
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


async def process_channel(channel: YouTubeChannel, db: AsyncSession, redis_client) -> None:
    """Check a single channel for new videos and process if found.

    Raises:
        IPBlockedError: If YouTube blocks requests (IP ban detected).
            The caller should pause the entire queue.

    Args:
        channel: The YouTubeChannel ORM object.
        db: Active async DB session.
        redis_client: Redis connection for rate limiting.
    """
    # Resolve channel ID if it's a handle
    real_channel_id = await resolve_channel_id(channel.channel_id)
    if not real_channel_id:
        logger.warning("Could not resolve channel ID for %s (%s)", channel.channel_name, channel.channel_id)
        channel.last_checked_at = datetime.utcnow()
        await db.commit()
        return

    # Update stored channel_id if we resolved a handle
    original_handle = None
    if real_channel_id != channel.channel_id:
        logger.info("Resolved %s → %s", channel.channel_id, real_channel_id)
        original_handle = channel.channel_id
        channel.channel_id = real_channel_id
        await db.commit()

    handle_for_fallback = original_handle or channel.channel_name

    latest = await fetch_latest_video(real_channel_id, handle=handle_for_fallback)
    if not latest:
        logger.debug("No videos found for channel %s", channel.channel_name)
        return

    new_video_id = latest["video_id"]

    if channel.last_video_id == new_video_id:
        logger.debug("No new video for %s (latest: %s)", channel.channel_name, new_video_id)
        return

    logger.info("New video on %s: %s (%s)", channel.channel_name, latest["title"], new_video_id)

    # Load the user
    user_result = await db.execute(select(User).where(User.id == channel.user_id))
    user = user_result.scalar_one_or_none()
    if not user or not user.openrouter_api_token:
        logger.warning("User %s missing or no API token – skipping", channel.user_id)
        channel.last_checked_at = datetime.utcnow()
        return

    # Load the prompt
    if not channel.prompt_id:
        logger.warning("Channel %s has no prompt assigned – skipping", channel.channel_name)
        channel.last_checked_at = datetime.utcnow()
        channel.last_video_id = new_video_id
        return

    prompt_result = await db.execute(select(Prompt).where(Prompt.id == channel.prompt_id))
    prompt = prompt_result.scalar_one_or_none()
    if not prompt or not prompt.body:
        logger.warning("Prompt %s not found or empty – skipping", channel.prompt_id)
        channel.last_checked_at = datetime.utcnow()
        channel.last_video_id = new_video_id
        return

    # Fetch transcript — throttle first to respect YouTube rate limits
    await _throttle_yt()
    try:
        transcript = fetch_transcript(new_video_id)
    except Exception as e:
        error_msg = str(e).lower()
        if any(kw in error_msg for kw in ("blocking", "ip", "blocked", "429", "too many", "rate")):
            raise IPBlockedError(f"Rate limited/IP blocked fetching transcript for {new_video_id}")
        logger.error("Transcript fetch failed for %s: %s", new_video_id, str(e)[:200])
        channel.last_checked_at = datetime.utcnow()
        await db.commit()
        return

    # Call AI (retry up to 3 times on 503 errors)
    ai_response = None
    max_retries = 3
    retry_delay = 10
    try:
        ai_model = prompt.ai_model or "openai/gpt-3.5-turbo"
        for attempt in range(1, max_retries + 1):
            try:
                ai_response = await query_ai(
                    prompt=prompt.body,
                    transcript=transcript,
                    api_token=user.openrouter_api_token,
                    user_id=str(user.id),
                    redis_client=redis_client,
                    model=ai_model,
                )
                break  # success
            except Exception as e:
                if "503" in str(e) and attempt < max_retries:
                    logger.warning("AI 503 for video %s (attempt %d/%d), retrying in %ds…",
                                   new_video_id, attempt, max_retries, retry_delay)
                    await asyncio.sleep(retry_delay)
                else:
                    raise
    except Exception as e:
        logger.error("AI query failed for video %s: %s", new_video_id, e)
        channel.last_checked_at = datetime.utcnow()
        return

    # Parse routing
    routing = parse_ai_routing(ai_response)
    source_url = f"https://www.youtube.com/watch?v={new_video_id}"

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
                    prompt_id=channel.prompt_id,
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
            prompt_id=channel.prompt_id,
            source_video_url=source_url,
            source_video_title=latest["title"],
            transcript_text=transcript,
            ai_response=routing.get("message", ai_response),
            visibility=routing.get("visibility", True),
        )
        db.add(msg)
        messages_created.append(msg)

    await db.flush()

    # Send to Telegram
    target_bots = routing.get("telegram_bots", [])
    if target_bots:
        bots_result = await db.execute(
            select(TelegramBot).where(
                TelegramBot.user_id == user.id,
                TelegramBot.bot_name.in_(target_bots),
            )
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

    # Update channel state
    channel.last_video_id = new_video_id
    channel.last_checked_at = datetime.utcnow()
    await db.commit()

    logger.info("Processed video %s for channel %s", new_video_id, channel.channel_name)


async def scheduler_loop(redis_client) -> None:
    """Main scheduler loop – runs forever, checking due channels every SCAN_INTERVAL_SECONDS.

    All YouTube requests are sequential. If any request triggers an IP ban,
    the entire queue pauses for the configured delay before retrying.

    Args:
        redis_client: Redis connection for AI rate limiting.
    """
    logger.info("Scheduler started (scan interval: %ds)", SCAN_INTERVAL_SECONDS)

    while True:
        try:
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

                for ch in channels:
                    # Check if enough time has passed since last check
                    if ch.last_checked_at:
                        next_check = ch.last_checked_at + timedelta(minutes=ch.check_interval_minutes)
                        if now < next_check:
                            continue

                    # Delay BEFORE processing each channel to spread requests
                    if request_delay > 0:
                        logger.debug("Waiting %ds before channel %s…", request_delay, ch.channel_name)
                        await asyncio.sleep(request_delay)

                    try:
                        await process_channel(ch, db, redis_client)
                    except IPBlockedError as ipb:
                        # IP ban detected — immediately abort this entire cycle.
                        # Do NOT retry; wait for the next scan interval so the
                        # block has time to expire.
                        logger.error("⚠ IP BLOCKED: %s — aborting cycle, waiting %ds before next scan",
                                     ipb, SCAN_INTERVAL_SECONDS)
                        break
                    except Exception as e:
                        logger.error("Error processing channel %s: %s", ch.channel_name, e)
                        ch.last_checked_at = now
                        await db.commit()

        except Exception as e:
            logger.error("Scheduler loop error: %s", e)

        await asyncio.sleep(SCAN_INTERVAL_SECONDS)
