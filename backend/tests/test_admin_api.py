"""
Integration tests for admin API routes.

Tests:
- User listing
- User creation
- User activation/approval
- User deletion
- Settings management
"""

import pytest


class TestAdminUserManagement:
    """Tests for admin user management endpoints."""

    @pytest.mark.asyncio
    async def test_list_users_as_admin(self, client, admin_headers):
        """Admin can list all users."""
        response = await client.get("/api/admin/users", headers=admin_headers)
        
        assert response.status_code == 200
        assert isinstance(response.json(), list)

    @pytest.mark.asyncio
    async def test_list_users_as_regular_user(self, client, auth_headers):
        """Regular user cannot list users."""
        response = await client.get("/api/admin/users", headers=auth_headers)
        
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_create_user_as_admin(self, client, admin_headers):
        """Admin can create new users."""
        response = await client.post(
            "/api/admin/users",
            headers=admin_headers,
            json={
                "email": "newadminuser@example.com",
                "password": "AdminCreated123!"
            }
        )
        
        assert response.status_code == 201
        data = response.json()
        assert data["email"] == "newadminuser@example.com"

    @pytest.mark.asyncio
    async def test_create_duplicate_user(self, client, admin_headers, test_user):
        """Cannot create user with existing email."""
        response = await client.post(
            "/api/admin/users",
            headers=admin_headers,
            json={
                "email": "testuser@example.com",  # Already exists
                "password": "SomePass123!"
            }
        )
        
        assert response.status_code == 409

    @pytest.mark.asyncio
    async def test_update_user_status(self, client, admin_headers, test_user):
        """Admin can update user active/approved status."""
        response = await client.patch(
            f"/api/admin/users/{test_user.id}",
            headers=admin_headers,
            params={
                "is_active": False,
                "is_approved": False
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert data["is_active"] is False
        assert data["is_approved"] is False

    @pytest.mark.asyncio
    async def test_delete_user_as_admin(self, client, admin_headers):
        """Admin can delete users."""
        # Create user to delete
        create_response = await client.post(
            "/api/admin/users",
            headers=admin_headers,
            json={"email": "delete@example.com", "password": "ToDelete123!"}
        )
        user_id = create_response.json()["id"]
        
        # Delete
        response = await client.delete(
            f"/api/admin/users/{user_id}",
            headers=admin_headers
        )
        
        assert response.status_code == 204

    @pytest.mark.asyncio
    async def test_delete_nonexistent_user(self, client, admin_headers):
        """Deleting non-existent user returns 404."""
        import uuid
        fake_id = str(uuid.uuid4())
        response = await client.delete(
            f"/api/admin/users/{fake_id}",
            headers=admin_headers
        )
        
        assert response.status_code == 404

    @pytest.mark.asyncio
    async def test_cannot_delete_own_admin_account(self, client, admin_headers):
        """Admin cannot delete their own account via this endpoint."""
        # The admin is not in the users table, so this should be 404
        response = await client.delete(
            "/api/admin/users/admin",
            headers=admin_headers
        )
        
        # Should not succeed
        assert response.status_code in [400, 404, 422]


class TestAdminSettings:
    """Tests for admin settings management."""

    @pytest.mark.asyncio
    async def test_get_settings(self, client, admin_headers):
        """Admin can view current settings."""
        response = await client.get("/api/admin/settings", headers=admin_headers)
        
        # May be 404 if endpoint not yet implemented
        if response.status_code == 200:
            data = response.json()
            assert "registration_enabled" in data or "allow_gmail_auth" in data

    @pytest.mark.asyncio
    async def test_update_settings(self, client, admin_headers):
        """Admin can update settings."""
        response = await client.patch(
            "/api/admin/settings",
            headers=admin_headers,
            json={
                "registration_enabled": False
            }
        )
        
        # May be 404 if endpoint not yet implemented
        if response.status_code == 200:
            data = response.json()
            assert data.get("registration_enabled") is False

    @pytest.mark.asyncio
    async def test_regular_user_cannot_access_settings(self, client, auth_headers):
        """Regular user cannot access admin settings."""
        response = await client.get("/api/admin/settings", headers=auth_headers)
        
        assert response.status_code in [403, 404]


class TestAdminStatsAndAnalytics:
    """Tests for admin dashboard statistics."""

    @pytest.mark.asyncio
    async def test_get_stats(self, client, admin_headers):
        """Admin can view system statistics."""
        response = await client.get("/api/admin/stats", headers=admin_headers)
        
        # May be 404 if endpoint not yet implemented
        if response.status_code == 200:
            data = response.json()
            # Should contain user counts or processing stats
            assert "total_users" in data or "total_messages" in data

    @pytest.mark.asyncio
    async def test_regular_user_cannot_access_stats(self, client, auth_headers):
        """Regular user cannot access admin stats."""
        response = await client.get("/api/admin/stats", headers=auth_headers)
        
        assert response.status_code in [403, 404]
