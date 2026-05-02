"""
Auth router — /auth/* and /admin/* endpoints.
"""

import hashlib
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr, Field

from deps import (
    AUTH_AVAILABLE, check_rate_limit,
    create_access_token, create_refresh_token, hash_password, verify_password,
    require_current_user, require_admin,
    API_PASSWORD,
)
from db.models import (
    create_user, get_user_by_email, get_user_by_id, update_user_last_login,
    get_augur_profile,
    validate_refresh_token, delete_refresh_token, set_user_admin,
)
from core.augur_weights import describe_augur

router = APIRouter(tags=["auth"])


# ── Request Models ─────────────────────────────────────────────────────────────

class AuthRequest(BaseModel):
    password: str

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    augur_name: str = Field(..., min_length=2, max_length=24)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class RefreshRequest(BaseModel):
    refresh_token: str


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.post("/auth")
def authenticate(req: AuthRequest):
    """Legacy password-only auth (returns API token hash)."""
    if req.password == API_PASSWORD:
        token = hashlib.sha256(API_PASSWORD.encode()).hexdigest()
        return {"authenticated": True, "token": token}
    raise HTTPException(status_code=401, detail="Wrong password")


@router.post("/auth/register")
def auth_register(req: RegisterRequest):
    """Register a new Augur account."""
    if not AUTH_AVAILABLE:
        raise HTTPException(status_code=503, detail="Auth not available (pyjwt/bcrypt not installed)")
    if not check_rate_limit("register", max_calls=5, window_seconds=3600):
        raise HTTPException(status_code=429, detail="Registration rate limit exceeded")

    pw_hash = hash_password(req.password)
    try:
        user_id = create_user(req.email, pw_hash, req.augur_name)
    except Exception as e:
        if "UNIQUE" in str(e).upper():
            raise HTTPException(status_code=409, detail="Email or Augur name already taken")
        raise HTTPException(status_code=500, detail=str(e))

    access_token = create_access_token(user_id, req.email, req.augur_name)
    refresh_token = create_refresh_token(user_id)
    update_user_last_login(user_id)

    return {
        "user_id": user_id,
        "augur_name": req.augur_name,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "needs_augur_profile": True,
    }


@router.post("/auth/login")
def auth_login(req: LoginRequest):
    """Login with email + password. Returns JWT tokens."""
    if not AUTH_AVAILABLE:
        raise HTTPException(status_code=503, detail="Auth not available")
    if not check_rate_limit(f"login:{req.email}", max_calls=10, window_seconds=300):
        raise HTTPException(status_code=429, detail="Too many login attempts")

    user = get_user_by_email(req.email)
    if not user or not verify_password(req.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Invalid email or password")

    _is_admin = bool(user.get("is_admin"))
    access_token = create_access_token(user["id"], user["email"], user["augur_name"], _is_admin)
    refresh_token = create_refresh_token(user["id"])
    update_user_last_login(user["id"])
    profile = get_augur_profile(user["id"])

    return {
        "user_id": user["id"],
        "augur_name": user["augur_name"],
        "is_admin": _is_admin,
        "access_token": access_token,
        "refresh_token": refresh_token,
        "token_type": "bearer",
        "needs_augur_profile": profile is None,
    }


@router.post("/auth/refresh")
def auth_refresh(req: RefreshRequest):
    """Exchange a refresh token for a new access token."""
    if not AUTH_AVAILABLE:
        raise HTTPException(status_code=503, detail="Auth not available")

    token_hash = hashlib.sha256(req.refresh_token.encode()).hexdigest()
    record = validate_refresh_token(token_hash)
    if not record:
        raise HTTPException(status_code=401, detail="Invalid or expired refresh token")

    user = get_user_by_id(record["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="User not found")

    delete_refresh_token(token_hash)
    access_token = create_access_token(user["id"], user["email"], user["augur_name"], bool(user.get("is_admin")))
    new_refresh = create_refresh_token(user["id"])

    return {
        "access_token": access_token,
        "refresh_token": new_refresh,
        "token_type": "bearer",
    }


@router.get("/auth/me")
async def auth_me(user: dict = Depends(require_current_user)):
    """Get current user profile + Augur attributes."""
    profile = get_augur_profile(user["id"])
    result = {
        "user_id": user["id"],
        "email": user["email"],
        "augur_name": user["augur_name"],
        "is_admin": bool(user.get("is_admin")),
        "created_at": user["created_at"],
        "last_login": user["last_login"],
        "has_augur_profile": profile is not None,
    }
    if profile:
        desc = describe_augur(profile)
        result["augur"] = {
            "prudentia": profile["prudentia"],
            "audacia": profile["audacia"],
            "sapientia": profile["sapientia"],
            "fortuna": profile["fortuna"],
            "prospectus": profile["prospectus"],
            "liquiditas": profile["liquiditas"],
            "avatar_seed": profile.get("avatar_seed"),
            "title": profile.get("title", "Novice Augur"),
            "xp": profile.get("xp", 0),
            "level": profile.get("level", 1),
            "dominant_trait": desc["dominant_trait"],
            "style": desc["style"],
        }
    return result


@router.post("/auth/logout")
async def auth_logout(
    req: RefreshRequest,
    user: dict = Depends(require_current_user),
):
    """Invalidate a refresh token."""
    token_hash = hashlib.sha256(req.refresh_token.encode()).hexdigest()
    delete_refresh_token(token_hash)
    return {"status": "logged_out"}


@router.post("/admin/promote/{user_id}")
async def promote_user(user_id: int, admin: dict = Depends(require_admin)):
    """Grant admin privileges to a user."""
    set_user_admin(user_id, True)
    return {"status": "promoted", "user_id": user_id}
