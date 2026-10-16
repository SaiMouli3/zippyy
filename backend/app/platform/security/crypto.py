"""Application-level protection for PII.

* Phone numbers, emails and address lines are encrypted with AES-256-GCM (random 96-bit nonce per value).
* Phone lookups use a keyed HMAC so the plaintext never needs to be indexed.
* Masking helpers produce the only representation shown by default in the UI.
"""
import base64
import hashlib
import hmac
import os
import re
from functools import lru_cache

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.config import get_settings

_VERSION = b"v1"


@lru_cache
def _aead() -> AESGCM:
    key = base64.b64decode(get_settings().pii_encryption_key)
    if len(key) != 32:
        raise RuntimeError("PII_ENCRYPTION_KEY must be base64 of exactly 32 bytes")
    return AESGCM(key)


def encrypt(plaintext: str | None, context: str = "") -> str | None:
    """Returns 'v1:<b64(nonce|ciphertext)>'. `context` is bound as associated data (e.g. the column name)."""
    if plaintext is None:
        return None
    nonce = os.urandom(12)
    ct = _aead().encrypt(nonce, plaintext.encode(), context.encode())
    return _VERSION.decode() + ":" + base64.b64encode(nonce + ct).decode()


def decrypt(token: str | None, context: str = "") -> str | None:
    if token is None:
        return None
    version, _, data = token.partition(":")
    if version != _VERSION.decode():
        raise ValueError("unknown PII ciphertext version")
    raw = base64.b64decode(data)
    return _aead().decrypt(raw[:12], raw[12:], context.encode()).decode()


def normalize_phone(phone: str) -> str:
    """E.164 for Indian numbers: '98765 43210' / '09876543210' / '+919876543210' -> '+919876543210'."""
    digits = re.sub(r"\D", "", phone or "")
    if len(digits) == 10:
        digits = "91" + digits
    elif len(digits) == 11 and digits.startswith("0"):
        digits = "91" + digits[1:]
    if not 10 <= len(digits) <= 15:
        raise ValueError("invalid phone number")
    return "+" + digits


def phone_hash(phone_e164: str) -> str:
    key = get_settings().pii_hash_key.encode()
    return hmac.new(key, phone_e164.encode(), hashlib.sha256).hexdigest()


def mask_phone(last4: str | None) -> str:
    return f"+91 XXXXX X{last4[-4:]}" if last4 else "—"


def mask_text(value: str | None, keep: int = 3) -> str:
    if not value:
        return "—"
    return value[:keep] + "•" * max(3, min(12, len(value) - keep))


def sign(payload: bytes, secret: str) -> str:
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def verify_signature(payload: bytes, secret: str, signature: str | None, prefix: str = "") -> bool:
    if not signature or not secret:
        return False
    if prefix and signature.startswith(prefix):
        signature = signature[len(prefix):]
    return hmac.compare_digest(sign(payload, secret), signature)


def token_hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()
