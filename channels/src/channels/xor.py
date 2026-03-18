"""XOR computation on UUIDs for channel resolution."""

from __future__ import annotations

import uuid as uuid_mod


def xor_uuids(uuids: list[str]) -> str:
    """Compute XOR of sorted UUIDs, return as UUID string.

    Each UUID is parsed as a 128-bit integer. The sorted list is
    XORed left-to-right. The result is formatted as a standard
    UUID string (8-4-4-4-12 hex).
    """
    if not uuids:
        raise ValueError("Need at least one UUID")

    sorted_uuids = sorted(uuids)
    result = 0
    for u in sorted_uuids:
        result ^= uuid_mod.UUID(u).int

    return str(uuid_mod.UUID(int=result))
