"""
Tests for Phase 2 features:
  - Folder prompt resolution (resolve_folder_prompts)
  - Fallback AI model logic
  - Channel → folder prompt multi-processing
"""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch, MagicMock
from uuid import uuid4

from app.models import Prompt, User
from app.services.ai_service import resolve_folder_prompts, query_ai, parse_ai_routing
from app.auth import hash_password, create_access_token


# ── resolve_folder_prompts ───────────────────────────────────────────────────

@pytest_asyncio.fixture
async def user_with_prompts(test_session):
    """Create a user with a folder containing child prompts."""
    user = User(
        email="folder_test@example.com",
        hashed_password=hash_password("testpassword123"),
        is_active=True,
        is_approved=True,
        openrouter_api_token="test-token",
    )
    test_session.add(user)
    await test_session.commit()
    await test_session.refresh(user)

    # Create folder
    folder = Prompt(
        user_id=user.id,
        name="News Folder",
        is_folder=True,
        body=None,
        ai_model=None,
    )
    test_session.add(folder)
    await test_session.commit()
    await test_session.refresh(folder)

    # Create child prompts inside the folder
    child1 = Prompt(
        user_id=user.id,
        parent_id=folder.id,
        name="Summary Prompt",
        is_folder=False,
        body="Summarize the video.",
        ai_model="openai/gpt-3.5-turbo",
        fallback_ai_model="google/gemini-pro-1.5",
    )
    child2 = Prompt(
        user_id=user.id,
        parent_id=folder.id,
        name="Analysis Prompt",
        is_folder=False,
        body="Analyze the video critically.",
        ai_model="openai/gpt-4o-mini",
        fallback_ai_model=None,
    )
    # Create a subfolder with a prompt
    subfolder = Prompt(
        user_id=user.id,
        parent_id=folder.id,
        name="Sub Folder",
        is_folder=True,
        body=None,
    )
    test_session.add_all([child1, child2, subfolder])
    await test_session.commit()
    await test_session.refresh(subfolder)

    nested_child = Prompt(
        user_id=user.id,
        parent_id=subfolder.id,
        name="Nested Prompt",
        is_folder=False,
        body="Extract key points.",
        ai_model="meta-llama/llama-3.1-8b-instruct",
    )
    test_session.add(nested_child)
    await test_session.commit()

    # Create a standalone prompt (not in folder)
    standalone = Prompt(
        user_id=user.id,
        name="Standalone Prompt",
        is_folder=False,
        body="Just summarize.",
        ai_model="openai/gpt-3.5-turbo",
    )
    test_session.add(standalone)
    await test_session.commit()
    await test_session.refresh(standalone)

    return {
        "user": user,
        "folder": folder,
        "child1": child1,
        "child2": child2,
        "subfolder": subfolder,
        "nested_child": nested_child,
        "standalone": standalone,
    }


@pytest.mark.asyncio
async def test_resolve_single_prompt(test_session, user_with_prompts):
    """Single (non-folder) prompt returns itself."""
    data = user_with_prompts
    result = await resolve_folder_prompts(data["standalone"].id, data["user"].id, test_session)
    assert len(result) == 1
    assert result[0].id == data["standalone"].id


@pytest.mark.asyncio
async def test_resolve_folder_returns_all_children(test_session, user_with_prompts):
    """Folder resolves to all child prompts (including nested)."""
    data = user_with_prompts
    result = await resolve_folder_prompts(data["folder"].id, data["user"].id, test_session)
    assert len(result) == 3  # child1, child2, nested_child
    names = {p.name for p in result}
    assert names == {"Summary Prompt", "Analysis Prompt", "Nested Prompt"}


@pytest.mark.asyncio
async def test_resolve_folder_excludes_empty_body(test_session, user_with_prompts):
    """Prompts without body are excluded from folder resolution."""
    data = user_with_prompts
    # Subfolder itself has no body, so it shouldn't appear in results
    result = await resolve_folder_prompts(data["folder"].id, data["user"].id, test_session)
    for p in result:
        assert p.body is not None
        assert p.body != ""


@pytest.mark.asyncio
async def test_resolve_nonexistent_prompt(test_session, user_with_prompts):
    """Non-existent prompt ID returns empty list."""
    data = user_with_prompts
    result = await resolve_folder_prompts(uuid4(), data["user"].id, test_session)
    assert result == []


@pytest.mark.asyncio
async def test_resolve_wrong_user(test_session, user_with_prompts):
    """Prompt belonging to another user returns empty list."""
    data = user_with_prompts
    result = await resolve_folder_prompts(data["folder"].id, uuid4(), test_session)
    assert result == []


# ── Fallback AI model ────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_query_ai_fallback_on_context_error(mock_redis):
    """When primary model fails with context_length error, fallback model is used."""
    with patch("app.services.ai_service.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        # First call (primary) raises context length error
        primary_response = MagicMock()
        primary_response.raise_for_status.side_effect = Exception("context_length_exceeded")

        # Second call (fallback) succeeds
        fallback_response = MagicMock()
        fallback_response.raise_for_status.return_value = None
        fallback_response.json.return_value = {
            "choices": [{"message": {"content": "Fallback result"}}]
        }

        mock_client.post = AsyncMock(side_effect=[primary_response, fallback_response])

        result = await query_ai(
            prompt="Test prompt",
            transcript="Test transcript",
            api_token="test-token",
            user_id="test-user",
            redis_client=mock_redis,
            model="small-model",
            fallback_model="big-model",
        )
        assert result == "Fallback result"
        assert mock_client.post.call_count == 2


@pytest.mark.asyncio
async def test_query_ai_no_fallback_on_other_error(mock_redis):
    """When primary model fails with non-context error and fallback exists, error is re-raised."""
    with patch("app.services.ai_service.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        primary_response = MagicMock()
        primary_response.raise_for_status.side_effect = Exception("authentication_failed")
        mock_client.post = AsyncMock(return_value=primary_response)

        with pytest.raises(Exception, match="authentication_failed"):
            await query_ai(
                prompt="Test prompt",
                transcript="Test transcript",
                api_token="bad-token",
                user_id="test-user",
                redis_client=mock_redis,
                model="small-model",
                fallback_model="big-model",
            )


@pytest.mark.asyncio
async def test_query_ai_no_fallback_configured(mock_redis):
    """When no fallback model is configured, context error is raised directly."""
    with patch("app.services.ai_service.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client_cls.return_value.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)

        primary_response = MagicMock()
        primary_response.raise_for_status.side_effect = Exception("context_length_exceeded")
        mock_client.post = AsyncMock(return_value=primary_response)

        with pytest.raises(Exception, match="context_length_exceeded"):
            await query_ai(
                prompt="Test prompt",
                transcript="Test transcript",
                api_token="test-token",
                user_id="test-user",
                redis_client=mock_redis,
                model="small-model",
                fallback_model=None,
            )


# ── API endpoint: folder processing ─────────────────────────────────────────

@pytest.mark.asyncio
async def test_process_video_with_folder_prompt(client, test_session, user_with_prompts):
    """POST /api/process with a folder prompt_id processes all child prompts."""
    data = user_with_prompts
    user = data["user"]
    token = create_access_token({"sub": str(user.id)})
    headers = {"Authorization": f"Bearer {token}"}

    with patch("app.api.process_routes.extract_video_id", return_value="dQw4w9WgXcQ"), \
         patch("app.api.process_routes.fetch_transcript", return_value="This is a test transcript"), \
         patch("app.api.process_routes.query_ai", new_callable=AsyncMock) as mock_ai:

        mock_ai.return_value = '{"message": "AI summary", "telegram_bots": [], "web_views": [], "visibility": true}'

        resp = await client.post("/api/process", json={
            "video_url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
            "prompt_id": str(data["folder"].id),
        }, headers=headers)

        assert resp.status_code == 200
        # Should have called AI once per child prompt (3 prompts in folder)
        assert mock_ai.call_count == 3


@pytest.mark.asyncio
async def test_process_video_with_single_prompt(client, test_session, user_with_prompts):
    """POST /api/process with a single prompt_id processes only that prompt."""
    data = user_with_prompts
    user = data["user"]
    token = create_access_token({"sub": str(user.id)})
    headers = {"Authorization": f"Bearer {token}"}

    with patch("app.api.process_routes.extract_video_id", return_value="dQw4w9WgXcQ"), \
         patch("app.api.process_routes.fetch_transcript", return_value="This is a test transcript"), \
         patch("app.api.process_routes.query_ai", new_callable=AsyncMock) as mock_ai:

        mock_ai.return_value = '{"message": "AI summary", "telegram_bots": [], "web_views": [], "visibility": true}'

        resp = await client.post("/api/process", json={
            "video_url": "https://youtube.com/watch?v=dQw4w9WgXcQ",
            "prompt_id": str(data["standalone"].id),
        }, headers=headers)

        assert resp.status_code == 200
        assert mock_ai.call_count == 1


# ── Schema tests ─────────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_prompt_create_with_fallback(client, test_session, user_with_prompts):
    """Creating a prompt with fallback_ai_model stores it correctly."""
    data = user_with_prompts
    token = create_access_token({"sub": str(data["user"].id)})
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.post("/api/prompts", json={
        "name": "Test With Fallback",
        "body": "Test body",
        "ai_model": "openai/gpt-3.5-turbo",
        "fallback_ai_model": "google/gemini-pro-1.5",
    }, headers=headers)

    assert resp.status_code == 201
    result = resp.json()
    assert result["fallback_ai_model"] == "google/gemini-pro-1.5"


@pytest.mark.asyncio
async def test_prompt_update_fallback(client, test_session, user_with_prompts):
    """Updating a prompt's fallback_ai_model works via PATCH."""
    data = user_with_prompts
    token = create_access_token({"sub": str(data["user"].id)})
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.patch(f"/api/prompts/{data['standalone'].id}", json={
        "fallback_ai_model": "anthropic/claude-3.5-sonnet",
    }, headers=headers)

    assert resp.status_code == 200
    assert resp.json()["fallback_ai_model"] == "anthropic/claude-3.5-sonnet"


@pytest.mark.asyncio
async def test_prompt_read_includes_fallback(client, test_session, user_with_prompts):
    """GET /api/prompts returns fallback_ai_model field."""
    data = user_with_prompts
    token = create_access_token({"sub": str(data["user"].id)})
    headers = {"Authorization": f"Bearer {token}"}

    resp = await client.get("/api/prompts", headers=headers)
    assert resp.status_code == 200
    prompts = resp.json()
    # Find the child1 prompt which has a fallback model
    child1 = next(p for p in prompts if p["name"] == "Summary Prompt")
    assert child1["fallback_ai_model"] == "google/gemini-pro-1.5"
