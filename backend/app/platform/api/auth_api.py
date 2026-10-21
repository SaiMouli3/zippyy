from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.config import get_settings
from app.db import new_session
from app.platform import audit, clock
from app.platform.auth import (Principal, clear_session_cookies, client_ip, create_session, get_principal,
                               memberships_of, set_session_cookies)
from app.platform.models import AuthSession, Membership, User
from app.platform.ratelimit import hit
from app.platform.security.passwords import verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


class LoginIn(BaseModel):
    email: str = Field(min_length=3, max_length=254)
    password: str = Field(min_length=1, max_length=200)


class SwitchIn(BaseModel):
    merchantId: str = Field(min_length=10, max_length=36)


def _me(p: Principal, memberships: list[dict]) -> dict:
    return {"user": {"id": p.user_id, "email": p.email, "name": p.name},
            "merchantId": p.merchant_id, "role": p.role, "permissions": sorted(p.permissions),
            "memberships": memberships, "isDemo": p.merchant_is_demo}


@router.post("/login")
async def login(body: LoginIn, request: Request, response: Response):
    s = get_settings()
    ip = client_ip(request)
    email = body.email.strip().lower()
    for key in (f"login-ip:{ip}", f"login-email:{email}"):
        allowed, retry = await hit(key, s.login_rate_limit_per_minute)
        if not allowed:
            raise HTTPException(429, {"code": "RATE_LIMITED", "message": "Too many sign-in attempts. Try again shortly."},
                                headers={"Retry-After": str(retry)})
    db = new_session(system=True)
    try:
        user = db.scalars(select(User).where(User.email == email)).first()
        now = clock.now()
        if user is not None and user.locked_until and clock.as_utc(user.locked_until) > now:
            raise HTTPException(423, {"code": "LOCKED", "message": "Account temporarily locked after failed attempts"})
        ok = verify_password(body.password, user.password_hash if user else None)
        if not ok or user is None or not user.is_active:
            if user is not None:
                user.failed_login_count += 1
                if user.failed_login_count >= s.login_max_failures:
                    from datetime import timedelta
                    user.locked_until = now + timedelta(minutes=s.login_lockout_minutes)
                    user.failed_login_count = 0
                audit.record(db, audit.Actor("user", user.id, email, None, ip), None, "user", user.id, "auth.login_failed")
                db.commit()
            raise HTTPException(401, {"code": "INVALID_CREDENTIALS", "message": "Email or password is incorrect"})
        memberships = memberships_of(db, user.id)
        if not memberships:
            raise HTTPException(403, {"code": "NO_WORKSPACE", "message": "Your account has no active workspace"})
        user.failed_login_count = 0
        user.locked_until = None
        user.last_login_at = now
        token, session = create_session(db, user, memberships[0]["merchantId"], request)
        audit.record(db, audit.Actor("user", user.id, email, getattr(request.state, "request_id", None), ip),
                     memberships[0]["merchantId"], "user", user.id, "auth.login")
        db.commit()
        set_session_cookies(response, token, session.id)
        role = memberships[0]["role"]
        from app.platform.rbac import permissions_for
        return {"user": {"id": user.id, "email": user.email, "name": user.name},
                "merchantId": memberships[0]["merchantId"], "role": role,
                "permissions": sorted(permissions_for(role)), "memberships": memberships,
                "isDemo": memberships[0]["isDemo"]}
    finally:
        db.close()


@router.post("/logout")
def logout(response: Response, principal: Principal = Depends(get_principal)):
    db = new_session(system=True)
    try:
        row = db.get(AuthSession, principal.session_id) if principal.session_id else None
        if row is not None:
            row.revoked_at = clock.now()
            audit.record(db, principal.actor, principal.merchant_id, "user", principal.user_id, "auth.logout")
            db.commit()
    finally:
        db.close()
    clear_session_cookies(response)
    return {"ok": True}


@router.get("/me")
def me(principal: Principal = Depends(get_principal)):
    if principal.type != "user":
        return {"apiKey": principal.api_key_id, "merchantId": principal.merchant_id, "permissions": sorted(principal.permissions)}
    db = new_session(system=True)
    try:
        return _me(principal, memberships_of(db, principal.user_id))
    finally:
        db.close()


@router.post("/switch-merchant")
def switch_merchant(body: SwitchIn, principal: Principal = Depends(get_principal)):
    if principal.type != "user":
        raise HTTPException(403, {"code": "FORBIDDEN", "message": "API keys are bound to one merchant"})
    db = new_session(system=True)
    try:
        if db.get(Membership, (body.merchantId, principal.user_id)) is None:
            raise HTTPException(403, {"code": "NO_ACCESS", "message": "You are not a member of that workspace"})
        row = db.get(AuthSession, principal.session_id)
        row.active_merchant_id = body.merchantId
        audit.record(db, principal.actor, body.merchantId, "user", principal.user_id, "auth.workspace_switched",
                     before={"merchantId": principal.merchant_id}, after={"merchantId": body.merchantId})
        db.commit()
        return {"ok": True, "merchantId": body.merchantId}
    finally:
        db.close()
