"""Tests for MCP tool implementations.

These tests exercise tool logic directly against MeshState + EventStore,
without going through the MCP transport layer.
"""

import asyncio
import time

import pytest

from mesh_server.events import EventStore
from mesh_server.tools import (
    tool_read_inbox,
    tool_read_inbox_async,
    tool_resolve_channel,
    tool_send,
    tool_show_neighbors,
    tool_shutdown,
    tool_whoami,
)
from mesh_server.auth import generate_token, hash_token
from mesh_server.projections import MeshState
from mesh_server.types import AgentRegistered, BROADCAST_UUID


@pytest.fixture
def store(tmp_path):
    return EventStore(tmp_path / "events.jsonl")


@pytest.fixture
def state():
    return MeshState()


def _register(state, store, uuid="agent-1", pid=100):
    """Helper to register an agent."""
    token = generate_token()
    token_h = hash_token(token)
    event = AgentRegistered(
        uuid=uuid, token_hash=token_h, pid=pid, timestamp=time.time()
    )
    store.append(event)
    state.apply(event)
    return token


def test_inv11_whoami_returns_identity(state, store):  # Tests INV-11
    _register(state, store, "agent-1")
    _register(state, store, "agent-2")
    result = tool_whoami(state, caller_uuid="agent-1")
    assert result["code"] == "ok"
    assert result["data"]["uuid"] == "agent-1"
    assert result["data"]["neighbors_count"] == 2  # includes self


def test_inv12_send_enqueues_message(state, store):  # Tests INV-12
    _register(state, store, "agent-1")
    _register(state, store, "agent-2")
    result = tool_send(
        state,
        store,
        caller_uuid="agent-1",
        to="agent-2",
        message="hello",
        command=None,
    )
    assert result["code"] == "ok"
    assert "agent-2" in result["data"]["delivered_to"]
    inbox = state.get_inbox("agent-2")
    assert len(inbox) == 1
    assert inbox[0].message == "hello"


def test_inv13_read_inbox_drains(state, store):  # Tests INV-13
    _register(state, store, "agent-1")
    _register(state, store, "agent-2")
    tool_send(state, store, caller_uuid="agent-1", to="agent-2", message="hi")
    result = tool_read_inbox(state, store, caller_uuid="agent-2", block=False)
    assert result["code"] == "ok"
    assert len(result["data"]["messages"]) == 1
    assert result["data"]["messages"][0]["message"] == "hi"
    # Inbox should now be empty
    assert len(state.get_inbox("agent-2")) == 0


async def test_inv14_read_inbox_blocks(state, store):  # Tests INV-14
    _register(state, store, "agent-1")
    _register(state, store, "agent-2")

    # Start blocking read in background
    read_task = asyncio.create_task(
        tool_read_inbox_async(state, store, caller_uuid="agent-2", block=True)
    )
    await asyncio.sleep(0.05)  # Let the task start waiting
    assert not read_task.done()

    # Send a message — should wake the reader
    tool_send(state, store, caller_uuid="agent-1", to="agent-2", message="wake")
    result = await asyncio.wait_for(read_task, timeout=2.0)
    assert result["code"] == "ok"
    assert len(result["data"]["messages"]) == 1
    assert result["data"]["messages"][0]["message"] == "wake"


def test_inv15_broadcast_fans_out(state, store):  # Tests INV-15
    _register(state, store, "agent-1")
    _register(state, store, "agent-2")
    _register(state, store, "agent-3")
    result = tool_send(
        state,
        store,
        caller_uuid="agent-1",
        to=BROADCAST_UUID,
        message="broadcast msg",
    )
    assert result["code"] == "ok"
    # Should deliver to agent-2 and agent-3 (not sender agent-1)
    assert len(result["data"]["delivered_to"]) == 2
    assert len(state.get_inbox("agent-2")) == 1
    assert len(state.get_inbox("agent-3")) == 1
    assert len(state.get_inbox("agent-1")) == 0


def test_fail2_send_unknown_uuid(state, store):  # Tests FAIL-2
    _register(state, store, "agent-1")
    result = tool_send(
        state, store, caller_uuid="agent-1", to="nonexistent", message="hi"
    )
    assert result["code"] == "not_found"


def test_fail3_shutdown_deregisters(state, store):  # Tests FAIL-3
    _register(state, store, "agent-1")
    result = tool_shutdown(state, store, caller_uuid="agent-1")
    assert result["code"] == "ok"
    agent = state.get_agent("agent-1")
    assert agent.alive is False


def test_show_neighbors(state, store):
    _register(state, store, "agent-1")
    _register(state, store, "agent-2")
    result = tool_show_neighbors(state, caller_uuid="agent-1")
    assert result["code"] == "ok"
    neighbors = result["data"]["neighbors"]
    uuids = [n["uuid"] for n in neighbors]
    assert "agent-1" in uuids
    assert "agent-2" in uuids


def test_read_inbox_empty_nonblocking(state, store):
    _register(state, store, "agent-1")
    result = tool_read_inbox(state, store, caller_uuid="agent-1", block=False)
    assert result["code"] == "ok"
    assert result["data"]["messages"] == []


# --- Attachment tests ---


def test_inv32_send_stores_attachments(state, store):  # Tests INV-32
    _register(state, store, "agent-1")
    _register(state, store, "agent-2")
    atts = [{"type": "file-ref", "path": "report.pdf"}]
    result = tool_send(
        state,
        store,
        caller_uuid="agent-1",
        to="agent-2",
        message="see attached",
        attachments=atts,
    )
    assert result["code"] == "ok"
    inbox = state.get_inbox("agent-2")
    assert len(inbox) == 1
    assert inbox[0].attachments == atts


def test_inv32_send_without_attachments(state, store):  # Tests INV-32 (no attachments)
    _register(state, store, "agent-1")
    _register(state, store, "agent-2")
    result = tool_send(
        state, store, caller_uuid="agent-1", to="agent-2", message="plain"
    )
    assert result["code"] == "ok"
    inbox = state.get_inbox("agent-2")
    assert inbox[0].attachments is None


def test_inv32_send_empty_attachments_treated_as_none(state, store):  # Tests INV-32
    _register(state, store, "agent-1")
    _register(state, store, "agent-2")
    result = tool_send(
        state,
        store,
        caller_uuid="agent-1",
        to="agent-2",
        message="empty list",
        attachments=[],
    )
    assert result["code"] == "ok"
    inbox = state.get_inbox("agent-2")
    assert inbox[0].attachments is None


_UUID_A = "11111111-1111-1111-1111-111111111111"
_UUID_B = "22222222-2222-2222-2222-222222222222"


def test_inv33_read_inbox_returns_attachments(state, store, tmp_path):  # Tests INV-33
    mesh_dir = tmp_path / ".mesh"
    _register(state, store, _UUID_A)
    _register(state, store, _UUID_B)
    atts = [{"type": "file-ref", "path": "data.csv"}]
    tool_send(
        state,
        store,
        caller_uuid=_UUID_A,
        to=_UUID_B,
        message="check file",
        attachments=atts,
    )
    result = tool_read_inbox(
        state, store, caller_uuid=_UUID_B, block=False, mesh_dir=mesh_dir
    )
    assert result["code"] == "ok"
    msg = result["data"]["messages"][0]
    assert "attachments" in msg
    resolved_path = msg["attachments"][0]["path"]
    # Path should be absolute and contain the mesh_dir
    assert str(mesh_dir) in resolved_path
    assert resolved_path.endswith("data.csv")


def test_inv34_resolve_channel_returns_path(tmp_path):  # Tests INV-34
    mesh_dir = tmp_path / ".mesh"
    result = tool_resolve_channel(
        mesh_dir=mesh_dir,
        caller_uuid=_UUID_A,
        participants=[_UUID_B],
    )
    assert result["code"] == "ok"
    assert "channel_dir" in result["data"]
    assert "attachments_dir" in result["data"]
    assert str(mesh_dir) in result["data"]["channel_dir"]


def test_inv35_resolve_channel_creates_dir(tmp_path):  # Tests INV-35
    mesh_dir = tmp_path / ".mesh"
    result = tool_resolve_channel(
        mesh_dir=mesh_dir,
        caller_uuid=_UUID_A,
        participants=[_UUID_B],
    )
    from pathlib import Path

    channel_dir = Path(result["data"]["channel_dir"])
    attachments_dir = Path(result["data"]["attachments_dir"])
    assert channel_dir.is_dir()
    assert attachments_dir.is_dir()


def test_fail7_send_rejects_non_list_attachments(state, store):  # Tests FAIL-7
    _register(state, store, "agent-1")
    _register(state, store, "agent-2")
    result = tool_send(
        state,
        store,
        caller_uuid="agent-1",
        to="agent-2",
        message="bad",
        attachments="not-a-list",
    )
    assert result["code"] == "invalid_args"
    assert "list" in result["error"]


def test_fail8_send_rejects_attachment_missing_type(state, store):  # Tests FAIL-8
    _register(state, store, "agent-1")
    _register(state, store, "agent-2")
    result = tool_send(
        state,
        store,
        caller_uuid="agent-1",
        to="agent-2",
        message="bad",
        attachments=[{"path": "file.txt"}],
    )
    assert result["code"] == "invalid_args"
    assert "type" in result["error"]


def test_fail9_send_rejects_path_traversal(state, store):  # Tests FAIL-9
    _register(state, store, "agent-1")
    _register(state, store, "agent-2")
    result = tool_send(
        state,
        store,
        caller_uuid="agent-1",
        to="agent-2",
        message="bad",
        attachments=[{"type": "file-ref", "path": "../../../etc/passwd"}],
    )
    assert result["code"] == "invalid_args"
    assert "traversal" in result["error"]


def test_fail10_resolve_channel_rejects_single(tmp_path):  # Tests FAIL-10
    mesh_dir = tmp_path / ".mesh"
    result = tool_resolve_channel(
        mesh_dir=mesh_dir,
        caller_uuid="agent-1",
        participants=[],
    )
    assert result["code"] == "invalid_args"
    assert "participant" in result["error"].lower()
