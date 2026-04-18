"""
Integration tests for resource CRUD API routes.
"""

import pytest
from unittest.mock import AsyncMock, patch


class TestPromptsAPI:

    @pytest.mark.asyncio
    async def test_list_prompts_empty(self, client, auth_headers):
        response = await client.get("/api/prompts", headers=auth_headers)
        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_create_prompt(self, client, auth_headers):
        payload = {"name": "Tech News Filter", "content": "Summarize tech news."}
        response = await client.post("/api/prompts", headers=auth_headers, json=payload)
        assert response.status_code == 201
        assert response.json()["name"] == "Tech News Filter"
        assert "id" in response.json()

    @pytest.mark.asyncio
    async def test_list_prompts_after_create(self, client, auth_headers):
        await client.post("/api/prompts", headers=auth_headers, json={"name": "Test Prompt", "content": "c"})
        response = await client.get("/api/prompts", headers=auth_headers)
        assert response.status_code == 200
        assert len(response.json()) >= 1

    @pytest.mark.asyncio
    async def test_update_prompt(self, client, auth_headers):
        cr = await client.post("/api/prompts", headers=auth_headers, json={"name": "Orig", "content": "c"})
        pid = cr.json()["id"]
        response = await client.patch(f"/api/prompts/{pid}", headers=auth_headers, json={"name": "Updated"})
        assert response.status_code == 200
        assert response.json()["name"] == "Updated"

    @pytest.mark.asyncio
    async def test_delete_prompt(self, client, auth_headers):
        cr = await client.post("/api/prompts", headers=auth_headers, json={"name": "Del", "content": "c"})
        pid = cr.json()["id"]
        response = await client.delete(f"/api/prompts/{pid}", headers=auth_headers)
        assert response.status_code == 204


class TestYouTubeChannelsAPI:

    @pytest.mark.asyncio
    async def test_list_channels_empty(self, client, auth_headers):
        response = await client.get("/api/channels", headers=auth_headers)
        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_create_channel(self, client, auth_headers):
        payload = {"channel_id": "UC123456789", "channel_name": "Tech Channel"}
        response = await client.post("/api/channels", headers=auth_headers, json=payload)
        assert response.status_code == 201
        assert response.json()["channel_id"] == "UC123456789"

    @pytest.mark.asyncio
    async def test_update_channel(self, client, auth_headers):
        cr = await client.post("/api/channels", headers=auth_headers, json={"channel_id": "UC111", "channel_name": "Orig"})
        cid = cr.json()["id"]
        response = await client.patch(f"/api/channels/{cid}", headers=auth_headers, json={"channel_name": "Updated"})
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_delete_channel(self, client, auth_headers):
        cr = await client.post("/api/channels", headers=auth_headers, json={"channel_id": "UC999", "channel_name": "Del"})
        cid = cr.json()["id"]
        response = await client.delete(f"/api/channels/{cid}", headers=auth_headers)
        assert response.status_code == 204


class TestTelegramBotsAPI:

    @pytest.mark.asyncio
    async def test_list_bots_empty(self, client, auth_headers):
        response = await client.get("/api/telegram-bots", headers=auth_headers)
        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_create_bot(self, client, auth_headers):
        with patch("app.services.telegram_service.validate_bot_token", new_callable=AsyncMock, return_value={"username": "test_bot"}):
            with patch("app.services.telegram_service.fetch_chat_id", new_callable=AsyncMock, return_value="-100123"):
                response = await client.post("/api/telegram-bots", headers=auth_headers, json={"bot_token": "123:ABC"})
        assert response.status_code == 201
        assert "id" in response.json()

    @pytest.mark.asyncio
    async def test_create_bot_invalid_token(self, client, auth_headers):
        with patch("app.services.telegram_service.validate_bot_token", new_callable=AsyncMock, side_effect=ValueError("Invalid")):
            response = await client.post("/api/telegram-bots", headers=auth_headers, json={"bot_token": "bad"})
        assert response.status_code == 400


class TestWebViewsAPI:

    @pytest.mark.asyncio
    async def test_list_webviews_empty(self, client, auth_headers):
        response = await client.get("/api/web-views", headers=auth_headers)
        assert response.status_code == 200
        assert response.json() == []

    @pytest.mark.asyncio
    async def test_create_webview(self, client, auth_headers):
        response = await client.post("/api/web-views", headers=auth_headers, json={"name": "daily_digest"})
        assert response.status_code == 201
        assert response.json()["name"] == "daily_digest"

    @pytest.mark.asyncio
    async def test_delete_webview(self, client, auth_headers):
        cr = await client.post("/api/web-views", headers=auth_headers, json={"name": "temp"})
        vid = cr.json()["id"]
        response = await client.delete(f"/api/web-views/{vid}", headers=auth_headers)
        assert response.status_code == 204


class TestResourceIsolation:

    @pytest.mark.asyncio
    async def test_cannot_delete_other_users_prompt(self, client, auth_headers):
        # Create a prompt as the default test user
        cr = await client.post("/api/prompts", headers=auth_headers, json={"name": "Private", "content": "Secret"})
        pid = cr.json()["id"]

        # Register a second user and get their token
        await client.post("/api/auth/register", json={
            "email": "other@example.com",
            "password": "OtherPass123!",
            "gdpr_consent": True
        })
        login = await client.post("/api/auth/login", json={
            "email": "other@example.com",
            "password": "OtherPass123!"
        })
        other_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

        # Other user should not be able to delete first user's prompt
        response = await client.delete(f"/api/prompts/{pid}", headers=other_headers)
        assert response.status_code == 404
