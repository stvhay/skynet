"""Tool implementations for the mesh server.

Each function takes MeshState + EventStore + caller identity,
performs the operation, and returns a result dict.
"""

from __future__ import annotations

import time
import uuid as uuid_mod
from pathlib import Path

from channels import resolve_channel as channels_resolve

from mesh_server.attachments import (
    normalize_attachments,
    resolve_attachment_paths,
    validate_attachments,
)
from mesh_server.events import EventStore
from mesh_server.projections import MeshState
from mesh_server.types import (
    BROADCAST_UUID,
    AgentDeregistered,
    MessageDrained,
    MessageEnqueued,
)


def _result(code: str, data: dict | None = None, error: str | None = None) -> dict:
    return {"code": code, "data": data or {}, "error": error}


def tool_whoami(state: MeshState, *, caller_uuid: str) -> dict:
    """Return the caller's UUID and neighbor count."""
    agent = state.get_agent(caller_uuid)
    if not agent or not agent.alive:
        return _result("not_found", error=f"Agent {caller_uuid} not registered")
    all_agents = state.list_alive_agents()
    return _result("ok", {"uuid": caller_uuid, "neighbors_count": len(all_agents)})


def tool_send(
    state: MeshState,
    store: EventStore,
    *,
    caller_uuid: str,
    to: str | list[str],
    message: str | None = None,
    command: str | None = None,
    attachments: list | None = None,
) -> dict:
    """Send a message to one or more recipients."""
    # Validate attachments
    err = validate_attachments(attachments)
    if err:
        return _result("invalid_args", error=err)

    # Normalize: empty list -> None
    attachments = normalize_attachments(attachments)

    # Normalize to a list of recipient UUIDs
    if isinstance(to, str):
        if to == BROADCAST_UUID:
            recipients = [
                a.uuid for a in state.list_alive_agents() if a.uuid != caller_uuid
            ]
        else:
            recipients = [to]
    else:
        recipients = list(to)

    # Validate recipients
    delivered_to = []
    for recipient in recipients:
        agent = state.get_agent(recipient)
        if not agent or not agent.alive:
            if len(recipients) == 1:
                return _result("not_found", error=f"Agent {recipient} not found")
            continue  # Skip dead agents in broadcast/group

        msg_id = str(uuid_mod.uuid4())
        event = MessageEnqueued(
            id=msg_id,
            from_uuid=caller_uuid,
            to_uuid=recipient,
            command=command,
            message=message,
            timestamp=time.time(),
            attachments=attachments,
        )
        store.append(event)
        state.apply(event)
        delivered_to.append(recipient)

    return _result("ok", {"delivered_to": delivered_to})


def _format_message(msg: "Message", *, mesh_dir: Path | None = None) -> dict:
    """Format a Message for tool output, optionally resolving attachment paths."""
    attachments = msg.attachments
    if attachments and mesh_dir is not None:
        attachments = resolve_attachment_paths(
            attachments,
            from_uuid=msg.from_uuid,
            to_uuid=msg.to_uuid,
            mesh_dir=mesh_dir,
        )
    result = {
        "id": msg.id,
        "from": msg.from_uuid,
        "to": msg.to_uuid,
        "command": msg.command,
        "message": msg.message,
        "timestamp": msg.timestamp,
    }
    if attachments:
        result["attachments"] = attachments
    return result


def tool_read_inbox(
    state: MeshState,
    store: EventStore,
    *,
    caller_uuid: str,
    block: bool = False,
    mesh_dir: Path | None = None,
) -> dict:
    """Read and drain inbox (non-blocking version)."""
    messages = state.get_inbox(caller_uuid)
    # Drain: emit MessageDrained events
    for msg in messages:
        drain_event = MessageDrained(
            message_id=msg.id, by_uuid=caller_uuid, timestamp=time.time()
        )
        store.append(drain_event)
        state.apply(drain_event)

    return _result(
        "ok",
        {
            "messages": [
                _format_message(m, mesh_dir=mesh_dir) for m in messages
            ]
        },
    )


async def tool_read_inbox_async(
    state: MeshState,
    store: EventStore,
    *,
    caller_uuid: str,
    block: bool = False,
    mesh_dir: Path | None = None,
) -> dict:
    """Read and drain inbox. If block=True, waits indefinitely for a message."""
    if block:
        # Check if inbox is empty — if so, wait
        messages = state.get_inbox(caller_uuid)
        if not messages:
            waiter = state.set_waiter(caller_uuid)
            try:
                await waiter.wait()
            finally:
                state.clear_waiter(caller_uuid)

    # Now drain (whether we waited or not)
    return tool_read_inbox(
        state, store, caller_uuid=caller_uuid, block=False, mesh_dir=mesh_dir
    )


def tool_show_neighbors(state: MeshState, *, caller_uuid: str) -> dict:
    """List all registered agents."""
    agents = state.list_all_agents()
    return _result(
        "ok",
        {
            "neighbors": [
                {
                    "uuid": a.uuid,
                    "alive": a.alive,
                    "state": a.state.value,
                    "pid": a.pid,
                }
                for a in agents
            ]
        },
    )


def tool_shutdown(
    state: MeshState,
    store: EventStore,
    *,
    caller_uuid: str,
) -> dict:
    """Agent self-terminates."""
    agent = state.get_agent(caller_uuid)
    if not agent or not agent.alive:
        return _result("not_found", error=f"Agent {caller_uuid} not found")

    event = AgentDeregistered(
        uuid=caller_uuid, reason="self_shutdown", timestamp=time.time()
    )
    store.append(event)
    state.apply(event)
    return _result("ok")


def tool_resolve_channel(
    *,
    mesh_dir: Path,
    caller_uuid: str,
    participants: list[str],
) -> dict:
    """Resolve channel directory for a set of participants."""
    all_participants = sorted(set([caller_uuid] + participants))
    if len(all_participants) < 2:
        return _result("invalid_args", error="Need at least one other participant")
    try:
        result = channels_resolve(mesh_dir=mesh_dir, participants=all_participants)
        return _result("ok", result)
    except ValueError as e:
        return _result("invalid_args", error=str(e))
