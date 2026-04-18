"""
Tests for database maintenance features:
- Message history limit (cleanup)
- User data export (prompts + channels)
- Admin backup
- AppSettings max_message_history field
"""

import pytest
import pytest_asyncio
from httpx import AsyncClient
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User, Message, Prompt, YouTubeChannel, AppSettings
from app.auth import create_access_token, hash_password


# ── Message History Limit ────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cleanup_messages_deletes_oldest(client: AsyncClient, test_user: User, test_session: AsyncSession, admin_headers: dict):
    """Cleanup should delete oldest messages when count exceeds max_message_history."""
    # Create app_settings with limit of 3
    settings = AppSettings(key="default", max_message_history=3)
    test_session.add(settings)
    await test_session.commit()

    # Create 5 messages for the user
    for i in range(5):
        msg = Message(
            user_id=test_user.id,
            source_video_url=f"https://youtube.com/watch?v=test{i}",
            ai_response=f"Response {i}",
        )
        test_session.add(msg)
    await test_session.commit()

    # Run cleanup
    resp = await client.post("/api/admin/cleanup-messages", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["deleted_messages"] == 2
    assert data["max_message_history"] == 3

    # Verify only 3 messages remain
    count = await test_session.scalar(
        select(func.count(Message.id)).where(Message.user_id == test_user.id)
    )
    assert count == 3


@pytest.mark.asyncio
async def test_cleanup_messages_no_excess(client: AsyncClient, test_user: User, test_session: AsyncSession, admin_headers: dict):
    """Cleanup should not delete anything when under the limit."""
    settings = AppSettings(key="default", max_message_history=100)
    test_session.add(settings)
    await test_session.commit()

    msg = Message(
        user_id=test_user.id,
        source_video_url="https://youtube.com/watch?v=test",
        ai_response="Response",
    )
    test_session.add(msg)
    await test_session.commit()

    resp = await client.post("/api/admin/cleanup-messages", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["deleted_messages"] == 0


@pytest.mark.asyncio
async def test_cleanup_messages_unlimited(client: AsyncClient, test_user: User, test_session: AsyncSession, admin_headers: dict):
    """When max_message_history is 0 (unlimited), nothing is deleted."""
    settings = AppSettings(key="default", max_message_history=0)
    test_session.add(settings)
    await test_session.commit()

    for i in range(10):
        test_session.add(Message(
            user_id=test_user.id,
            source_video_url=f"https://youtube.com/watch?v=test{i}",
            ai_response=f"Response {i}",
        ))
    await test_session.commit()

    resp = await client.post("/api/admin/cleanup-messages", headers=admin_headers)
    assert resp.status_code == 200
    assert resp.json()["deleted_messages"] == 0


@pytest.mark.asyncio
async def test_cleanup_requires_admin(client: AsyncClient, auth_headers: dict):
    """Regular user cannot run cleanup."""
    resp = await client.post("/api/admin/cleanup-messages", headers=auth_headers)
    assert resp.status_code == 403


# ── Max Message History in Settings ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_update_max_message_history(client: AsyncClient, test_session: AsyncSession, admin_headers: dict):
    """Admin can update max_message_history via settings patch."""
    resp = await client.patch(
        "/api/admin/settings",
        json={"max_message_history": 500},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["max_message_history"] == 500


@pytest.mark.asyncio
async def test_get_settings_includes_max_message_history(client: AsyncClient, test_session: AsyncSession, admin_headers: dict):
    """GET settings should include the max_message_history field."""
    resp = await client.get("/api/admin/settings", headers=admin_headers)
    assert resp.status_code == 200
    assert "max_message_history" in resp.json()


# ── User Data Export ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_export_user_data(client: AsyncClient, test_user: User, test_session: AsyncSession, auth_headers: dict):
    """User can export their prompts and channels."""
    # Create some prompts and channels
    prompt = Prompt(user_id=test_user.id, name="My Prompt", body="Summarize this")
    channel = YouTubeChannel(
        user_id=test_user.id,
        channel_id="UC123",
        channel_name="Test Channel",
    )
    test_session.add_all([prompt, channel])
    await test_session.commit()

    resp = await client.get("/api/export", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["email"] == test_user.email
    assert len(data["prompts"]) == 1
    assert data["prompts"][0]["name"] == "My Prompt"
    assert len(data["channels"]) == 1
    assert data["channels"][0]["channel_name"] == "Test Channel"
    assert "exported_at" in data


@pytest.mark.asyncio
async def test_export_empty_data(client: AsyncClient, test_user: User, auth_headers: dict):
    """Export works even with no data."""
    resp = await client.get("/api/export", headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["prompts"] == []
    assert data["channels"] == []


@pytest.mark.asyncio
async def test_export_requires_auth(client: AsyncClient):
    """Export endpoint requires authentication."""
    resp = await client.get("/api/export")
    assert resp.status_code == 401


# ── User Data Import ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_import_user_data(client: AsyncClient, test_user: User, auth_headers: dict):
    """User can import prompts and channels from JSON."""
    payload = {
        "prompts": [
            {"name": "Imported Prompt", "body": "Do something", "ai_model": "openai/gpt-3.5-turbo"},
            {"name": "Imported Folder", "is_folder": True},
        ],
        "channels": [
            {"channel_id": "UCimport1", "channel_name": "Imported Channel"},
        ],
    }
    resp = await client.post("/api/import", json=payload, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["prompts_imported"] == 2
    assert data["channels_imported"] == 1
    assert data["prompts_skipped"] == 0
    assert data["channels_skipped"] == 0


@pytest.mark.asyncio
async def test_import_skips_duplicates(client: AsyncClient, test_user: User, test_session: AsyncSession, auth_headers: dict):
    """Import skips prompts/channels that already exist."""
    # Create existing data
    test_session.add(Prompt(user_id=test_user.id, name="Existing Prompt", body="body"))
    test_session.add(YouTubeChannel(user_id=test_user.id, channel_id="UCexist", channel_name="Existing"))
    await test_session.commit()

    payload = {
        "prompts": [
            {"name": "Existing Prompt", "body": "Different body"},
            {"name": "New Prompt", "body": "New body"},
        ],
        "channels": [
            {"channel_id": "UCexist", "channel_name": "Existing Again"},
            {"channel_id": "UCnew", "channel_name": "New Channel"},
        ],
    }
    resp = await client.post("/api/import", json=payload, headers=auth_headers)
    assert resp.status_code == 200
    data = resp.json()
    assert data["prompts_imported"] == 1
    assert data["prompts_skipped"] == 1
    assert data["channels_imported"] == 1
    assert data["channels_skipped"] == 1


@pytest.mark.asyncio
async def test_import_requires_auth(client: AsyncClient):
    """Import endpoint requires authentication."""
    resp = await client.post("/api/import", json={"prompts": [], "channels": []})
    assert resp.status_code == 401


# ── Admin Backup ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_admin_backup(client: AsyncClient, test_user: User, test_session: AsyncSession, admin_headers: dict):
    """Admin backup returns complete database dump."""
    # Create some data
    prompt = Prompt(user_id=test_user.id, name="Backup Prompt", body="body")
    test_session.add(prompt)
    msg = Message(
        user_id=test_user.id,
        source_video_url="https://youtube.com/watch?v=backup",
        ai_response="Backup response",
    )
    test_session.add(msg)
    await test_session.commit()

    resp = await client.get("/api/admin/backup", headers=admin_headers)
    assert resp.status_code == 200
    data = resp.json()

    assert "backup_created_at" in data
    assert "users" in data
    assert "prompts" in data
    assert "messages" in data
    assert "youtube_channels" in data
    assert "telegram_bots" in data
    assert "web_views" in data
    assert "app_settings" in data

    # Verify user data is present
    assert len(data["users"]) >= 1
    assert len(data["prompts"]) >= 1
    assert len(data["messages"]) >= 1

    # Verify no passwords in backup
    for u in data["users"]:
        assert "hashed_password" not in u


@pytest.mark.asyncio
async def test_admin_backup_requires_admin(client: AsyncClient, auth_headers: dict):
    """Regular user cannot access backup."""
    resp = await client.get("/api/admin/backup", headers=auth_headers)
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_admin_backup_no_auth(client: AsyncClient):
    """Backup requires authentication."""
    resp = await client.get("/api/admin/backup")
    assert resp.status_code == 401
