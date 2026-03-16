"""Shared agent launch helper used by both MCP tools and REST API."""

from __future__ import annotations

import logging

from agent_runtime.launcher import AgentSupervisor

logger = logging.getLogger(__name__)


async def launch_agent(
    supervisor: AgentSupervisor | None,
    spawn_result: dict,
    caller_uuid: str,
    *,
    role: str | None = None,
    thinking_budget: int | None = None,
    initial_prompt: str | None = None,
    server_url: str = "http://127.0.0.1:9090/mcp",
    server_base_url: str = "http://127.0.0.1:9090",
) -> int | None:
    """Launch agent via supervisor.  Returns PID or None on failure.

    If *supervisor* is None or *spawn_result* indicates an error, returns
    None immediately without touching the result dict -- callers decide
    how to surface the failure.
    """
    if supervisor is None or spawn_result.get("code") != "ok":
        return None
    try:
        d = spawn_result["data"]
        return await supervisor.launch(
            uuid=d["uuid"],
            model=d["model"],
            agent_dir=d["agent_dir"],
            bearer_token=d["bearer_token"],
            spawner_uuid=caller_uuid,
            server_url=server_url,
            server_base_url=server_base_url,
            role=role,
            thinking_budget=d.get("thinking_budget"),
            initial_prompt=initial_prompt,
        )
    except Exception:
        logger.exception("Failed to launch agent via supervisor")
        return None
