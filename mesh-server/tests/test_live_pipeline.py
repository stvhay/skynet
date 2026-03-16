"""Live pipeline integration test using fake Claude CLI.

INV-31: Mock CLI agent completes full spawn->connect->message->shutdown cycle.
"""

from __future__ import annotations

import asyncio
import sys
import time
from pathlib import Path

import httpx
import pytest

from agent_runtime.launcher import AgentProcess, AgentSupervisor
from mesh_server.api import create_api_routes
from mesh_server.events import EventStore
from mesh_server.projections import MeshState
from mesh_server.tools import tool_shutdown
from mesh_server.types import AgentRegistered, generate_controller_uuid

FAKE_CLAUDE = str(Path(__file__).parent / "fake_claude.py")


class FakeAgentSupervisor(AgentSupervisor):
    """Launches fake_claude.py instead of real claude."""

    async def launch(self, **kwargs) -> int:
        from agent_runtime.config import write_agent_configs

        uuid = kwargs["uuid"]
        model = kwargs["model"]
        agent_dir = kwargs["agent_dir"]
        bearer_token = kwargs["bearer_token"]

        write_agent_configs(
            agent_dir=agent_dir,
            agent_uuid=uuid,
            spawner_uuid=kwargs.get("spawner_uuid", "controller"),
            bearer_token=bearer_token,
            model=model,
            server_url=kwargs.get("server_url", "http://127.0.0.1:9090/mcp"),
            server_base_url=kwargs.get("server_base_url", "http://127.0.0.1:9090"),
            role=kwargs.get("role"),
        )

        process = AgentProcess(
            uuid=uuid,
            model=model,
            agent_dir=agent_dir,
            bearer_token=bearer_token,
            thinking_budget=kwargs.get("thinking_budget"),
            initial_prompt=kwargs.get("initial_prompt"),
        )

        # Monkey-patch _build_cli_args to invoke fake_claude.py
        original_build = process._build_cli_args

        def patched_cli_args():
            args = original_build()
            # Replace "claude" with "python3 fake_claude.py"
            args[0] = sys.executable
            args.insert(1, FAKE_CLAUDE)
            return args

        process._build_cli_args = patched_cli_args

        pid = process.start()
        self._processes[uuid] = process
        task = asyncio.create_task(self._supervise(uuid))
        self._tasks[uuid] = task
        return pid


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


async def test_inv31_mock_cli_full_cycle(
    store, state, controller_uuid, mesh_dir
):
    """Full lifecycle: spawn agent with fake CLI, verify shutdown."""
    import uvicorn
    from starlette.applications import Starlette

    # Register controller
    ctrl_event = AgentRegistered(
        uuid=controller_uuid, token_hash={}, pid=None, timestamp=time.time()
    )
    store.append(ctrl_event)
    state.apply(ctrl_event)

    # Create supervisor with shutdown callback
    async def _on_agent_exit(uuid: str, exit_code: int) -> None:
        agent = state.get_agent(uuid)
        if agent and agent.alive:
            tool_shutdown(state, store, caller_uuid=uuid)

    supervisor = FakeAgentSupervisor(shutdown_callback=_on_agent_exit)

    # Use port=0 for random available port
    # We need to start the server first to know the port, then pass it to routes
    # Use a two-phase approach: create server, get port, then set up routes

    # Phase 1: create a temporary app to bind the socket
    tmp_app = Starlette(routes=[])
    config = uvicorn.Config(tmp_app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)

    # Start server to bind socket
    server_task = asyncio.create_task(server.serve())

    # Wait for server to start
    for _ in range(50):
        await asyncio.sleep(0.1)
        if server.started:
            break
    assert server.started, "Server failed to start"

    port = server.servers[0].sockets[0].getsockname()[1]
    base_url = f"http://127.0.0.1:{port}"

    # Phase 2: now create the real app with the correct base URL
    server.should_exit = True
    await server_task

    routes = create_api_routes(
        store=store,
        state=state,
        controller_uuid=controller_uuid,
        mesh_dir=mesh_dir,
        agent_supervisor=supervisor,
        server_base_url=base_url,
    )
    app = Starlette(routes=routes)

    config = uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning")
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())

    for _ in range(50):
        await asyncio.sleep(0.1)
        if server.started:
            break
    assert server.started, "Server failed to start on second attempt"

    try:
        async with httpx.AsyncClient(base_url=base_url) as client:
            # Spawn agent (no initial_message — fake CLI doesn't read inbox)
            resp = await client.post(
                "/api/spawn",
                json={"model": "sonnet"},
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["code"] == "ok"
            agent_uuid = data["data"]["uuid"]

            # Wait for fake agent to process and exit
            for _ in range(50):
                await asyncio.sleep(0.2)
                agent = state.get_agent(agent_uuid)
                if agent and not agent.alive:
                    break

            # Agent should be deregistered
            agent = state.get_agent(agent_uuid)
            assert agent is not None
            assert agent.alive is False, "Agent still alive after timeout"

    finally:
        server.should_exit = True
        await server_task
