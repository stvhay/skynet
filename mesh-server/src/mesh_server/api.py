"""REST/SSE API routes for the controller web UI.

These routes call the same tool_* functions as the MCP tools,
mounted on the same Starlette app that FastMCP uses.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
from pathlib import Path
from typing import Any, Protocol

from starlette.requests import Request
from starlette.responses import JSONResponse, Response, StreamingResponse
from starlette.routing import Route

from mesh_server.events import EventStore
from mesh_server.projections import MeshState
from mesh_server.spawner import prepare_spawn
from mesh_server.tools import (
    tool_read_inbox,
    tool_send,
    tool_show_neighbors,
    tool_shutdown,
)

logger = logging.getLogger(__name__)

# Keepalive interval for SSE (seconds)
SSE_KEEPALIVE_SECONDS = 30


class AgentSupervisor(Protocol):
    """Protocol for optional agent supervisor that launches processes."""

    async def launch(self, **kwargs: Any) -> None: ...


def create_api_routes(
    store: EventStore,
    state: MeshState,
    controller_uuid: str,
    mesh_dir: Path,
    agent_supervisor: AgentSupervisor | None = None,
    server_base_url: str = "http://127.0.0.1:9090",
) -> list[Route]:
    """Create REST/SSE API routes.

    Returns a list of Starlette Route objects to be added to the app.
    All routes close over the provided store, state, and controller_uuid.
    """
    # Cache index.html content at startup to avoid blocking reads per request
    static_dir = Path(__file__).parent / "static"
    _index_html = (static_dir / "index.html").read_text()

    async def api_events(request: Request) -> Response:
        """SSE endpoint — stream all events to the controller."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=256)
        store.subscribe(queue)

        async def event_generator():
            try:
                while True:
                    try:
                        event = await asyncio.wait_for(
                            queue.get(), timeout=SSE_KEEPALIVE_SECONDS
                        )
                        data = json.dumps(
                            dataclasses.asdict(event), separators=(",", ":")
                        )
                        yield f"data: {data}\n\n"
                    except asyncio.TimeoutError:
                        # Send keepalive comment
                        yield ": keepalive\n\n"
            except asyncio.CancelledError:
                return
            finally:
                store.unsubscribe(queue)

        return StreamingResponse(
            event_generator(),
            media_type="text/event-stream",
            headers={
                "Cache-Control": "no-cache",
                "Connection": "keep-alive",
                "X-Accel-Buffering": "no",
            },
        )

    async def api_agents(request: Request) -> Response:
        """Return list of all agents as JSON."""
        result = tool_show_neighbors(state, caller_uuid=controller_uuid)
        return JSONResponse(result)

    async def api_send(request: Request) -> Response:
        """Send a message from the controller."""
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Body must be a JSON object")
        except Exception:
            return JSONResponse(
                {"code": "invalid_args", "data": {}, "error": "Invalid JSON body"},
                status_code=400,
            )
        to = body.get("to")
        if not to:
            return JSONResponse(
                {"code": "invalid_args", "data": {}, "error": "Missing 'to' field"},
                status_code=400,
            )
        result = tool_send(
            state,
            store,
            caller_uuid=controller_uuid,
            to=to,
            message=body.get("message"),
            command=body.get("command"),
        )
        if result.get("code") == "not_found":
            return JSONResponse(result, status_code=404)
        return JSONResponse(result)

    async def api_spawn(request: Request) -> Response:
        """Spawn a new agent."""
        try:
            body = await request.json()
            if not isinstance(body, dict):
                raise ValueError("Body must be a JSON object")
        except Exception:
            return JSONResponse(
                {"code": "invalid_args", "data": {}, "error": "Invalid JSON body"},
                status_code=400,
            )
        result = prepare_spawn(
            state,
            store,
            mesh_dir=mesh_dir,
            claude_md=body.get("claude_md"),
            model=body.get("model", "sonnet"),
            thinking_budget=body.get("thinking_budget"),
        )

        if result["code"] != "ok":
            return JSONResponse(result, status_code=400)

        # Launch via supervisor if available
        if agent_supervisor is not None:
            try:
                d = result["data"]
                await agent_supervisor.launch(
                    uuid=d["uuid"],
                    model=d["model"],
                    agent_dir=d["agent_dir"],
                    bearer_token=d["bearer_token"],
                    spawner_uuid=controller_uuid,
                    server_url=f"{server_base_url}/mcp",
                    server_base_url=server_base_url,
                    role=body.get("claude_md"),
                    thinking_budget=d.get("thinking_budget"),
                )
            except Exception:
                logger.exception("Failed to launch agent via supervisor")

        # Auto-send initial_message if provided
        initial_message = body.get("initial_message")
        if initial_message:
            new_uuid = result["data"]["uuid"]
            tool_send(
                state,
                store,
                caller_uuid=controller_uuid,
                to=new_uuid,
                message=initial_message,
            )

        return JSONResponse(result)

    async def api_shutdown_agent(request: Request) -> Response:
        """Shut down a specific agent."""
        target_uuid = request.path_params["uuid"]
        result = tool_shutdown(state, store, caller_uuid=target_uuid)
        if result.get("code") == "not_found":
            return JSONResponse(result, status_code=404)
        return JSONResponse(result)

    async def api_inbox(request: Request) -> Response:
        """Return controller's inbox messages."""
        result = tool_read_inbox(state, store, caller_uuid=controller_uuid)
        return JSONResponse(result)

    async def index(request: Request) -> Response:
        """Serve controller UI from cached index.html."""
        return Response(
            content=_index_html,
            media_type="text/html",
        )

    return [
        Route("/api/events", api_events, methods=["GET"]),
        Route("/api/agents", api_agents, methods=["GET"]),
        Route("/api/send", api_send, methods=["POST"]),
        Route("/api/spawn", api_spawn, methods=["POST"]),
        Route("/api/agents/{uuid}/shutdown", api_shutdown_agent, methods=["POST"]),
        Route("/api/inbox", api_inbox, methods=["GET"]),
        Route("/", index, methods=["GET"]),
    ]
