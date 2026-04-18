"""
Tests for authentication utilities: password hashing, JWT creation.

Run: cd backend && pytest tests/ -v
"""

from app.auth import hash_password, verify_password, create_access_token
from jose import jwt
from app.config import get_settings

settings = get_settings()


def test_hash_and_verify_password():
    hashed = hash_password("TestPass123!")
    assert verify_password("TestPass123!", hashed)
    assert not verify_password("WrongPass", hashed)


def test_create_access_token():
    token = create_access_token({"sub": "test-user-id"})
    payload = jwt.decode(token, settings.SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
    assert payload["sub"] == "test-user-id"
    assert "exp" in payload
