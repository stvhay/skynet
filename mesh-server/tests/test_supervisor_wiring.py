"""Tests for AgentSupervisor wiring into mesh-server spawn paths.

INV-29: REST spawn calls supervisor.launch() with correct parameters.
"""

from __future__ import annotations

import time
from unittest.mock import AsyncMock

import httpx
import pytest
from starlette.applications import Starlette

from mesh_server.api import create_api_routes
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


def _make_app(store, state, controller_uuid, mesh_dir, agent_supervisor=None):
    """Create a Starlette test app with API routes and optional supervisor."""
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
        agent_supervisor=agent_supervisor,
    )
    return Starlette(routes=routes)


async def test_inv29_rest_spawn_calls_supervisor_launch(
    store, state, controller_uuid, mesh_dir
):
    """POST /api/spawn calls supervisor.launch() with correct explicit kwargs."""
    mock_supervisor = AsyncMock()
    mock_supervisor.launch = AsyncMock(return_value=12345)

    app = _make_app(store, state, controller_uuid, mesh_dir, mock_supervisor)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/spawn", json={"model": "sonnet"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == "ok"

    # Verify supervisor.launch() was called exactly once
    mock_supervisor.launch.assert_called_once()

    # Verify explicit kwargs were passed (not just **result["data"])
    call_kwargs = mock_supervisor.launch.call_args.kwargs
    assert call_kwargs["uuid"] == data["data"]["uuid"]
    assert call_kwargs["model"] == data["data"]["model"]
    assert call_kwargs["agent_dir"] == data["data"]["agent_dir"]
    assert call_kwargs["bearer_token"] == data["data"]["bearer_token"]
    assert call_kwargs["spawner_uuid"] == controller_uuid
    assert call_kwargs["server_url"] == "http://127.0.0.1:9090/mcp"
    assert call_kwargs["server_base_url"] == "http://127.0.0.1:9090"


async def test_inv29_rest_spawn_works_without_supervisor(
    store, state, controller_uuid, mesh_dir
):
    """POST /api/spawn works when no supervisor is configured (backward compat)."""
    app = _make_app(store, state, controller_uuid, mesh_dir, agent_supervisor=None)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/spawn", json={"model": "sonnet"})

    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == "ok"
    assert "uuid" in data["data"]
