"""
Shared FastAPI dependencies — auth, rate limiting, JWT helpers.
Imported by main.py and all routers so they don't need to duplicate this.
"""

import os
import time
import hashlib
import secrets
import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException, Header, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

try:
    import jwt as pyjwt
    import bcrypt
    AUTH_AVAILABLE = True
except ImportError:
    AUTH_AVAILABLE = False
    logging.getLogger(__name__).warning("pyjwt/bcrypt not installed — auth endpoints disabled")

from db.models import get_user_by_id, save_refresh_token

# ── Constants ─────────────────────────────────────────────────────────────────

API_PASSWORD = os.environ.get("CYBERSCREENER_PASSWORD", "cybershield2026")
JWT_SECRET = os.environ.get("JWT_SECRET", secrets.token_hex(32))
JWT_ALGORITHM = "HS256"
JWT_ACCESS_EXPIRE_MINUTES = 15
JWT_REFRESH_EXPIRE_DAYS = 30

_bearer_scheme = HTTPBearer(auto_error=False)

# ── Rate Limiter ───────────────────────────────────────────────────────────────

_rate_limits: dict = {}

def check_rate_limit(key: str, max_calls: int = 10, window_seconds: int = 60) -> bool:
    """Returns True if under limit (OK to proceed), False if rate limited."""
    now = time.time()
    cutoff = now - window_seconds
    times = [t for t in _rate_limits.get(key, []) if t > cutoff]
    if len(times) >= max_calls:
        _rate_limits[key] = times
        return False
    times.append(now)
    _rate_limits[key] = times
    return True

# ── Token Helpers ──────────────────────────────────────────────────────────────

def create_access_token(user_id: int, email: str, augur_name: str, is_admin: bool = False) -> str:
    payload = {
        "user_id": user_id,
        "email": email,
        "augur_name": augur_name,
        "is_admin": is_admin,
        "exp": datetime.utcnow() + timedelta(minutes=JWT_ACCESS_EXPIRE_MINUTES),
        "iat": datetime.utcnow(),
        "type": "access",
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def create_refresh_token(user_id: int) -> str:
    raw_token = secrets.token_urlsafe(48)
    token_hash = hashlib.sha256(raw_token.encode()).hexdigest()
    expires_at = (datetime.utcnow() + timedelta(days=JWT_REFRESH_EXPIRE_DAYS)).strftime("%Y-%m-%d %H:%M:%S")
    save_refresh_token(user_id, token_hash, expires_at)
    return raw_token


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))

# ── Auth Dependencies ──────────────────────────────────────────────────────────

async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> Optional[dict]:
    """Returns user dict if valid JWT, None if no token. Raises 401 if token is invalid."""
    if not AUTH_AVAILABLE or credentials is None:
        return None
    try:
        payload = pyjwt.decode(credentials.credentials, JWT_SECRET, algorithms=[JWT_ALGORITHM])
        if payload.get("type") != "access":
            raise HTTPException(status_code=401, detail="Invalid token type")
        user = get_user_by_id(payload["user_id"])
        if not user:
            raise HTTPException(status_code=401, detail="User not found")
        return user
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(status_code=401, detail="Token expired")
    except pyjwt.InvalidTokenError:
        raise HTTPException(status_code=401, detail="Invalid token")


async def require_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> dict:
    user = await get_current_user(credentials)
    if user is None:
        raise HTTPException(status_code=401, detail="Authentication required")
    return user


async def require_admin(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
    x_api_key: Optional[str] = Header(None),
) -> dict:
    if credentials:
        user = await require_current_user(credentials)
        if user.get("is_admin"):
            return user
        raise HTTPException(status_code=403, detail="Admin access required")
    if x_api_key:
        expected = hashlib.sha256(API_PASSWORD.encode()).hexdigest()
        if x_api_key == expected:
            return {"id": 0, "augur_name": "admin", "is_admin": True, "email": "admin@local"}
    raise HTTPException(status_code=403, detail="Admin access required. Sign in with an admin account.")
