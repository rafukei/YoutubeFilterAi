"""
Telegram bot message sender and setup helpers.

Each user configures their own Telegram bot (via BotFather token).
This service sends messages to the configured chat_id using the Bot API,
and provides helpers to validate tokens and auto-detect chat IDs.

Functions:
    validate_bot_token(bot_token: str) -> dict
    fetch_chat_id(bot_token: str) -> str | None
    send_telegram_message(bot_token: str, chat_id: str, text: str, video_url: str) -> bool
"""

import httpx


async def validate_bot_token(bot_token: str) -> dict:
    """Validate a Telegram bot token by calling getMe.

    Args:
        bot_token: The Telegram bot token (from BotFather).

    Returns:
        Bot info dict with keys like 'id', 'first_name', 'username'.

    Raises:
        ValueError: If the token is invalid.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"https://api.telegram.org/bot{bot_token}/getMe")
        data = resp.json()
        if not data.get("ok"):
            raise ValueError("Virheellinen bot-token. Tarkista token BotFatherilta.")
        return data["result"]


async def fetch_chat_id(bot_token: str) -> str | None:
    """Try to auto-detect the chat ID from recent messages sent to the bot.

    The user should send /start to the bot before calling this.

    Args:
        bot_token: The Telegram bot token.

    Returns:
        The chat ID as a string, or None if no messages found.
    """
    async with httpx.AsyncClient(timeout=15) as client:
        resp = await client.get(f"https://api.telegram.org/bot{bot_token}/getUpdates")
        data = resp.json()
        if not data.get("ok"):
            return None
        updates = data.get("result", [])
        if not updates:
            return None
        # Return the chat_id from the most recent message
        for update in reversed(updates):
            msg = update.get("message") or update.get("my_chat_member", {})
            chat = msg.get("chat") if isinstance(msg, dict) else None
            if chat and chat.get("id"):
                return str(chat["id"])
        return None


async def send_telegram_message(
    bot_token: str,
    chat_id: str,
    text: str,
    video_url: str,
) -> bool:
    """Send a message to a Telegram chat via the Bot API.

    Always appends the source video link so the user can verify.

    Args:
        bot_token: The Telegram bot token (from BotFather).
        chat_id: Target chat or channel ID.
        text: AI-generated summary text.
        video_url: Original YouTube video URL.

    Returns:
        True if the message was sent successfully.
    """
    full_text = f"{text}\n\n🔗 Source: {video_url}"

    # Telegram message limit is 4096 chars; split if needed
    chunks = [full_text[i : i + 4096] for i in range(0, len(full_text), 4096)]

    async with httpx.AsyncClient(timeout=30) as client:
        for chunk in chunks:
            resp = await client.post(
                f"https://api.telegram.org/bot{bot_token}/sendMessage",
                json={"chat_id": chat_id, "text": chunk, "parse_mode": "HTML"},
            )
            if resp.status_code != 200:
                return False
    return True
