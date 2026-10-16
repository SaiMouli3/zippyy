"""Identifiers: time-ordered UUIDs (v7 layout) for primary keys, short human codes for operators."""
import os
import secrets
import time
import uuid


def new_id() -> str:
    """UUIDv7: 48-bit unix-ms timestamp + random. Sorts by creation time, indexes well in B-trees."""
    ms = int(time.time() * 1000)
    rand = int.from_bytes(os.urandom(10), "big")
    value = (ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76  # version 7
    value |= (rand >> 68 & 0xFFF) << 64
    value |= 0b10 << 62  # RFC 4122 variant
    value |= rand & ((1 << 62) - 1)
    return str(uuid.UUID(int=value))


def short_code(prefix: str) -> str:
    """Operator-facing reference, e.g. NDR-7K3QX9. Uniqueness is enforced by a DB constraint; callers retry."""
    alphabet = "23456789ABCDEFGHJKLMNPQRSTUVWXYZ"  # no 0/O/1/I confusion
    return f"{prefix}-" + "".join(secrets.choice(alphabet) for _ in range(6))


def correlation_id() -> str:
    return "cor_" + secrets.token_hex(8)
