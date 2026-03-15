"""Token generation and scrypt-based verification."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets


def generate_token() -> str:
    """Generate a 256-bit random bearer token as hex string."""
    return secrets.token_hex(32)


def hash_token(raw_token: str) -> dict:
    """Hash a token using scrypt. Returns a dict with scheme + parameters."""
    salt = os.urandom(16)
    h = hashlib.scrypt(
        raw_token.encode(),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )
    return {
        "scheme": "scrypt",
        "salt": salt.hex(),
        "hash": h.hex(),
        "n": 16384,
        "r": 8,
        "p": 1,
    }


def verify_token(raw_token: str, stored: dict) -> bool:
    """Verify a raw token against a stored scrypt hash."""
    if stored.get("scheme") != "scrypt":
        return False
    h = hashlib.scrypt(
        raw_token.encode(),
        salt=bytes.fromhex(stored["salt"]),
        n=stored["n"],
        r=stored["r"],
        p=stored["p"],
        dklen=32,
    )
    return hmac.compare_digest(h.hex(), stored["hash"])
