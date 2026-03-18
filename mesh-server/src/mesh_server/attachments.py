"""Attachment validation and path resolution."""

from __future__ import annotations

from pathlib import Path, PurePosixPath

from channels import resolve_channel


def validate_attachments(attachments: list | None) -> str | None:
    """Validate attachment descriptors. Returns error string or None if valid."""
    if attachments is None:
        return None

    if not isinstance(attachments, list):
        return "attachments must be a list"

    for att in attachments:
        if not isinstance(att, dict):
            return "each attachment must be a dict"
        if "type" not in att:
            return "attachment missing 'type' field"
        if "path" in att:
            path = att["path"]
            if ".." in PurePosixPath(path).parts:
                return f"path traversal not allowed: {path}"

    return None


def normalize_attachments(attachments: list | None) -> list | None:
    """Normalize attachments: empty list becomes None."""
    if not attachments:
        return None
    return attachments


def resolve_attachment_paths(
    attachments: list[dict] | None,
    *,
    from_uuid: str,
    to_uuid: str,
    mesh_dir: Path,
) -> list[dict] | None:
    """Resolve relative attachment paths to absolute paths.

    For file-ref attachments (those with a 'path' field), resolves
    the path relative to the channel's attachments/ directory.
    Inline attachments (those with 'data' field) are returned as-is.
    """
    if not attachments:
        return attachments

    channel = resolve_channel(
        mesh_dir=mesh_dir,
        participants=sorted([from_uuid, to_uuid]),
    )
    attachments_dir = Path(channel["attachments_dir"])

    resolved = []
    for att in attachments:
        if "path" in att:
            resolved.append({
                **att,
                "path": str(attachments_dir / att["path"]),
            })
        else:
            resolved.append(att)
    return resolved
