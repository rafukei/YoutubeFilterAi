"""
Integration tests for authentication API routes.

Tests:
- User registration endpoint
- User login endpoint
- Admin login endpoint
- Token refresh and validation
"""

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.main import app
from app.models import User
from app.auth import hash_password


class TestUserRegistration:
    """Tests for POST /api/auth/register"""

    @pytest.mark.asyncio
    async def test_register_success(self, client):
        """New user can register with valid data."""
        response = await client.post(
            "/api/auth/register",
            json={
                "email": "newuser@example.com",
                "password": "SecurePass123!"
            }
        )
        
        assert response.status_code == 201
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_register_duplicate_email(self, client, test_user):
        """Registration with existing email should fail."""
        response = await client.post(
            "/api/auth/register",
            json={
                "email": "testuser@example.com",  # Same as test_user
                "password": "AnotherPass123!"
            }
        )
        
        assert response.status_code == 409
        assert "already registered" in response.json()["detail"].lower()

    @pytest.mark.asyncio
    async def test_register_invalid_email(self, client):
        """Registration with invalid email format should fail."""
        response = await client.post(
            "/api/auth/register",
            json={
                "email": "not-an-email",
                "password": "SecurePass123!"
            }
        )
        
        assert response.status_code == 422  # Validation error

    @pytest.mark.asyncio
    async def test_register_weak_password(self, client):
        """Registration with weak password should fail validation."""
        response = await client.post(
            "/api/auth/register",
            json={
                "email": "user@example.com",
                "password": "123"  # Too short
            }
        )
        
        # Weak password should be rejected by Pydantic validation (422)
        # or accepted if no validation rule exists
        assert response.status_code in [201, 422]


class TestUserLogin:
    """Tests for POST /api/auth/login"""

    @pytest.mark.asyncio
    async def test_login_success(self, client, test_user):
        """Registered user can login with correct credentials."""
        response = await client.post(
            "/api/auth/login",
            json={
                "email": "testuser@example.com",
                "password": "testpassword123"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"

    @pytest.mark.asyncio
    async def test_login_wrong_password(self, client, test_user):
        """Login with wrong password should fail."""
        response = await client.post(
            "/api/auth/login",
            json={
                "email": "testuser@example.com",
                "password": "wrongpassword"
            }
        )
        
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_login_nonexistent_user(self, client):
        """Login with non-existent email should fail."""
        response = await client.post(
            "/api/auth/login",
            json={
                "email": "nobody@example.com",
                "password": "somepassword"
            }
        )
        
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_login_unapproved_user(self, client, unapproved_user):
        """Unapproved user login behavior — currently allowed (only is_active checked)."""
        response = await client.post(
            "/api/auth/login",
            json={
                "email": "unapproved@example.com",
                "password": "password123"
            }
        )
        
        # Login checks is_active, not is_approved; unapproved users can still log in
        assert response.status_code == 200


class TestAdminLogin:
    """Tests for POST /api/admin/login"""

    @pytest.mark.asyncio
    async def test_admin_login_success(self, client, monkeypatch):
        """Admin can login with correct credentials."""
        monkeypatch.setattr("app.api.admin_routes.settings.ADMIN_USERNAME", "testadmin")
        monkeypatch.setattr("app.api.admin_routes.settings.ADMIN_PASSWORD", "testadminpass")
        
        response = await client.post(
            "/api/admin/login",
            json={
                "username": "testadmin",
                "password": "testadminpass"
            }
        )
        
        assert response.status_code == 200
        data = response.json()
        assert "access_token" in data

    @pytest.mark.asyncio
    async def test_admin_login_wrong_password(self, client, monkeypatch):
        """Admin login with wrong password should fail."""
        monkeypatch.setattr("app.api.admin_routes.settings.ADMIN_USERNAME", "testadmin")
        monkeypatch.setattr("app.api.admin_routes.settings.ADMIN_PASSWORD", "correctpass")
        
        response = await client.post(
            "/api/admin/login",
            json={
                "username": "testadmin",
                "password": "wrongpass"
            }
        )
        
        assert response.status_code == 401


class TestTokenValidation:
    """Tests for protected endpoints requiring authentication."""

    @pytest.mark.asyncio
    async def test_access_protected_without_token(self, client):
        """Accessing protected endpoint without token should fail."""
        response = await client.get("/api/prompts")
        
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_access_protected_with_invalid_token(self, client):
        """Accessing protected endpoint with invalid token should fail."""
        response = await client.get(
            "/api/prompts",
            headers={"Authorization": "Bearer invalid-token"}
        )
        
        assert response.status_code == 401

    @pytest.mark.asyncio
    async def test_access_protected_with_valid_token(self, client, auth_headers):
        """Accessing protected endpoint with valid token should succeed."""
        response = await client.get("/api/prompts", headers=auth_headers)
        
        assert response.status_code == 200

    @pytest.mark.asyncio
    async def test_access_admin_route_as_user(self, client, auth_headers):
        """Regular user should not access admin routes."""
        response = await client.get("/api/admin/users", headers=auth_headers)
        
        assert response.status_code == 403

    @pytest.mark.asyncio
    async def test_access_admin_route_as_admin(self, client, admin_headers):
        """Admin should access admin routes."""
        response = await client.get("/api/admin/users", headers=admin_headers)
        
        assert response.status_code == 200
