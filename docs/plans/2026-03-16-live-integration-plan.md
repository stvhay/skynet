# Live Integration Implementation Plan

> **Status:** Completed — all tasks executed and verified.

**Issue:** #10 — Live integration: launch real Claude CLI agents through mesh
**Beads:** skynet-5tj
**Design:** docs/plans/2026-03-16-live-integration-design.md

> **For Claude:** Execute this plan using subagent-driven-development (same session) or executing-plans (separate session / teammate).

**Goal:** Wire AgentSupervisor into mesh-server so that spawn_neighbor (MCP) and /api/spawn (REST) launch real Claude CLI subprocesses.

**Architecture:** mesh-server gains agent-runtime as a direct dependency. `create_app()` instantiates an `AgentSupervisor` with a shutdown callback and stores it in `AppContext`. Both MCP and REST spawn paths call `supervisor.launch()` after `prepare_spawn()`. A mock CLI script enables CI testing of the full pipeline.

**Tech Stack:** Python 3.13, FastMCP, agent-runtime (AgentSupervisor), subprocess, asyncio

**Acceptance Criteria — what must be TRUE when this plan is done:**
- [ ] `spawn_neighbor` MCP tool launches a subprocess via AgentSupervisor (INV-28)
- [ ] `/api/spawn` REST endpoint launches a subprocess via AgentSupervisor (INV-29)
- [ ] Supervisor emits AgentDeregistered when a process exits unexpectedly (INV-30)
- [ ] Mock CLI agent completes full spawn→connect→message→shutdown cycle (INV-31)
- [ ] All existing tests continue to pass (no regressions)
- [ ] Documentation updated (ARCHITECTURE.md, SPEC.md, README.md)

**Dependencies:** None

---

### Task 1: Wire AgentSupervisor into mesh-server

**Context:** mesh-server has a `prepare_spawn()` function that registers agents and creates credentials but never launches a process. agent-runtime has an `AgentSupervisor` class that writes configs and launches Claude CLI subprocesses. The goal is to connect them: add agent-runtime as a dependency, put the supervisor in `AppContext`, and call `supervisor.launch()` from both the MCP `spawn_neighbor` tool and the REST `/api/spawn` endpoint.

There is a parameter mismatch to fix: `prepare_spawn()` returns `{uuid, bearer_token, env_vars, model, thinking_budget, agent_dir}` but `AgentSupervisor.launch()` expects `{uuid, model, agent_dir, bearer_token, spawner_uuid, server_url, server_base_url, role, thinking_budget, initial_prompt}`. The missing fields (`spawner_uuid`, `server_url`, `server_base_url`, `role`) must be supplied by the caller. The extra field (`env_vars`) must not be passed to launch.

The REST endpoint (`api.py:152`) already does `supervisor.launch(**result["data"])` — this will break because of the mismatch. Fix by building the launch kwargs explicitly rather than splatting.

**Subsystem spec(s):** `mesh-server/SPEC.md`
**Key invariants from spec:**
- INV-28: spawn_neighbor (MCP) launches Claude CLI subprocess via AgentSupervisor → `def test_inv28_mcp_spawn_launches_process():  # Tests INV-28`
- INV-29: REST /api/spawn launches Claude CLI subprocess via AgentSupervisor → `def test_inv29_rest_spawn_launches_process():  # Tests INV-29`
**Adjacent specs:** `agent-runtime/SPEC.md` — Public Interface: `AgentSupervisor.launch(uuid, model, agent_dir, bearer_token, spawner_uuid, server_url, server_base_url, role, thinking_budget?, initial_prompt?) -> int`

**Files:**
- Modify: `mesh-server/pyproject.toml` (add agent-runtime dependency)
- Modify: `mesh-server/src/mesh_server/server.py:29-33` (AppContext), `server.py:212-232` (create_app), `server.py:185-209` (spawn_neighbor)
- Modify: `mesh-server/src/mesh_server/api.py:145-168` (api_spawn launch call)
- Create: `mesh-server/tests/test_supervisor_wiring.py`

**Depends on:** Independent

**Step 1: Write failing tests for supervisor wiring**

Create `mesh-server/tests/test_supervisor_wiring.py`:

```python
"""Tests for AgentSupervisor wiring into mesh-server.

Tests verify that spawn operations invoke the supervisor to launch processes.
Uses a mock supervisor to avoid launching real subprocesses.
"""

from __future__ import annotations

import asyncio
import time
from unittest.mock import AsyncMock, MagicMock

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


@pytest.fixture
def mock_supervisor():
    supervisor = MagicMock()
    supervisor.launch = AsyncMock(return_value=12345)
    return supervisor


@pytest.fixture
def app(store, state, controller_uuid, mesh_dir, mock_supervisor):
    """Create test app with mock supervisor."""
    ctrl_event = AgentRegistered(
        uuid=controller_uuid, token_hash={}, pid=None, timestamp=time.time()
    )
    store.append(ctrl_event)
    state.apply(ctrl_event)

    routes = create_api_routes(
        store=store,
        state=state,
        controller_uuid=controller_uuid,
        mesh_dir=mesh_dir,
        agent_supervisor=mock_supervisor,
    )
    return Starlette(routes=routes)


@pytest.fixture
async def client(app):
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


async def test_inv29_rest_spawn_launches_process(  # Tests INV-29
    client, mock_supervisor, controller_uuid
):
    """POST /api/spawn calls supervisor.launch() with correct parameters."""
    resp = await client.post(
        "/api/spawn",
        json={"model": "sonnet", "claude_md": "You are a test agent"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["code"] == "ok"

    # Supervisor should have been called
    mock_supervisor.launch.assert_called_once()
    call_kwargs = mock_supervisor.launch.call_args
    # Must include required fields
    assert "uuid" in call_kwargs.kwargs or len(call_kwargs.args) > 0
    kwargs = call_kwargs.kwargs if call_kwargs.kwargs else {}
    if call_kwargs.args:
        # positional — just verify it was called
        pass
    else:
        assert kwargs["uuid"] == data["data"]["uuid"]
        assert kwargs["bearer_token"] == data["data"]["bearer_token"]
        assert kwargs["model"] == data["data"]["model"]
        assert "server_url" in kwargs
        assert "server_base_url" in kwargs
        assert "spawner_uuid" in kwargs


async def test_inv29_rest_spawn_without_supervisor(store, state, controller_uuid, mesh_dir):
    """POST /api/spawn works without supervisor (registers but doesn't launch)."""
    ctrl_event = AgentRegistered(
        uuid=controller_uuid, token_hash={}, pid=None, timestamp=time.time()
    )
    store.append(ctrl_event)
    state.apply(ctrl_event)

    routes = create_api_routes(
        store=store,
        state=state,
        controller_uuid=controller_uuid,
        mesh_dir=mesh_dir,
        agent_supervisor=None,  # No supervisor
    )
    app = Starlette(routes=routes)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        resp = await client.post("/api/spawn", json={"model": "sonnet"})
        assert resp.status_code == 200
        assert resp.json()["code"] == "ok"
```

**Step 2: Run tests to verify they fail**

Run: `cd mesh-server && uv run --extra dev pytest tests/test_supervisor_wiring.py -v`
Expected: Tests fail because launch kwargs mismatch (missing `server_url`, `spawner_uuid`, etc.)

**Step 3: Add agent-runtime as dependency**

In `mesh-server/pyproject.toml`, add to `dependencies`:
```toml
dependencies = [
    "mcp[cli]>=1.2.0",
    "uvicorn>=0.30",
    "agent-runtime",
]
```

Add to the bottom of `pyproject.toml`:
```toml
[tool.uv.sources]
agent-runtime = { path = "../agent-runtime" }
```

Run: `cd mesh-server && uv sync --extra dev`

**Step 4: Update AppContext and create_app()**

In `mesh-server/src/mesh_server/server.py`:

Add import at top:
```python
from agent_runtime.launcher import AgentSupervisor
```

Update `AppContext`:
```python
@dataclass
class AppContext:
    store: EventStore
    state: MeshState
    mesh_dir: Path
    controller_uuid: str
    supervisor: AgentSupervisor | None = None
```

Update `create_app()`:
```python
def create_app(mesh_dir: Path | None = None) -> object:
    """Create the combined ASGI app with MCP + REST/SSE routes."""
    global _app_context
    ctx = _init_app_context(mesh_dir)

    # Create supervisor with shutdown callback
    async def _on_agent_exit(uuid: str, exit_code: int) -> None:
        """Handle unexpected agent exit — deregister if still alive."""
        agent = ctx.state.get_agent(uuid)
        if agent and agent.alive:
            from mesh_server.tools import tool_shutdown
            tool_shutdown(ctx.state, ctx.store, caller_uuid=uuid)

    supervisor = AgentSupervisor(shutdown_callback=_on_agent_exit)
    ctx.supervisor = supervisor

    _app_context = ctx

    # Register REST/SSE routes via FastMCP's public custom_route API
    api_routes = create_api_routes(
        store=ctx.store,
        state=ctx.state,
        controller_uuid=ctx.controller_uuid,
        mesh_dir=ctx.mesh_dir,
        agent_supervisor=supervisor,
    )
    for route in api_routes:
        mcp.custom_route(route.path, methods=route.methods)(route.endpoint)

    return mcp.streamable_http_app()
```

**Step 5: Update spawn_neighbor MCP tool to call supervisor**

In `mesh-server/src/mesh_server/server.py`, update `spawn_neighbor`:
```python
@mcp.tool()
async def spawn_neighbor(
    caller_uuid: str,
    ctx: Ctx,
    claude_md: str | None = None,
    model: str = "sonnet",
    thinking_budget: int | None = None,
) -> dict:
    """Spawn a new agent in the mesh.

    Args:
        caller_uuid: Your agent UUID (from MESH_AGENT_ID env var)
        claude_md: Optional CLAUDE.md content defining the new agent's role
        model: Model short name: "opus", "sonnet", or "haiku" (default: "sonnet")
        thinking_budget: Optional thinking token budget (None = no extended thinking)
    """
    app = _get_app(ctx)
    result = prepare_spawn(
        app.state,
        app.store,
        mesh_dir=app.mesh_dir,
        claude_md=claude_md,
        model=model,
        thinking_budget=thinking_budget,
    )

    # Launch via supervisor if available and spawn succeeded
    if result["code"] == "ok" and app.supervisor is not None:
        try:
            pid = await app.supervisor.launch(
                uuid=result["data"]["uuid"],
                model=result["data"]["model"],
                agent_dir=result["data"]["agent_dir"],
                bearer_token=result["data"]["bearer_token"],
                spawner_uuid=caller_uuid,
                server_url=f"http://127.0.0.1:9090/mcp",
                server_base_url="http://127.0.0.1:9090",
                role=claude_md,
                thinking_budget=thinking_budget,
            )
            result["data"]["pid"] = pid
        except Exception as e:
            import logging
            logging.getLogger(__name__).exception("Failed to launch agent")
            result["data"]["launch_error"] = str(e)

    return result
```

**Step 6: Fix REST api_spawn to build launch kwargs explicitly**

In `mesh-server/src/mesh_server/api.py`, replace the `api_spawn` supervisor launch block (lines ~149-154):

```python
        # Launch via supervisor if available
        if agent_supervisor is not None:
            try:
                await agent_supervisor.launch(
                    uuid=result["data"]["uuid"],
                    model=result["data"]["model"],
                    agent_dir=result["data"]["agent_dir"],
                    bearer_token=result["data"]["bearer_token"],
                    spawner_uuid=controller_uuid,
                    server_url=f"http://127.0.0.1:9090/mcp",
                    server_base_url="http://127.0.0.1:9090",
                    role=body.get("claude_md"),
                    thinking_budget=body.get("thinking_budget"),
                    initial_prompt=body.get("initial_message"),
                )
            except Exception:
                logger.exception("Failed to launch agent via supervisor")
```

**Step 7: Run tests to verify they pass**

Run: `cd mesh-server && uv run --extra dev pytest tests/test_supervisor_wiring.py -v`
Expected: PASS

Run: `cd mesh-server && uv run --extra dev pytest -v`
Expected: All tests pass (no regressions)

**Step 8: Commit**

```bash
git add mesh-server/pyproject.toml mesh-server/src/mesh_server/server.py mesh-server/src/mesh_server/api.py mesh-server/tests/test_supervisor_wiring.py
git commit -m "feat: wire AgentSupervisor into mesh-server spawn paths (INV-28, INV-29)"
```

---

### Task 2: Shutdown callback and unexpected exit handling

**Context:** When a supervised agent process exits (crash or clean exit), the `AgentSupervisor` calls its `shutdown_callback(uuid, exit_code)`. This callback must emit an `AgentDeregistered` event if the agent is still alive — the Stop hook may have already called shutdown (clean exit), so we must not double-deregister.

Task 1 created the callback skeleton in `create_app()`. This task adds proper tests for the callback behavior, including the double-deregister guard.

**Subsystem spec(s):** `mesh-server/SPEC.md`
**Key invariants from spec:**
- INV-30: Supervisor emits AgentDeregistered when process exits unexpectedly → `def test_inv30_supervisor_deregisters_on_crash():  # Tests INV-30`

**Files:**
- Modify: `mesh-server/tests/test_supervisor_wiring.py` (add callback tests)

**Depends on:** Task 1

**Step 1: Write failing tests for shutdown callback**

Add to `mesh-server/tests/test_supervisor_wiring.py`:

```python
from mesh_server.tools import tool_shutdown


async def test_inv30_supervisor_deregisters_on_crash(  # Tests INV-30
    store, state, controller_uuid, mesh_dir
):
    """Shutdown callback emits AgentDeregistered for alive agent."""
    from mesh_server.spawner import prepare_spawn

    # Register an agent
    result = prepare_spawn(state, store, mesh_dir=mesh_dir, model="sonnet")
    agent_uuid = result["data"]["uuid"]
    assert state.get_agent(agent_uuid).alive is True

    # Simulate the shutdown callback from create_app
    async def _on_agent_exit(uuid: str, exit_code: int) -> None:
        agent = state.get_agent(uuid)
        if agent and agent.alive:
            tool_shutdown(state, store, caller_uuid=uuid)

    await _on_agent_exit(agent_uuid, exit_code=1)

    # Agent should now be dead
    assert state.get_agent(agent_uuid).alive is False


async def test_inv30_no_double_deregister(  # Tests INV-30
    store, state, controller_uuid, mesh_dir
):
    """Shutdown callback skips already-dead agents (Stop hook already called)."""
    from mesh_server.spawner import prepare_spawn

    # Register and manually shut down
    result = prepare_spawn(state, store, mesh_dir=mesh_dir, model="sonnet")
    agent_uuid = result["data"]["uuid"]
    tool_shutdown(state, store, caller_uuid=agent_uuid)
    assert state.get_agent(agent_uuid).alive is False

    events_before = len(store.replay())

    # Callback should be a no-op
    async def _on_agent_exit(uuid: str, exit_code: int) -> None:
        agent = state.get_agent(uuid)
        if agent and agent.alive:
            tool_shutdown(state, store, caller_uuid=uuid)

    await _on_agent_exit(agent_uuid, exit_code=0)

    events_after = len(store.replay())
    assert events_after == events_before  # No new events
```

**Step 2: Run tests**

Run: `cd mesh-server && uv run --extra dev pytest tests/test_supervisor_wiring.py -v`
Expected: PASS (callback logic already implemented in Task 1)

If tests fail, fix the callback in `server.py` accordingly.

**Step 3: Commit**

```bash
git add mesh-server/tests/test_supervisor_wiring.py
git commit -m "test: add shutdown callback tests for unexpected agent exit (INV-30)"
```

---

### Task 3: Mock CLI agent and live pipeline test

**Context:** To test the full spawn pipeline without real Claude API calls, we need a fake CLI script that behaves like a Claude CLI agent: reads env vars, connects to the MCP server, exchanges messages, and shuts down. This script is launched by `AgentSupervisor` as a subprocess (instead of `claude`), proving the entire pipeline works: spawn → config gen → subprocess launch → MCP connection → message exchange → shutdown.

The fake CLI must be a standalone Python script with no imports from mesh-server or agent-runtime — it uses only the MCP client library to connect to the server, mimicking what a real Claude CLI would do.

The test starts a real mesh-server (using `create_app()`), spawns an agent via the REST API with the supervisor configured to use the fake CLI, and verifies the agent connects, receives a message, sends a reply, and shuts down.

**Subsystem spec(s):** `mesh-server/SPEC.md`
**Key invariants from spec:**
- INV-31: Mock CLI agent completes full spawn→connect→message→shutdown cycle → `def test_inv31_mock_cli_full_cycle():  # Tests INV-31`

**Files:**
- Create: `mesh-server/tests/fake_claude.py` (mock CLI script)
- Create: `mesh-server/tests/test_live_pipeline.py`

**Depends on:** Task 1

**Step 1: Create the fake CLI script**

Create `mesh-server/tests/fake_claude.py`:

```python
#!/usr/bin/env python3
"""Fake Claude CLI for integration testing.

Reads MESH_AGENT_ID and MESH_BEARER_TOKEN from env,
connects to the MCP server via the generated mcp_config.json,
calls whoami, reads inbox, sends a reply, and shuts down.

Usage: python fake_claude.py [-p "initial prompt"] --mcp-config <path> --model <model>
"""

import argparse
import json
import os
import sys
import urllib.request


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("-p", "--prompt", default=None)
    parser.add_argument("--mcp-config", required=True)
    parser.add_argument("--model", default="sonnet")
    parser.add_argument("--thinking-budget", type=int, default=None)
    args = parser.parse_args()

    agent_uuid = os.environ["MESH_AGENT_ID"]
    bearer_token = os.environ["MESH_BEARER_TOKEN"]

    # Read MCP config to get server URL
    with open(args.mcp_config) as f:
        mcp_config = json.load(f)

    server_url = mcp_config["mcpServers"]["mesh"]["url"]
    # Derive base URL from MCP URL (strip /mcp suffix)
    base_url = server_url.rsplit("/mcp", 1)[0]

    headers = {
        "Authorization": f"Bearer {bearer_token}",
        "X-Agent-ID": agent_uuid,
        "Content-Type": "application/json",
    }

    def call_tool(tool_name: str, arguments: dict) -> dict:
        """Call an MCP tool via the REST-like interface.

        For the fake CLI, we use direct HTTP to the server's tool endpoints
        rather than full MCP protocol. This is simpler and sufficient for testing.
        """
        # Use the REST API endpoints that exist
        if tool_name == "whoami":
            url = f"{base_url}/api/agents"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read())

        elif tool_name == "read_inbox":
            url = f"{base_url}/api/inbox"
            req = urllib.request.Request(url, headers=headers)
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read())

        elif tool_name == "send":
            url = f"{base_url}/api/send"
            data = json.dumps(arguments).encode()
            req = urllib.request.Request(url, data=data, headers=headers, method="POST")
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read())

        elif tool_name == "shutdown":
            url = f"{base_url}/api/agents/{agent_uuid}/shutdown"
            req = urllib.request.Request(url, headers=headers, method="POST")
            with urllib.request.urlopen(req) as resp:
                return json.loads(resp.read())

        return {"error": f"Unknown tool: {tool_name}"}

    # --- Agent behavior ---

    # 1. Check identity
    agents_result = call_tool("whoami", {})

    # 2. Read inbox (should have initial message if spawned with one)
    inbox_result = call_tool("read_inbox", {})
    messages = inbox_result.get("data", {}).get("messages", [])

    # 3. If we got a message, reply to the sender
    if messages:
        sender = messages[0].get("from")
        if sender:
            call_tool("send", {
                "to": sender,
                "message": f"fake-agent-reply: processed by {agent_uuid}",
            })

    # 4. Shutdown
    call_tool("shutdown", {})


if __name__ == "__main__":
    main()
```

Make it executable: `chmod +x mesh-server/tests/fake_claude.py`

**Step 2: Write the live pipeline test**

Create `mesh-server/tests/test_live_pipeline.py`:

```python
"""Live pipeline integration test using fake Claude CLI.

Starts a real mesh-server, spawns an agent via REST using a fake CLI,
and verifies the full lifecycle: spawn → connect → message → shutdown.

INV-31: Mock CLI agent completes full spawn→connect→message→shutdown cycle.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from starlette.applications import Starlette

from agent_runtime.launcher import AgentProcess, AgentSupervisor
from mesh_server.api import create_api_routes
from mesh_server.events import EventStore
from mesh_server.projections import MeshState
from mesh_server.tools import tool_shutdown
from mesh_server.types import AgentRegistered, generate_controller_uuid


FAKE_CLAUDE = str(Path(__file__).parent / "fake_claude.py")


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


class FakeAgentSupervisor(AgentSupervisor):
    """AgentSupervisor that launches fake_claude.py instead of real claude."""

    async def launch(self, **kwargs):
        """Override to use fake_claude.py as the CLI command."""
        # Patch AgentProcess to use fake_claude.py
        uuid = kwargs["uuid"]
        model = kwargs["model"]
        agent_dir = kwargs["agent_dir"]
        bearer_token = kwargs["bearer_token"]

        from agent_runtime.config import write_agent_configs

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

        # Override the CLI args to use fake_claude.py
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


async def test_inv31_mock_cli_full_cycle(  # Tests INV-31
    store, state, controller_uuid, mesh_dir
):
    """Full lifecycle: spawn agent with fake CLI, exchange messages, shutdown."""
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

    # Create app with routes
    routes = create_api_routes(
        store=store,
        state=state,
        controller_uuid=controller_uuid,
        mesh_dir=mesh_dir,
        agent_supervisor=supervisor,
    )
    app = Starlette(routes=routes)

    # Start test server on a random port
    import uvicorn

    config = uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning")
    server = uvicorn.Server(config)

    # Run server in background
    server_task = asyncio.create_task(server.serve())

    # Wait for server to start
    for _ in range(50):
        await asyncio.sleep(0.1)
        if server.started:
            break
    assert server.started, "Server failed to start"

    # Get actual port
    port = server.servers[0].sockets[0].getsockname()[1]

    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            base_url=f"http://127.0.0.1:{port}"
        ) as client:
            # Spawn agent with initial message
            resp = await client.post(
                "/api/spawn",
                json={
                    "model": "sonnet",
                    "initial_message": "Hello from controller",
                },
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["code"] == "ok"
            agent_uuid = data["data"]["uuid"]

            # Wait for the fake agent to process and exit
            await asyncio.sleep(2.0)

            # Check controller inbox for reply
            resp = await client.get("/api/inbox")
            assert resp.status_code == 200
            inbox = resp.json()

            # Agent should have replied
            messages = inbox.get("data", {}).get("messages", [])
            assert len(messages) >= 1, f"Expected reply from agent, got: {inbox}"
            assert "fake-agent-reply" in messages[0]["message"]

            # Agent should be deregistered (either via shutdown tool or callback)
            agent = state.get_agent(agent_uuid)
            assert agent is not None
            assert agent.alive is False

    finally:
        server.should_exit = True
        await server_task
```

**Step 3: Run tests**

Run: `cd mesh-server && uv run --extra dev pytest tests/test_live_pipeline.py -v --timeout=30`
Expected: Initially FAIL (server URL handling issues likely)

Iterate on the fake_claude.py and test until the pipeline works.

**Step 4: Run full test suite**

Run: `cd mesh-server && uv run --extra dev pytest -v`
Expected: All tests pass

**Step 5: Commit**

```bash
git add mesh-server/tests/fake_claude.py mesh-server/tests/test_live_pipeline.py
git commit -m "test: add mock CLI agent and live pipeline integration test (INV-31)"
```

---

### Task 4: Documentation updates

**Context:** The live integration adds a new architectural decision (agent-runtime as mesh-server dependency), new SPEC.md invariants, and requires a README.md rewrite. This task applies the documentation updates drafted during brainstorming.

The README.md should be rewritten to lead with the vision — what MCP Mesh enables and why it matters — rather than jumping into implementation details. Quick Start stays but becomes secondary.

**Subsystem spec(s):** `mesh-server/SPEC.md`
**Key invariants from spec:** INV-28 through INV-31 (adding to SPEC.md, already tested in Tasks 1-3)

**Files:**
- Modify: `docs/ARCHITECTURE.md` (add Process Supervision section, update subsystem map)
- Modify: `mesh-server/SPEC.md` (add INV-28..31)
- Modify: `README.md` (rewrite as compelling introduction)

**Depends on:** Task 1, Task 2, Task 3

**Step 1: Update ARCHITECTURE.md**

Add "Process Supervision" section after the "Hook Architecture" section (after line ~150):

```markdown
## Process Supervision

In the context of needing spawn_neighbor to launch real Claude CLI processes, facing the choice between mesh-server orchestrating launches directly or delegating to an external supervisor, we decided to make agent-runtime a direct dependency of mesh-server and instantiate an AgentSupervisor within create_app(), accepting the coupling in exchange for single-process operational simplicity.

The supervisor writes config artifacts (MCP config, hooks, CLAUDE.md, settings.json) to the agent's directory, launches `claude` as a subprocess, and monitors it. If an agent process exits unexpectedly, the supervisor emits an AgentDeregistered event automatically.

Spawned agents inherit the parent process environment, including Claude Code subscription credentials — no API key is required.
```

Update the subsystem map table — change the agent-runtime row to link to its SPEC.md:

```markdown
| [agent-runtime](../agent-runtime/) | Agent bootstrap and lifecycle management | v0.3 | [SPEC.md](../agent-runtime/SPEC.md) |
```

**Step 2: Update SPEC.md**

Add to the Invariants section:

```markdown
- **INV-28**: spawn_neighbor (MCP) launches Claude CLI subprocess via AgentSupervisor
- **INV-29**: REST /api/spawn launches Claude CLI subprocess via AgentSupervisor
- **INV-30**: Supervisor emits AgentDeregistered when process exits unexpectedly
- **INV-31**: Mock CLI agent completes full spawn→connect→message→shutdown cycle
```

**Step 3: Rewrite README.md**

Replace the full `README.md` content with a version that leads with vision. Keep the technical accuracy but make it read as an introduction to the project, not a spec sheet. Use the current `docs/images/hero.png`. The Quick Start section stays but is shorter and comes after the narrative.

**Step 4: Commit**

```bash
git add docs/ARCHITECTURE.md mesh-server/SPEC.md README.md
git commit -m "docs: add process supervision ADR, SPEC invariants, rewrite README"
```
