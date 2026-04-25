"""OpenRouter AI client with rate-limiting and helper utilities.

This module provides a small wrapper around OpenRouter's chat/completions
API including:

- Model discovery: ``get_available_models`` fetches available models (with a
    curated fallback list in ``DEFAULT_MODELS``).
- Per-user free-tier rate limiting enforced by Redis: ``_check_rate_limit``.
- A higher-level ``query_ai`` which sends a prompt + transcript to OpenRouter,
    optionally retries a fallback model on capacity/context errors, and returns
    the AI text output.
- Helpers to parse the JSON routing block appended by the AI (``parse_ai_routing``)
    and to resolve prompt folders to leaf prompts (``resolve_folder_prompts``).

All functions follow the project's docstring style (Args, Returns, Raises).
The rate limiter uses the ``OPENROUTER_FREE_RPM`` setting (env) by default.
"""

import json
from typing import Optional, List
from uuid import UUID

import httpx
import redis.asyncio as aioredis
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
import logging

from app.config import get_settings

settings = get_settings()

logger = logging.getLogger(__name__)

# Popular free and paid models on OpenRouter (fallback list).
# Each entry contains an `id` matching OpenRouter, a human-friendly `name`,
# an estimated `context_length` (tokens), a small `pricing` hint and a short
# `description`. This list is used as a fallback when the OpenRouter models
# endpoint is unreachable.
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

    This function queries OpenRouter's `/models` endpoint. If the network
    request fails or the API is unavailable, a curated fallback list defined
    in ``DEFAULT_MODELS`` is returned so the UI can still present choices.

    Args:
        api_token: Optional API token for authenticated requests. If provided
            it is added to the Authorization header.

    Returns:
        A list of model dictionaries. Each dict contains keys: ``id``,
        ``name``, ``context_length``, ``pricing`` and ``description``.

    Raises:
        None: network/API errors are swallowed and the fallback list is
        returned to keep the caller simple.
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

    The implementation stores a per-user counter in Redis with a 60-second
    expiry (sliding window). If the counter is >= ``settings.OPENROUTER_FREE_RPM``
    a ``RuntimeError`` is raised and the caller should surface that to the
    user (HTTP 429/502-equivalent behavior in the API handlers).

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
    model: str = "openai/gpt-4.1-mini",
    fallback_model: Optional[str] = None,
) -> str:
    """Send a prompt + transcript to OpenRouter and return the AI response.

    This is the main entrypoint used by the processing pipeline. It performs
    the following high-level steps:
    1. Enforces per-user rate limit via ``_check_rate_limit``.
    2. Sends the prompt + transcript to the chosen OpenRouter model.
    3. If the model responds with an error that looks like a capacity or
       context-length issue and a ``fallback_model`` is provided, the call
       is retried once using the fallback model (rate limit is re-checked).

    Args:
        prompt: The user's prompt template (string). In this application the
            prompt is expected to end with a JSON routing block that the AI
            should echo back (telegram_bots, web_views, visibility).
        transcript: Raw YouTube transcript text to be appended to the prompt.
        api_token: User's personal OpenRouter API token used for Authorization.
        user_id: User UUID string used for per-user rate limiting in Redis.
        redis_client: Async Redis client instance used by the rate limiter.
        model: Primary OpenRouter model identifier (e.g. "openai/gpt-3.5-turbo").
        fallback_model: Optional fallback model to try when the primary fails
            on capacity/context errors.

    Returns:
        The AI-generated response text (string) from the chosen model.

    Raises:
        RuntimeError: If the user is rate-limited, or if OpenRouter returns an
            error for both primary and fallback models. The error message
            includes the model id and the upstream error body when available.
    """
    await _check_rate_limit(user_id, redis_client)

    # Debug: log incoming call parameters so we can trace which model is used
    try:
        prompt_len = len(prompt) if prompt else 0
        transcript_chars = len(transcript) if transcript else 0
    except Exception:
        prompt_len = 0
        transcript_chars = 0
    logger.debug("query_ai called: user=%s model=%s fallback=%s prompt_len=%d transcript_chars=%d",
                 user_id, model, fallback_model, prompt_len, transcript_chars)

    full_prompt = f"{prompt}\n\n--- VIDEO TRANSCRIPT ---\n{transcript}"

    # Errors that indicate the primary model can't handle the input
    _FALLBACK_KEYWORDS = (
        "context_length", "context length", "too long", "token limit",
        "max_tokens", "capacity", "overloaded", "503", "model_not_available",
    )

    async def _call_model(chosen_model: str) -> str:
        """Make a single OpenRouter API call with the given model.

        Args:
            chosen_model: Model id to request from OpenRouter.

        Returns:
            The response body string from the model (assistant content).

        Raises:
            RuntimeError: If OpenRouter responds with a non-2xx status code
                or if the response JSON cannot be parsed into the expected
                structure.
        """
        # Log the outgoing model and approximate token estimate for debugging
        try:
            approx_tokens = int(len(full_prompt) / 4)
        except Exception:
            approx_tokens = 0
        # Try to find a known context length for the chosen model so we can
        # pre-flight reject or switch to a fallback before sending to OpenRouter.
        model_info = next((m for m in DEFAULT_MODELS if m.get("id") == chosen_model), None)
        if model_info and model_info.get("context_length"):
            if approx_tokens > int(model_info["context_length"]):
                # If a fallback model is provided and it can handle the input,
                # use it instead of calling the undersized model.
                fb_info = next((m for m in DEFAULT_MODELS if m.get("id") == fallback_model), None) if fallback_model else None
                if fb_info and approx_tokens <= int(fb_info.get("context_length", 0)):
                    logger.warning(
                        "Estimated tokens (%d) exceed model %s context (%d) — switching to fallback %s",
                        approx_tokens, chosen_model, model_info["context_length"], fallback_model,
                    )
                    chosen_model = fallback_model
                else:
                    # No adequate fallback: raise a clear error so the API can
                    # return a 400 with an actionable message instead of a
                    # 502 from an upstream 400.
                    raise RuntimeError(
                        f"Estimated prompt size ({approx_tokens} tokens) exceeds the context length for model {chosen_model} ({model_info['context_length']} tokens). "
                        "Choose a model with a larger context window (e.g. openai/gpt-4o-mini) or shorten the transcript."
                    )

        logger.info("OpenRouter request: user=%s model=%s approx_prompt_tokens=%d", user_id, chosen_model, approx_tokens)

        async with httpx.AsyncClient(timeout=120) as client:
            response = await client.post(
                f"{settings.OPENROUTER_BASE_URL}/chat/completions",
                headers={
                    "Authorization": f"Bearer {api_token}",
                    "Content-Type": "application/json",
                },
                json={
                    "model": chosen_model,
                    "messages": [
                        {"role": "system", "content": (
                        "You process YouTube video transcripts according to user instructions. "
                        "IMPORTANT: The JSON routing block at the end of the user's prompt defines where to send results. "
                        "You MUST always preserve the telegram_bots and web_views arrays exactly as given. "
                        "The 'visibility' field controls ALL delivery: when false, the message is stored but NOT sent to Telegram or shown on web."
                    )},
                        {"role": "user", "content": full_prompt},
                    ],
                },
            )
            if response.status_code >= 400:
                # Read the error body for a meaningful message
                try:
                    err_body = response.json()
                    err_msg = err_body.get("error", {}).get("message", "") or str(err_body)
                except Exception:
                    err_msg = response.text[:500]
                raise RuntimeError(
                    f"OpenRouter API error {response.status_code} (model: {chosen_model}): {err_msg}"
                )
            data = response.json()
            return data["choices"][0]["message"]["content"]

    # Try primary model
    try:
        return await _call_model(model)
    except Exception as primary_err:
        err_str = str(primary_err).lower()
        if fallback_model and any(kw in err_str for kw in _FALLBACK_KEYWORDS):
            # Primary failed on capacity/context — try fallback
            # Check rate limit again for the second call
            await _check_rate_limit(user_id, redis_client)
            try:
                return await _call_model(fallback_model)
            except Exception as fallback_err:
                raise RuntimeError(
                    f"Both models failed. Primary ({model}): {primary_err}; "
                    f"Fallback ({fallback_model}): {fallback_err}"
                )
        raise


def parse_ai_routing(ai_response: str, prompt_routing: dict | None = None) -> dict:
    """Extract the JSON routing block from the end of an AI response.

    The prompt instructs the AI to append a JSON block like:
        {"message": "...", "telegram_bots": ["bot_name"], "web_views": ["view_name"], "visibility": true}

    If the AI omits routing fields (e.g. telegram_bots), the original prompt's
    routing block is used as fallback to ensure delivery targets are preserved.

    Args:
        ai_response: Full AI response text.
        prompt_routing: Optional dict parsed from the prompt's own routing JSON.
            Used as fallback for telegram_bots / web_views if AI omits them.

    Returns:
        A dict with keys: ``message`` (string), ``telegram_bots`` (list),
        ``web_views`` (list) and ``visibility`` (bool). If the AI did not
        append a valid JSON object with a ``message`` key, the entire AI
        response is returned as the ``message`` and arrays/defaults are used
        for the other fields.

    Raises:
        None: parsing failures are handled gracefully and a sensible fallback
        dict is returned.
    """
    prompt_routing = prompt_routing or {}

    # Try to find the last JSON object in the response
    try:
        last_brace = ai_response.rfind("}")
        first_brace = ai_response.rfind("{", 0, last_brace)
        if first_brace != -1:
            candidate = ai_response[first_brace : last_brace + 1]
            parsed = json.loads(candidate)
            if "message" in parsed:
                # Merge: use prompt's routing targets as fallback if AI dropped them
                if not parsed.get("telegram_bots") and prompt_routing.get("telegram_bots"):
                    parsed["telegram_bots"] = prompt_routing["telegram_bots"]
                if not parsed.get("web_views") and prompt_routing.get("web_views"):
                    parsed["web_views"] = prompt_routing["web_views"]
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


async def resolve_folder_prompts(
    prompt_id: UUID,
    user_id: UUID,
    db: AsyncSession,
) -> list:
    """Resolve a prompt_id to a list of executable prompts.

    If the prompt is a regular prompt, returns it in a single-element list.
    If it's a folder, returns all non-folder child prompts (recursive).

    Args:
        prompt_id: UUID of the prompt or folder.
        user_id: Owner UUID (security check).
        db: Async database session.

    Returns:
        A list of Prompt ORM objects (leaf prompts with a non-empty ``body``).

    Raises:
        None: If the referenced prompt does not exist or the folder is empty
        an empty list is returned.
    """
    from app.models import Prompt  # local import to avoid circular

    result = await db.execute(
        select(Prompt).where(Prompt.id == prompt_id, Prompt.user_id == user_id)
    )
    prompt = result.scalar_one_or_none()
    if not prompt:
        return []

    if not prompt.is_folder:
        return [prompt] if prompt.body else []

    # Recursively collect all child prompts from this folder
    collected: list = []

    async def _collect_children(parent_id: UUID) -> None:
        children_result = await db.execute(
            select(Prompt).where(Prompt.parent_id == parent_id, Prompt.user_id == user_id)
        )
        for child in children_result.scalars().all():
            if child.is_folder:
                await _collect_children(child.id)
            elif child.body:
                collected.append(child)

    await _collect_children(prompt_id)
    return collected
