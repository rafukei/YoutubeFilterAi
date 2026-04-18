"""
OpenRouter AI client with rate-limiting for free-tier usage.

Functions:
    query_ai(prompt: str, transcript: str, api_token: str) -> str
    get_available_models(api_token: str) -> list[dict]

The rate limiter uses Redis to track per-user request counts and
prevents exceeding OPENROUTER_FREE_RPM (requests per minute).
"""

import json
from typing import Optional, List

import httpx
import redis.asyncio as aioredis

from app.config import get_settings

settings = get_settings()

# Popular free and paid models on OpenRouter (fallback list)
DEFAULT_MODELS = [
    {"id": "openai/gpt-3.5-turbo", "name": "GPT-3.5 Turbo", "context_length": 16385, "pricing": {"prompt": 0.0005, "completion": 0.0015}, "description": "Fast and affordable, great for summaries"},
    {"id": "openai/gpt-4o-mini", "name": "GPT-4o Mini", "context_length": 128000, "pricing": {"prompt": 0.00015, "completion": 0.0006}, "description": "Excellent balance of speed and quality"},
    {"id": "openai/gpt-4o", "name": "GPT-4o", "context_length": 128000, "pricing": {"prompt": 0.005, "completion": 0.015}, "description": "Most capable, best for complex analysis"},
    {"id": "anthropic/claude-3-haiku", "name": "Claude 3 Haiku", "context_length": 200000, "pricing": {"prompt": 0.00025, "completion": 0.00125}, "description": "Fast and affordable Anthropic model"},
    {"id": "anthropic/claude-3.5-sonnet", "name": "Claude 3.5 Sonnet", "context_length": 200000, "pricing": {"prompt": 0.003, "completion": 0.015}, "description": "Excellent reasoning and writing"},
    {"id": "google/gemini-pro-1.5", "name": "Gemini Pro 1.5", "context_length": 2097152, "pricing": {"prompt": 0.00125, "completion": 0.005}, "description": "Massive context window, good for long transcripts"},
    {"id": "meta-llama/llama-3.1-70b-instruct", "name": "Llama 3.1 70B", "context_length": 131072, "pricing": {"prompt": 0.00035, "completion": 0.0004}, "description": "Open source, high quality"},
    {"id": "meta-llama/llama-3.1-8b-instruct", "name": "Llama 3.1 8B", "context_length": 131072, "pricing": {"prompt": 0.00005, "completion": 0.00005}, "description": "Free tier available, fast"},
    {"id": "mistralai/mistral-7b-instruct", "name": "Mistral 7B", "context_length": 32768, "pricing": {"prompt": 0.00005, "completion": 0.00005}, "description": "Free tier, efficient"},
    {"id": "qwen/qwen-2-72b-instruct", "name": "Qwen 2 72B", "context_length": 32768, "pricing": {"prompt": 0.00035, "completion": 0.0004}, "description": "Strong multilingual support"},
]


async def get_available_models(api_token: Optional[str] = None) -> List[dict]:
    """Fetch available models from OpenRouter API.

    Args:
        api_token: Optional API token for authenticated requests.

    Returns:
        List of model dictionaries with id, name, context_length, pricing, description.
        Falls back to curated default list on API failure.
    """
    try:
        headers = {"Content-Type": "application/json"}
        if api_token:
            headers["Authorization"] = f"Bearer {api_token}"

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                f"{settings.OPENROUTER_BASE_URL}/models",
                headers=headers,
            )
            response.raise_for_status()
            data = response.json()

            models = []
            for model in data.get("data", []):
                models.append({
                    "id": model.get("id"),
                    "name": model.get("name", model.get("id")),
                    "context_length": model.get("context_length", 4096),
                    "pricing": model.get("pricing", {}),
                    "description": model.get("description", ""),
                })

            # Sort by name for easier browsing
            models.sort(key=lambda m: m["name"].lower())
            return models

    except Exception:
        # Return curated default list if API fails
        return DEFAULT_MODELS


async def _check_rate_limit(user_id: str, redis_client: aioredis.Redis) -> None:
    """Enforce per-user rate limit for OpenRouter calls.

    Args:
        user_id: UUID string identifying the user.
        redis_client: Async Redis connection.

    Raises:
        RuntimeError: If the user has exceeded the free-tier RPM.
    """
    key = f"openrouter:rpm:{user_id}"
    current = await redis_client.get(key)
    if current and int(current) >= settings.OPENROUTER_FREE_RPM:
        raise RuntimeError(
            f"Rate limit exceeded ({settings.OPENROUTER_FREE_RPM} requests/min). "
            "Please wait before sending another query."
        )
    pipe = redis_client.pipeline()
    pipe.incr(key)
    pipe.expire(key, 60)  # 60-second sliding window
    await pipe.execute()


async def query_ai(
    prompt: str,
    transcript: str,
    api_token: str,
    user_id: str,
    redis_client: aioredis.Redis,
    model: str = "openai/gpt-3.5-turbo",
) -> str:
    """Send a prompt + transcript to OpenRouter and return the AI response.

    Args:
        prompt: The user's prompt template (must include routing JSON block).
        transcript: Raw YouTube transcript text.
        api_token: User's personal OpenRouter API token.
        user_id: For rate-limit tracking.
        redis_client: Async Redis connection.
        model: OpenRouter model identifier.

    Returns:
        The AI-generated response text.

    Raises:
        RuntimeError: On rate limit or API errors.
    """
    await _check_rate_limit(user_id, redis_client)

    full_prompt = f"{prompt}\n\n--- VIDEO TRANSCRIPT ---\n{transcript}"

    async with httpx.AsyncClient(timeout=120) as client:
        response = await client.post(
            f"{settings.OPENROUTER_BASE_URL}/chat/completions",
            headers={
                "Authorization": f"Bearer {api_token}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": [
                    {"role": "system", "content": "You process YouTube video transcripts according to user instructions."},
                    {"role": "user", "content": full_prompt},
                ],
            },
        )
        response.raise_for_status()
        data = response.json()
        return data["choices"][0]["message"]["content"]


def parse_ai_routing(ai_response: str) -> dict:
    """Extract the JSON routing block from the end of an AI response.

    The prompt instructs the AI to append a JSON block like:
        {"message": "...", "telegram_bots": [...], "web_views": [...], "visibility": true}

    Args:
        ai_response: Full AI response text.

    Returns:
        Parsed dict with keys: message, telegram_bots, web_views, visibility.
        Falls back to defaults if JSON is missing.
    """
    # Try to find the last JSON object in the response
    try:
        last_brace = ai_response.rfind("}")
        first_brace = ai_response.rfind("{", 0, last_brace)
        if first_brace != -1:
            candidate = ai_response[first_brace : last_brace + 1]
            parsed = json.loads(candidate)
            if "message" in parsed:
                return parsed
    except (json.JSONDecodeError, ValueError):
        pass

    # Fallback: treat entire response as the message
    return {
        "message": ai_response,
        "telegram_bots": [],
        "web_views": [],
        "visibility": True,
    }
