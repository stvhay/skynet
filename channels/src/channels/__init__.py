"""XOR-derived filesystem channels for MCP Mesh.

Public API:
    resolve_channel(mesh_dir, participants) -> dict
    ensure_channel_dir(channel_dir) -> None
"""

from __future__ import annotations

from pathlib import Path

from channels.xor import xor_uuids

BROADCAST_UUID = "00000000-0000-0000-0000-000000000000"


def ensure_channel_dir(channel_dir: Path) -> None:
    """Create a channel directory with an attachments/ subdirectory."""
    channel_dir.mkdir(parents=True, exist_ok=True)
    (channel_dir / "attachments").mkdir(exist_ok=True)


def resolve_channel(
    *,
    mesh_dir: Path,
    participants: list[str],
) -> dict:
    """Resolve the channel directory for a set of participants.

    If any participant is the broadcast UUID, returns the well-known
    .mesh/channels/all/ path. Otherwise computes XOR(sorted(participants))
    and returns that as the channel directory name.

    Creates the directory (with attachments/ subdirectory) if it doesn't exist.

    Raises ValueError if fewer than 2 participants are provided.
    """
    if len(participants) < 2:
        raise ValueError("Need at least 2 participants for a channel")

    channels_root = mesh_dir / "channels"

    if BROADCAST_UUID in participants:
        channel_dir = channels_root / "all"
    else:
        xor_id = xor_uuids(participants)
        channel_dir = channels_root / xor_id

    ensure_channel_dir(channel_dir)

    return {
        "channel_dir": str(channel_dir),
        "attachments_dir": str(channel_dir / "attachments"),
    }
