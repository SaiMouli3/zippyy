"""Password hashing with scrypt (memory-hard, stdlib). Format: scrypt$n$r$p$salt$hash (base64)."""
import base64
import hashlib
import hmac
import os

_N, _R, _P = 2**15, 8, 1
_MAXMEM = 64 * 1024 * 1024


def hash_password(password: str) -> str:
    if len(password) < 12:
        raise ValueError("password must be at least 12 characters")
    salt = os.urandom(16)
    dk = hashlib.scrypt(password.encode(), salt=salt, n=_N, r=_R, p=_P, maxmem=_MAXMEM, dklen=32)
    return "$".join(["scrypt", str(_N), str(_R), str(_P), base64.b64encode(salt).decode(), base64.b64encode(dk).decode()])


def verify_password(password: str, encoded: str | None) -> bool:
    if not encoded:
        # Burn comparable time so unknown users are not distinguishable by latency.
        hashlib.scrypt(b"x", salt=b"0" * 16, n=_N, r=_R, p=_P, maxmem=_MAXMEM, dklen=32)
        return False
    try:
        algo, n, r, p, salt, expected = encoded.split("$")
        if algo != "scrypt":
            return False
        dk = hashlib.scrypt(
            password.encode(), salt=base64.b64decode(salt), n=int(n), r=int(r), p=int(p), maxmem=_MAXMEM, dklen=32
        )
    except (ValueError, TypeError):
        return False
    return hmac.compare_digest(dk, base64.b64decode(expected))
