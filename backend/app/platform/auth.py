"""Authentication, sessions, CSRF, API keys and request-scoped tenant context.

* Browser sessions: random 256-bit token in an httpOnly, SameSite=Lax cookie (Secure in production); only its
  SHA-256 is stored. Absolute TTL plus idle timeout; revocable.
* CSRF: signed double-submit token. Unsafe requests authenticated by cookie must send X-CSRF-Token equal to the
  zpy_csrf cookie, and the token must be an HMAC of the session id (so it cannot be forged or reused).
* API keys: `zpy_live_<random>`, stored hashed, merchant-bound, scoped, revocable, optional expiry.
* The tenant is always the session's active merchant (membership-checked) or the API key's merchant. A merchant
  id in a request body or query string is never trusted.
"""
import hmac
import secrets
from dataclasses import dataclass, field
from datetime import timedelta

from fastapi import Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import new_session
from app.platform import audit, clock
from app.platform.models import ApiKey, AuthSession, Membership, Merchant, User
from app.platform.rbac import permissions_for
from app.platform.ratelimit import hit
from app.platform.security import crypto

SESSION_COOKIE = "zpy_session"
CSRF_COOKIE = "zpy_csrf"
SAFE_METHODS = {"GET", "HEAD", "OPTIONS"}


@dataclass
class Principal:
    type: str  # user | api_key
    merchant_id: str
    permissions: frozenset[str]
    user_id: str | None = None
    email: str | None = None
    name: str | None = None
    role: str | None = None
    session_id: str | None = None
    api_key_id: str | None = None
    request_id: str | None = None
    ip: str | None = None
    merchant_is_demo: bool = False
    memberships: list[dict] = field(default_factory=list)

    @property
    def actor(self) -> audit.Actor:
        if self.type == "user":
            return audit.Actor("user", self.user_id, self.email, self.request_id, self.ip)
        return audit.Actor("api_key", self.api_key_id, "API key", self.request_id, self.ip)

    def can(self, perm: str) -> bool:
        return perm in self.permissions


def csrf_token_for(session_id: str) -> str:
    return hmac.new(get_settings().secret_key.encode(), f"csrf:{session_id}".encode(), "sha256").hexdigest()


def client_ip(request: Request) -> str:
    # Trust X-Forwarded-For only from the configured proxy chain in production; first hop otherwise.
    fwd = request.headers.get("x-forwarded-for")
    return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "unknown"))[:64]


def create_session(db: Session, user: User, merchant_id: str, request: Request) -> tuple[str, AuthSession]:
    token = secrets.token_urlsafe(32)
    s = get_settings()
    row = AuthSession(token_hash=crypto.token_hash(token), user_id=user.id, active_merchant_id=merchant_id,
                      ip=client_ip(request), user_agent=(request.headers.get("user-agent") or "")[:200],
                      expires_at=clock.now() + timedelta(hours=s.session_ttl_hours))
    db.add(row)
    db.flush()
    return token, row


def set_session_cookies(response, token: str, session_id: str) -> None:
    s = get_settings()
    max_age = s.session_ttl_hours * 3600
    response.set_cookie(SESSION_COOKIE, token, max_age=max_age, httponly=True, secure=s.session_cookie_secure,
                        samesite="lax", path="/")
    response.set_cookie(CSRF_COOKIE, csrf_token_for(session_id), max_age=max_age, httponly=False,
                        secure=s.session_cookie_secure, samesite="lax", path="/")


def clear_session_cookies(response) -> None:
    response.delete_cookie(SESSION_COOKIE, path="/")
    response.delete_cookie(CSRF_COOKIE, path="/")


def memberships_of(db: Session, user_id: str) -> list[dict]:
    rows = db.execute(select(Membership, Merchant).join(Merchant, Merchant.id == Membership.merchant_id)
                      .where(Membership.user_id == user_id, Merchant.status != "suspended")
                      .order_by(Merchant.brand_name)).all()
    return [{"merchantId": m.id, "code": m.code, "brandName": m.brand_name, "role": ms.role, "isDemo": m.is_demo}
            for ms, m in rows]


def _api_key_principal(db: Session, raw: str, request: Request) -> Principal:
    key = db.scalars(select(ApiKey).where(ApiKey.key_hash == crypto.token_hash(raw))).first()
    now = clock.now()
    if key is None or key.revoked_at is not None or (key.expires_at and clock.as_utc(key.expires_at) < now):
        raise HTTPException(401, {"code": "INVALID_API_KEY", "message": "API key is invalid or revoked"})
    if key.last_used_at is None or now - clock.as_utc(key.last_used_at) > timedelta(minutes=5):
        key.last_used_at = now
        db.commit()
    merchant = db.get(Merchant, key.merchant_id)
    return Principal("api_key", key.merchant_id, frozenset(key.scopes or []), api_key_id=key.id,
                     request_id=getattr(request.state, "request_id", None), ip=client_ip(request),
                     merchant_is_demo=merchant.is_demo if merchant else False)


def _session_principal(db: Session, token: str, request: Request) -> Principal:
    s = get_settings()
    row = db.scalars(select(AuthSession).where(AuthSession.token_hash == crypto.token_hash(token))).first()
    now = clock.now()
    if row is None or row.revoked_at is not None or clock.as_utc(row.expires_at) < now \
            or now - clock.as_utc(row.last_seen_at) > timedelta(minutes=s.session_idle_minutes):
        raise HTTPException(401, {"code": "SESSION_EXPIRED", "message": "Please sign in again"})
    user = db.get(User, row.user_id)
    if user is None or not user.is_active:
        raise HTTPException(401, {"code": "SESSION_EXPIRED", "message": "Please sign in again"})
    membership = db.get(Membership, (row.active_merchant_id, row.user_id))
    merchant = db.get(Merchant, row.active_merchant_id)
    if membership is None or merchant is None or merchant.status == "suspended":
        raise HTTPException(403, {"code": "NO_ACCESS", "message": "You no longer have access to this workspace"})
    if request.method not in SAFE_METHODS:
        header = request.headers.get("x-csrf-token", "")
        cookie = request.cookies.get(CSRF_COOKIE, "")
        expected = csrf_token_for(row.id)
        if not (header and hmac.compare_digest(header, cookie) and hmac.compare_digest(header, expected)):
            raise HTTPException(403, {"code": "CSRF_FAILED", "message": "Missing or invalid CSRF token"})
    if now - clock.as_utc(row.last_seen_at) > timedelta(seconds=60):
        row.last_seen_at = now
        db.commit()
    return Principal("user", merchant.id, permissions_for(membership.role), user_id=user.id, email=user.email,
                     name=user.name, role=membership.role, session_id=row.id,
                     request_id=getattr(request.state, "request_id", None), ip=client_ip(request),
                     merchant_is_demo=merchant.is_demo)


async def get_principal(request: Request) -> Principal:
    auth_header = request.headers.get("authorization", "")
    db = new_session(system=True)  # identity lookup precedes tenant selection
    try:
        if auth_header.lower().startswith("bearer zpy_"):
            principal = _api_key_principal(db, auth_header[7:].strip(), request)
        else:
            token = request.cookies.get(SESSION_COOKIE)
            if not token:
                raise HTTPException(401, {"code": "NOT_AUTHENTICATED", "message": "Sign in required"})
            principal = _session_principal(db, token, request)
    finally:
        db.close()
    allowed, retry = await hit(f"p:{principal.session_id or principal.api_key_id}", get_settings().rate_limit_per_minute)
    if not allowed:
        raise HTTPException(429, {"code": "RATE_LIMITED", "message": "Too many requests"}, headers={"Retry-After": str(retry)})
    request.state.principal = principal
    return principal


def tenant_db(principal: Principal = Depends(get_principal)):
    db = new_session(merchant_id=principal.merchant_id)
    try:
        yield db
    finally:
        db.close()


def require(*perms: str):
    async def dep(principal: Principal = Depends(get_principal)) -> Principal:
        missing = [p for p in perms if p not in principal.permissions]
        if missing:
            raise HTTPException(403, {"code": "FORBIDDEN", "message": f"Missing permission: {', '.join(missing)}"})
        return principal
    return dep
