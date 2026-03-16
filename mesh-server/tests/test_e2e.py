"""End-to-end integration tests for spawn-chain demo scenario.

Tests simulate the full spawn-chain workflow through the REST API
using mock agents (no real Claude CLI). Verifies that controller
can spawn agents, agents can exchange messages, shut down, and
that all events are captured correctly.
"""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest
from starlette.applications import Starlette

from mesh_server.api import create_api_routes
from mesh_server.events import EventStore
from mesh_server.projections import MeshState
from mesh_server.tools import tool_send, tool_shutdown
from mesh_server.types import (
    AgentDeregistered,
    AgentRegistered,
    MessageEnqueued,
    generate_controller_uuid,
)


@pytest.fixture
def store(tmp_path):
    return EventStore(tmp_path / "events.jsonl")


@pytest.fixture
def state():
    return MeshState()


@pytest.fixture
def controller_uuid():
    return generate_controller_uuid()


@pytest.fixture
def mesh_dir(tmp_path):
    return tmp_path / "mesh"


@pytest.fixture
def app(store, state, controller_uuid, mesh_dir):
    """Create a Starlette test app with API routes and pre-registered controller."""
    ctrl_event = AgentRegistered(
        uuid=controller_uuid,
        token_hash={},
        pid=None,
        timestamp=time.time(),
    )
    store.append(ctrl_event)
    state.apply(ctrl_event)

    routes = create_api_routes(
        store=store,
        state=state,
        controller_uuid=controller_uuid,
        mesh_dir=mesh_dir,
    )
    return Starlette(routes=routes)


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_inv27_spawn_chain_e2e(client, state, store, controller_uuid):
    """Full spawn-chain demo: controller spawns A, A spawns B, messages flow, both shut down."""

    # Step 1: Controller spawns Agent A (sonnet) with initial_message
    resp = await client.post(
        "/api/spawn",
        json={
            "model": "sonnet",
            "initial_message": "Begin your task: research auth module",
        },
    )
    assert resp.status_code == 200
    data_a = resp.json()
    assert data_a["code"] == "ok"
    uuid_a = data_a["data"]["uuid"]

    # Verify A is registered and alive
    agent_a = state.get_agent(uuid_a)
    assert agent_a is not None
    assert agent_a.alive is True

    # Verify A has the initial message in its inbox
    inbox_a = state.get_inbox(uuid_a)
    assert len(inbox_a) == 1
    assert inbox_a[0].message == "Begin your task: research auth module"
    assert inbox_a[0].from_uuid == controller_uuid

    # Step 2: Simulate Agent A spawning Agent B (haiku)
    # In production A would call spawn_neighbor via MCP; here controller proxies via REST
    resp = await client.post(
        "/api/spawn",
        json={"model": "haiku"},
    )
    assert resp.status_code == 200
    data_b = resp.json()
    assert data_b["code"] == "ok"
    uuid_b = data_b["data"]["uuid"]

    # Verify B is registered
    agent_b = state.get_agent(uuid_b)
    assert agent_b is not None
    assert agent_b.alive is True

    # Step 3: Agent A sends task to Agent B
    result = tool_send(
        state,
        store,
        caller_uuid=uuid_a,
        to=uuid_b,
        message="Subtask: review auth token generation",
    )
    assert result["code"] == "ok"
    assert uuid_b in result["data"]["delivered_to"]

    # Verify B has the message
    inbox_b = state.get_inbox(uuid_b)
    assert len(inbox_b) == 1
    assert inbox_b[0].message == "Subtask: review auth token generation"
    assert inbox_b[0].from_uuid == uuid_a

    # Step 4: Agent B reports back to Agent A
    result = tool_send(
        state,
        store,
        caller_uuid=uuid_b,
        to=uuid_a,
        message="Auth tokens use scrypt, looks solid",
    )
    assert result["code"] == "ok"

    # Step 5: Agent B shuts down
    resp = await client.post(f"/api/agents/{uuid_b}/shutdown")
    assert resp.status_code == 200
    assert resp.json()["code"] == "ok"

    # Verify B is dead
    agent_b = state.get_agent(uuid_b)
    assert agent_b.alive is False

    # Step 6: Agent A reports summary to controller
    result = tool_send(
        state,
        store,
        caller_uuid=uuid_a,
        to=controller_uuid,
        message="Summary: auth module reviewed, tokens use scrypt, no issues found",
    )
    assert result["code"] == "ok"

    # Step 7: Agent A shuts down
    resp = await client.post(f"/api/agents/{uuid_a}/shutdown")
    assert resp.status_code == 200
    assert resp.json()["code"] == "ok"

    # Verify A is dead
    agent_a = state.get_agent(uuid_a)
    assert agent_a.alive is False

    # Step 8: Verify controller inbox has the summary message
    resp = await client.get("/api/inbox")
    assert resp.status_code == 200
    inbox_data = resp.json()
    assert inbox_data["code"] == "ok"
    messages = inbox_data["data"]["messages"]
    assert len(messages) == 1
    assert "auth module reviewed" in messages[0]["message"]
    assert messages[0]["from"] == uuid_a

    # Step 9: Verify event log contains all expected events
    events = store.replay()

    registered_events = [e for e in events if isinstance(e, AgentRegistered)]
    enqueued_events = [e for e in events if isinstance(e, MessageEnqueued)]
    deregistered_events = [e for e in events if isinstance(e, AgentDeregistered)]

    # 3 registrations: controller + A + B
    assert len(registered_events) >= 3, (
        f"Expected >= 3 AgentRegistered, got {len(registered_events)}"
    )
    # 4 messages: initial to A, A->B, B->A, A->controller
    assert len(enqueued_events) >= 4, (
        f"Expected >= 4 MessageEnqueued, got {len(enqueued_events)}"
    )
    # 2 deregistrations: B + A
    assert len(deregistered_events) >= 2, (
        f"Expected >= 2 AgentDeregistered, got {len(deregistered_events)}"
    )


async def test_inv27_sse_captures_spawn_chain_events(
    store, state, controller_uuid, mesh_dir
):
    """SSE subscribers see all events from a simplified spawn chain."""
    # Register controller
    ctrl_event = AgentRegistered(
        uuid=controller_uuid,
        token_hash={},
        pid=None,
        timestamp=time.time(),
    )
    store.append(ctrl_event)
    state.apply(ctrl_event)

    # Subscribe a queue to capture events
    queue: asyncio.Queue = asyncio.Queue()
    store.subscribe(queue)

    try:
        # Spawn agent A via prepare_spawn (simulating REST /api/spawn)
        from mesh_server.spawner import prepare_spawn

        result_a = prepare_spawn(state, store, mesh_dir=mesh_dir, model="sonnet")
        assert result_a["code"] == "ok"
        uuid_a = result_a["data"]["uuid"]

        # Controller sends initial message to A
        tool_send(
            state,
            store,
            caller_uuid=controller_uuid,
            to=uuid_a,
            message="Do the thing",
        )

        # A sends report to controller
        tool_send(
            state,
            store,
            caller_uuid=uuid_a,
            to=controller_uuid,
            message="Done",
        )

        # A shuts down
        tool_shutdown(state, store, caller_uuid=uuid_a)

        # Collect all events from queue
        received_events = []
        while not queue.empty():
            received_events.append(queue.get_nowait())

        # Verify event types: the ctrl_event was appended before subscribe,
        # so we expect: AgentRegistered(A), MessageEnqueued(ctrl->A),
        # MessageEnqueued(A->ctrl), AgentDeregistered(A)
        type_names = [type(e).__name__ for e in received_events]
        assert "AgentRegistered" in type_names
        assert type_names.count("MessageEnqueued") >= 2
        assert "AgentDeregistered" in type_names

        # Verify ordering: registration before messages before deregistration
        reg_idx = type_names.index("AgentRegistered")
        dereg_idx = len(type_names) - 1 - type_names[::-1].index("AgentDeregistered")
        assert reg_idx < dereg_idx

    finally:
        store.unsubscribe(queue)


async def test_inv27_api_agents_reflects_lifecycle(client, state, store, mesh_dir):
    """GET /api/agents shows correct state at each lifecycle step."""

    # Spawn an agent
    resp = await client.post("/api/spawn", json={"model": "haiku"})
    assert resp.status_code == 200
    uuid_a = resp.json()["data"]["uuid"]

    # Verify agent appears as alive in /api/agents
    resp = await client.get("/api/agents")
    assert resp.status_code == 200
    agents_data = resp.json()["data"]["neighbors"]
    agent_entry = next(n for n in agents_data if n["uuid"] == uuid_a)
    assert agent_entry["alive"] is True

    # Shut down the agent
    resp = await client.post(f"/api/agents/{uuid_a}/shutdown")
    assert resp.status_code == 200

    # Verify agent appears as dead in /api/agents
    resp = await client.get("/api/agents")
    assert resp.status_code == 200
    agents_data = resp.json()["data"]["neighbors"]
    agent_entry = next(n for n in agents_data if n["uuid"] == uuid_a)
    assert agent_entry["alive"] is False
