"""MCP server setup with FastMCP, streamable-HTTP transport."""

from __future__ import annotations

import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from mesh_server.api import create_api_routes
from mesh_server.events import EventStore
from mesh_server.projections import MeshState
from mesh_server.spawner import prepare_spawn
from mesh_server.tools import (
    tool_read_inbox_async,
    tool_send,
    tool_show_neighbors,
    tool_shutdown,
    tool_whoami,
)
from mesh_server.types import AgentRegistered, generate_controller_uuid


@dataclass
class AppContext:
    store: EventStore
    state: MeshState
    mesh_dir: Path
    controller_uuid: str


# Module-level shared state — initialized by _init_shared_state() before server starts.
_shared: AppContext | None = None


def _init_shared_state(mesh_dir: Path | None = None) -> AppContext:
    """Create shared store, state, and controller identity.

    Called once before the server starts. The same objects are used by both
    MCP tool handlers (via lifespan context) and REST/SSE API routes.
    """
    global _shared
    if mesh_dir is None:
        mesh_dir = Path(os.environ.get("MESH_DIR", ".mesh"))

    store = EventStore(mesh_dir / "events.jsonl")
    state = MeshState()

    # Replay events to rebuild state
    for event in store.replay():
        state.apply(event)

    # Register controller as an agent in the mesh
    controller_uuid = generate_controller_uuid()
    ctrl_event = AgentRegistered(
        uuid=controller_uuid,
        token_hash={},  # Controller doesn't need token auth
        pid=os.getpid(),
        timestamp=time.time(),
    )
    store.append(ctrl_event)
    state.apply(ctrl_event)

    _shared = AppContext(
        store=store, state=state, mesh_dir=mesh_dir, controller_uuid=controller_uuid
    )
    return _shared


@asynccontextmanager
async def app_lifespan(server: FastMCP):
    """Yield the shared AppContext for MCP tool handlers."""
    if _shared is None:
        raise RuntimeError(
            "Shared state not initialized — call _init_shared_state() first"
        )
    yield _shared


mcp = FastMCP("mesh", lifespan=app_lifespan, json_response=True)

Ctx = Context[ServerSession, AppContext]


def _get_app(ctx: Ctx) -> AppContext:
    return ctx.request_context.lifespan_context


@mcp.tool()
async def whoami(caller_uuid: str, ctx: Ctx) -> dict:
    """Return your UUID and current neighbor count.

    Args:
        caller_uuid: Your agent UUID (from MESH_AGENT_ID env var)
    """
    app = _get_app(ctx)
    return tool_whoami(app.state, caller_uuid=caller_uuid)


@mcp.tool()
async def send(
    caller_uuid: str,
    to: str,
    ctx: Ctx,
    message: str | None = None,
    command: str | None = None,
) -> dict:
    """Send a message to another agent or broadcast.

    Args:
        caller_uuid: Your agent UUID (from MESH_AGENT_ID env var)
        to: Recipient UUID, or "00000000-0000-0000-0000-000000000000" for broadcast
        message: Free-form message text
        command: Optional structured command string
    """
    app = _get_app(ctx)
    agent = app.state.get_agent(caller_uuid)
    if not agent or not agent.alive:
        return {"code": "unauthorized", "data": {}, "error": "Agent not registered"}
    return tool_send(
        app.state,
        app.store,
        caller_uuid=caller_uuid,
        to=to,
        message=message,
        command=command,
    )


@mcp.tool()
async def read_inbox(
    caller_uuid: str,
    ctx: Ctx,
    block: bool = False,
) -> dict:
    """Read and drain your inbox.

    Args:
        caller_uuid: Your agent UUID (from MESH_AGENT_ID env var)
        block: If true, wait indefinitely until a message arrives (yield/idle)
    """
    app = _get_app(ctx)
    return await tool_read_inbox_async(
        app.state,
        app.store,
        caller_uuid=caller_uuid,
        block=block,
    )


@mcp.tool()
async def show_neighbors(caller_uuid: str, ctx: Ctx) -> dict:
    """List all registered agents with their status.

    Args:
        caller_uuid: Your agent UUID (from MESH_AGENT_ID env var)
    """
    app = _get_app(ctx)
    return tool_show_neighbors(app.state, caller_uuid=caller_uuid)


@mcp.tool()
async def shutdown(caller_uuid: str, ctx: Ctx) -> dict:
    """Self-terminate. Deregisters from the mesh and stops this agent.

    Args:
        caller_uuid: Your agent UUID (from MESH_AGENT_ID env var)
    """
    app = _get_app(ctx)
    return tool_shutdown(app.state, app.store, caller_uuid=caller_uuid)


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
    return result


def create_app(mesh_dir: Path | None = None) -> object:
    """Create the combined ASGI app with MCP + REST/SSE routes.

    Initializes shared state, registers API routes on FastMCP's Starlette app,
    and returns the Starlette application.
    """
    ctx = _init_shared_state(mesh_dir)

    # Add REST/SSE routes to FastMCP's Starlette app
    api_routes = create_api_routes(
        store=ctx.store,
        state=ctx.state,
        controller_uuid=ctx.controller_uuid,
        mesh_dir=ctx.mesh_dir,
    )
    mcp._custom_starlette_routes.clear()
    mcp._custom_starlette_routes.extend(api_routes)

    return mcp.streamable_http_app()


def run_server(host: str = "127.0.0.1", port: int = 9090) -> None:
    """Start the MCP mesh server with REST/SSE API."""
    import uvicorn

    app = create_app()
    config = uvicorn.Config(app, host=host, port=port, log_level="info")
    server = uvicorn.Server(config)

    import anyio

    anyio.run(server.serve)


if __name__ == "__main__":
    run_server()
