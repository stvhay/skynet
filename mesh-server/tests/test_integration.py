"""Integration test: full mesh message exchange."""

import asyncio

import pytest

from mesh_server.events import EventStore
from mesh_server.projections import MeshState
from mesh_server.spawner import prepare_spawn
from mesh_server.tools import (
    tool_read_inbox,
    tool_read_inbox_async,
    tool_send,
    tool_show_neighbors,
    tool_shutdown,
    tool_whoami,
)


@pytest.fixture
def mesh(tmp_path):
    """Set up a fresh mesh with event store and state."""
    mesh_dir = tmp_path / ".mesh"
    store = EventStore(mesh_dir / "events.jsonl")
    state = MeshState()
    return store, state, mesh_dir


def test_inv18_e2e_message_exchange(mesh):  # Tests INV-18
    """Two agents register, exchange messages, and shut down."""
    store, state, mesh_dir = mesh

    # Spawn agent A
    result_a = prepare_spawn(
        state, store, mesh_dir=mesh_dir, claude_md="Agent A: coordinator"
    )
    assert result_a["code"] == "ok"
    uuid_a = result_a["data"]["uuid"]

    # Spawn agent B
    result_b = prepare_spawn(
        state, store, mesh_dir=mesh_dir, claude_md="Agent B: worker"
    )
    assert result_b["code"] == "ok"
    uuid_b = result_b["data"]["uuid"]

    # A checks identity
    whoami_a = tool_whoami(state, caller_uuid=uuid_a)
    assert whoami_a["data"]["uuid"] == uuid_a
    assert whoami_a["data"]["neighbors_count"] == 2

    # A sees B as neighbor
    neighbors = tool_show_neighbors(state, caller_uuid=uuid_a)
    uuids = [n["uuid"] for n in neighbors["data"]["neighbors"]]
    assert uuid_b in uuids

    # A sends message to B
    send_result = tool_send(
        state,
        store,
        caller_uuid=uuid_a,
        to=uuid_b,
        message="Please review the auth module.",
        command="review",
    )
    assert send_result["code"] == "ok"
    assert uuid_b in send_result["data"]["delivered_to"]

    # B reads inbox
    read_result = tool_read_inbox(state, store, caller_uuid=uuid_b, block=False)
    assert read_result["code"] == "ok"
    messages = read_result["data"]["messages"]
    assert len(messages) == 1
    assert messages[0]["from"] == uuid_a
    assert messages[0]["message"] == "Please review the auth module."
    assert messages[0]["command"] == "review"

    # B replies to A
    tool_send(
        state,
        store,
        caller_uuid=uuid_b,
        to=uuid_a,
        message="Review complete. LGTM.",
        command="review_response",
    )

    # A reads reply
    reply = tool_read_inbox(state, store, caller_uuid=uuid_a, block=False)
    assert reply["code"] == "ok"
    assert len(reply["data"]["messages"]) == 1
    assert reply["data"]["messages"][0]["message"] == "Review complete. LGTM."

    # Both shut down
    tool_shutdown(state, store, caller_uuid=uuid_a)
    tool_shutdown(state, store, caller_uuid=uuid_b)

    # Verify both are dead
    assert state.get_agent(uuid_a).alive is False
    assert state.get_agent(uuid_b).alive is False

    # Verify event log has full sequence
    events = store.replay()
    assert len(events) >= 8  # 2 register + 2 send + 2 drain + 2 deregister


def test_e2e_server_restart_recovers_state(mesh):
    """Server restart (replay) recovers all registered agents and pending messages."""
    store, state, mesh_dir = mesh

    result_a = prepare_spawn(state, store, mesh_dir=mesh_dir)
    uuid_a = result_a["data"]["uuid"]
    result_b = prepare_spawn(state, store, mesh_dir=mesh_dir)
    uuid_b = result_b["data"]["uuid"]
    tool_send(state, store, caller_uuid=uuid_a, to=uuid_b, message="pending")

    # Simulate server restart
    new_state = MeshState()
    for event in store.replay():
        new_state.apply(event)

    inbox = new_state.get_inbox(uuid_b)
    assert len(inbox) == 1
    assert inbox[0].message == "pending"
    assert new_state.get_agent(uuid_a).alive is True
    assert new_state.get_agent(uuid_b).alive is True


async def test_e2e_blocking_read(mesh):
    """Blocking read_inbox yields until message arrives."""
    store, state, mesh_dir = mesh

    result_a = prepare_spawn(state, store, mesh_dir=mesh_dir)
    uuid_a = result_a["data"]["uuid"]
    result_b = prepare_spawn(state, store, mesh_dir=mesh_dir)
    uuid_b = result_b["data"]["uuid"]

    read_task = asyncio.create_task(
        tool_read_inbox_async(state, store, caller_uuid=uuid_b, block=True)
    )
    await asyncio.sleep(0.05)
    assert not read_task.done()

    tool_send(state, store, caller_uuid=uuid_a, to=uuid_b, message="wake up")
    result = await asyncio.wait_for(read_task, timeout=2.0)
    assert result["code"] == "ok"
    assert result["data"]["messages"][0]["message"] == "wake up"
