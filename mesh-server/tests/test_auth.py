"""Tests for the auth module."""

from mesh_server.auth import generate_token, hash_token, verify_token


def test_inv3_token_roundtrip():  # Tests INV-3
    """A generated token verifies against its own hash."""
    raw_token = generate_token()
    token_hash = hash_token(raw_token)
    assert verify_token(raw_token, token_hash) is True


def test_inv4_wrong_token_rejected():  # Tests INV-4
    """A wrong token does not verify."""
    raw_token = generate_token()
    token_hash = hash_token(raw_token)
    assert verify_token("wrong-token-value", token_hash) is False


def test_inv5_hash_includes_scheme():  # Tests INV-5
    """Hash dict includes scheme field for upgrade path."""
    raw_token = generate_token()
    token_hash = hash_token(raw_token)
    assert token_hash["scheme"] == "scrypt"
    assert "salt" in token_hash
    assert "hash" in token_hash
    assert token_hash["n"] == 16384
    assert token_hash["r"] == 8
    assert token_hash["p"] == 1


def test_generate_token_is_unique():
    """Each generated token is unique."""
    tokens = {generate_token() for _ in range(10)}
    assert len(tokens) == 10


def test_generate_token_length():
    """Token is 64 hex chars (32 bytes)."""
    token = generate_token()
    assert len(token) == 64
    int(token, 16)  # Should be valid hex
