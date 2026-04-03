"""
JWT / OAuth2 Authentication.

Provides token-based authentication for the NBI REST API.
Supports:
  - OAuth2 password flow (token issuance)
  - JWT Bearer token validation
  - Role-based access control (admin, operator, viewer)
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any

from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from jose import JWTError, jwt
import bcrypt
from pydantic import BaseModel, Field

from shared.config import get_settings

logger = logging.getLogger(__name__)
settings = get_settings()

# ── Security Schemes ─────────────────────────────────────────────────────────

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/v1/auth/token")

# ── Models ───────────────────────────────────────────────────────────────────


class Token(BaseModel):
    """JWT token response."""
    access_token: str
    token_type: str = "bearer"
    expires_in: int = Field(description="Token TTL in seconds")
    user: dict[str, str] = Field(default_factory=dict)


class TokenPayload(BaseModel):
    """Decoded JWT token payload."""
    sub: str  # Subject (username)
    role: str = "viewer"
    exp: datetime | None = None


class User(BaseModel):
    """API user representation."""
    username: str
    role: str = "viewer"
    disabled: bool = False


# ── In-memory user store (replace with DB in production) ─────────────────────

_USERS_DB: dict[str, dict[str, Any]] = {
    "admin": {
        "username": "admin",
        "hashed_password": bcrypt.hashpw(b"admin", bcrypt.gensalt()).decode("utf-8"),
        "role": "admin",
        "disabled": False,
    },
    "operator": {
        "username": "operator",
        "hashed_password": bcrypt.hashpw(b"operator", bcrypt.gensalt()).decode("utf-8"),
        "role": "operator",
        "disabled": False,
    },
    "viewer": {
        "username": "viewer",
        "hashed_password": bcrypt.hashpw(b"viewer", bcrypt.gensalt()).decode("utf-8"),
        "role": "viewer",
        "disabled": False,
    },
}


# ── Token Functions ──────────────────────────────────────────────────────────


def create_access_token(data: dict[str, Any], expires_delta: timedelta | None = None) -> str:
    """Create a signed JWT access token."""
    to_encode = data.copy()
    expire = datetime.utcnow() + (expires_delta or timedelta(minutes=settings.jwt_expiry_minutes))
    to_encode.update({"exp": expire})

    return jwt.encode(
        to_encode,
        settings.jwt_secret_key.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plaintext password against its hash."""
    return bcrypt.checkpw(plain_password.encode("utf-8"), hashed_password.encode("utf-8"))


def authenticate_user(username: str, password: str) -> User | None:
    """Authenticate a user by username and password."""
    user_data = _USERS_DB.get(username)
    if not user_data:
        return None
    if not verify_password(password, user_data["hashed_password"]):
        return None
    return User(**{k: v for k, v in user_data.items() if k != "hashed_password"})


async def get_current_user(token: str = Depends(oauth2_scheme)) -> User:
    """Decode and validate the JWT token, returning the current user."""
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Invalid or expired authentication token",
        headers={"WWW-Authenticate": "Bearer"},
    )

    try:
        payload = jwt.decode(
            token,
            settings.jwt_secret_key.get_secret_value(),
            algorithms=[settings.jwt_algorithm],
        )
        username: str | None = payload.get("sub")
        if username is None:
            raise credentials_exception

        user_data = _USERS_DB.get(username)
        if not user_data:
            raise credentials_exception

        user = User(**{k: v for k, v in user_data.items() if k != "hashed_password"})
        if user.disabled:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is disabled",
            )
        return user

    except JWTError as exc:
        raise credentials_exception from exc


def require_role(*roles: str):
    """Dependency factory: require the current user to have one of the specified roles."""

    async def _check_role(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Role '{user.role}' insufficient. Required: {roles}",
            )
        return user

    return _check_role
