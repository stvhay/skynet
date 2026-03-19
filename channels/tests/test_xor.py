"""Tests for XOR channel computation."""

import uuid as uuid_mod

from channels.xor import xor_uuids


def test_inv1_xor_symmetric():  # Tests CH-INV-1
    """XOR(A, B) == XOR(B, A)."""
    a = str(uuid_mod.uuid4())
    b = str(uuid_mod.uuid4())
    assert xor_uuids([a, b]) == xor_uuids([b, a])


def test_inv2_xor_associative():  # Tests CH-INV-2
    """XOR(A, B, C) == XOR(sorted([A, B, C])) regardless of input order."""
    a = str(uuid_mod.uuid4())
    b = str(uuid_mod.uuid4())
    c = str(uuid_mod.uuid4())
    assert xor_uuids([a, b, c]) == xor_uuids([c, a, b])
    assert xor_uuids([a, b, c]) == xor_uuids([b, c, a])


def test_inv3_xor_produces_valid_uuid():  # Tests CH-INV-3
    """XOR result is a valid UUID string (8-4-4-4-12 hex format)."""
    a = "a3f28b4c-1234-5678-9abc-def012345678"
    b = "b7c12d9f-abcd-ef01-2345-678901234567"
    result = xor_uuids([a, b])
    parsed = uuid_mod.UUID(result)
    assert str(parsed) == result


def test_xor_deterministic():
    """Same inputs always produce the same output."""
    a = "a3f28b4c-1234-5678-9abc-def012345678"
    b = "b7c12d9f-abcd-ef01-2345-678901234567"
    r1 = xor_uuids([a, b])
    r2 = xor_uuids([a, b])
    assert r1 == r2


def test_xor_known_values():
    """XOR of known UUIDs produces the expected result."""
    a = "00000000-0000-0000-0000-000000000001"
    b = "00000000-0000-0000-0000-000000000002"
    result = xor_uuids([a, b])
    assert result == "00000000-0000-0000-0000-000000000003"
