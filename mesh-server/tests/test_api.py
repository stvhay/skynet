"""Tests for REST/SSE API endpoints.

Tests exercise API routes via httpx AsyncClient with ASGITransport,
without starting an HTTP server.
"""

from __future__ import annotations

import time

import httpx
import pytest
from starlette.applications import Starlette

from mesh_server.api import create_api_routes
from mesh_server.auth import generate_token, hash_token
from mesh_server.events import EventStore
from mesh_server.projections import MeshState
from mesh_server.types import AgentRegistered, generate_controller_uuid


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
    """Create a Starlette test app with API routes."""
    # Register controller as agent
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


def _register_agent(state, store, uuid="agent-1", pid=100):
    """Register an agent in state and store."""
    token = generate_token()
    token_h = hash_token(token)
    event = AgentRegistered(
        uuid=uuid, token_hash=token_h, pid=pid, timestamp=time.time()
    )
    store.append(event)
    state.apply(event)
    return token


async def test_inv22_api_agents(client, state, store, controller_uuid):
    """GET /api/agents returns registered agents."""
    _register_agent(state, store, "agent-1", pid=111)
    _register_agent(state, store, "agent-2", pid=222)

    resp = await client.get("/api/agents")
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == "ok"
    uuids = [n["uuid"] for n in data["data"]["neighbors"]]
    assert controller_uuid in uuids
    assert "agent-1" in uuids
    assert "agent-2" in uuids


async def test_inv23_api_send(client, state, store, controller_uuid):
    """POST /api/send enqueues message from controller."""
    _register_agent(state, store, "agent-1")

    resp = await client.post(
        "/api/send",
        json={"to": "agent-1", "message": "hello from controller"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == "ok"
    assert "agent-1" in data["data"]["delivered_to"]

    # Verify message is in inbox
    inbox = state.get_inbox("agent-1")
    assert len(inbox) == 1
    assert inbox[0].message == "hello from controller"
    assert inbox[0].from_uuid == controller_uuid


async def test_inv23_api_send_missing_to(client):
    """POST /api/send without 'to' returns 400."""
    resp = await client.post("/api/send", json={"message": "no recipient"})
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_args"


async def test_inv23_api_send_malformed_json(client):
    """POST /api/send with invalid JSON body returns 400."""
    resp = await client.post(
        "/api/send",
        content=b"not valid json{{{",
        headers={"Content-Type": "application/json"},
    )
    assert resp.status_code == 400
    assert resp.json()["code"] == "invalid_args"


async def test_inv24_api_spawn(client, state, store, mesh_dir):
    """POST /api/spawn registers a new agent."""
    resp = await client.post(
        "/api/spawn",
        json={"model": "sonnet"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == "ok"
    new_uuid = data["data"]["uuid"]

    # Verify agent is registered
    agent = state.get_agent(new_uuid)
    assert agent is not None
    assert agent.alive is True


async def test_inv24_api_spawn_with_initial_message(
    client, state, store, controller_uuid, mesh_dir
):
    """POST /api/spawn with initial_message auto-sends to new agent."""
    resp = await client.post(
        "/api/spawn",
        json={"model": "sonnet", "initial_message": "Your task is X"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == "ok"
    new_uuid = data["data"]["uuid"]

    # Verify initial message is in new agent's inbox
    inbox = state.get_inbox(new_uuid)
    assert len(inbox) == 1
    assert inbox[0].message == "Your task is X"
    assert inbox[0].from_uuid == controller_uuid


async def test_inv25_api_shutdown(client, state, store):
    """POST /api/agents/{uuid}/shutdown deregisters agent."""
    _register_agent(state, store, "agent-1")
    assert state.get_agent("agent-1").alive is True

    resp = await client.post("/api/agents/agent-1/shutdown")
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == "ok"

    # Verify agent is dead
    agent = state.get_agent("agent-1")
    assert agent.alive is False


async def test_inv26_api_inbox(client, state, store, controller_uuid):
    """GET /api/inbox returns controller's messages."""
    _register_agent(state, store, "agent-1")

    # Agent sends message to controller
    from mesh_server.tools import tool_send

    tool_send(
        state,
        store,
        caller_uuid="agent-1",
        to=controller_uuid,
        message="status report",
    )

    resp = await client.get("/api/inbox")
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == "ok"
    assert len(data["data"]["messages"]) == 1
    assert data["data"]["messages"][0]["message"] == "status report"

    # Inbox should be drained after reading
    inbox = state.get_inbox(controller_uuid)
    assert len(inbox) == 0


async def test_inv21_api_events_streams_sse(store, state, controller_uuid, mesh_dir):
    """GET /api/events streams events via SSE.

    Tests the pub/sub mechanism and the ASGI response headers.
    httpx's ASGITransport cannot test true streaming (it buffers the full
    response), so we test the underlying pub/sub separately and verify
    the endpoint sends correct SSE headers via raw ASGI.
    """
    import asyncio

    # Test 1: Verify pub/sub delivers events (the mechanism SSE relies on)
    queue: asyncio.Queue = asyncio.Queue()
    store.subscribe(queue)
    event = AgentRegistered(
        uuid="sse-test-agent", token_hash={}, pid=None, timestamp=time.time()
    )
    store.append(event)
    received = queue.get_nowait()
    assert received.uuid == "sse-test-agent"
    store.unsubscribe(queue)

    # Test 2: Verify SSE endpoint sends correct headers and streams data
    # by calling the ASGI app directly
    ctrl_event = AgentRegistered(
        uuid=controller_uuid, token_hash={}, pid=None, timestamp=time.time()
    )
    store.append(ctrl_event)
    state.apply(ctrl_event)

    routes = create_api_routes(
        store=store, state=state, controller_uuid=controller_uuid, mesh_dir=mesh_dir
    )
    test_app = Starlette(routes=routes)

    # Capture ASGI messages
    messages: list[dict] = []
    response_started = asyncio.Event()
    got_body = asyncio.Event()

    async def receive():
        # Simulate client disconnect after we get what we need
        await got_body.wait()
        return {"type": "http.disconnect"}

    async def send(message):
        messages.append(message)
        if message["type"] == "http.response.start":
            response_started.set()
        if message["type"] == "http.response.body" and message.get("body"):
            got_body.set()

    scope = {
        "type": "http",
        "method": "GET",
        "path": "/api/events",
        "query_string": b"",
        "headers": [],
        "root_path": "",
    }

    # Fire an event so the stream has data to send
    async def fire_event():
        await response_started.wait()
        await asyncio.sleep(0.01)
        store.append(
            AgentRegistered(
                uuid="sse-live-agent", token_hash={}, pid=None, timestamp=time.time()
            )
        )

    task = asyncio.create_task(fire_event())
    app_task = asyncio.create_task(test_app(scope, receive, send))

    await asyncio.wait_for(got_body.wait(), timeout=5.0)
    app_task.cancel()
    task.cancel()

    # Verify response headers
    start_msg = messages[0]
    assert start_msg["type"] == "http.response.start"
    assert start_msg["status"] == 200
    headers = dict(start_msg["headers"])
    assert b"text/event-stream" in headers[b"content-type"]

    # Verify body contains SSE data
    body_chunks = [
        m["body"].decode()
        for m in messages
        if m["type"] == "http.response.body" and m.get("body")
    ]
    combined = "".join(body_chunks)
    assert "data:" in combined
    assert "sse-live-agent" in combined


async def test_inv21_api_events_pubsub(store):
    """EventStore pub/sub delivers events to subscriber queues."""
    import asyncio

    queue: asyncio.Queue = asyncio.Queue()
    store.subscribe(queue)

    # Append an event
    event = AgentRegistered(
        uuid="test-agent",
        token_hash={},
        pid=None,
        timestamp=time.time(),
    )
    store.append(event)

    # Event should be in queue
    received = queue.get_nowait()
    assert received.uuid == "test-agent"

    store.unsubscribe(queue)


async def test_index_page(client):
    """GET / returns HTML controller UI."""
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "MCP Mesh" in resp.text
    assert "d3.v7" in resp.text
