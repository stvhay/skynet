"""Tests for channel directory resolution and management."""

import pytest

from channels import resolve_channel, ensure_channel_dir
from channels.xor import xor_uuids

BROADCAST_UUID = "00000000-0000-0000-0000-000000000000"


def test_inv4_broadcast_resolves_to_all(tmp_path):  # Tests CH-INV-4
    """Broadcast UUID resolves to .mesh/channels/all/."""
    mesh_dir = tmp_path / ".mesh"
    result = resolve_channel(
        mesh_dir=mesh_dir,
        participants=["agent-a", BROADCAST_UUID],
    )
    assert result["channel_dir"] == str(mesh_dir / "channels" / "all")
    assert result["attachments_dir"] == str(
        mesh_dir / "channels" / "all" / "attachments"
    )


def test_inv5_ensure_creates_directory(tmp_path):  # Tests CH-INV-5
    """ensure_channel_dir creates channel dir with attachments/ subdirectory."""
    channel_dir = tmp_path / "channels" / "test-channel"
    ensure_channel_dir(channel_dir)
    assert channel_dir.is_dir()
    assert (channel_dir / "attachments").is_dir()


def test_inv6_resolve_returns_paths(tmp_path):  # Tests CH-INV-6
    """resolve_channel returns channel_dir and attachments_dir."""
    mesh_dir = tmp_path / ".mesh"
    a = "a3f28b4c-1234-5678-9abc-def012345678"
    b = "b7c12d9f-abcd-ef01-2345-678901234567"
    result = resolve_channel(mesh_dir=mesh_dir, participants=[a, b])
    expected_xor = xor_uuids([a, b])
    assert result["channel_dir"] == str(mesh_dir / "channels" / expected_xor)
    assert result["attachments_dir"] == str(
        mesh_dir / "channels" / expected_xor / "attachments"
    )


def test_inv6_resolve_creates_directory(tmp_path):  # Tests CH-INV-6
    """resolve_channel lazily creates the channel directory."""
    mesh_dir = tmp_path / ".mesh"
    a = "a3f28b4c-1234-5678-9abc-def012345678"
    b = "b7c12d9f-abcd-ef01-2345-678901234567"
    resolve_channel(mesh_dir=mesh_dir, participants=[a, b])
    expected_xor = xor_uuids([a, b])
    assert (mesh_dir / "channels" / expected_xor).is_dir()
    assert (mesh_dir / "channels" / expected_xor / "attachments").is_dir()


def test_fail1_resolve_rejects_single_participant(tmp_path):  # Tests CH-FAIL-1
    """resolve_channel with fewer than 2 participants raises ValueError."""
    mesh_dir = tmp_path / ".mesh"
    with pytest.raises(ValueError, match="at least 2 participants"):
        resolve_channel(mesh_dir=mesh_dir, participants=["only-one"])


def test_resolve_idempotent(tmp_path):
    """Calling resolve_channel twice returns the same result, no error."""
    mesh_dir = tmp_path / ".mesh"
    a = "a3f28b4c-1234-5678-9abc-def012345678"
    b = "b7c12d9f-abcd-ef01-2345-678901234567"
    r1 = resolve_channel(mesh_dir=mesh_dir, participants=[a, b])
    r2 = resolve_channel(mesh_dir=mesh_dir, participants=[a, b])
    assert r1 == r2
