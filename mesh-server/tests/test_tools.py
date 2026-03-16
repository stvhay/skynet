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
