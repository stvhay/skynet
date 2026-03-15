"""Agent spawner: credential generation and directory setup."""

from __future__ import annotations

import time
from pathlib import Path

from mesh_server.auth import generate_token, hash_token
from mesh_server.events import EventStore
from mesh_server.projections import MeshState
from mesh_server.types import AgentRegistered, generate_agent_uuid

MESH_AGENT_PREAMBLE = """\
# Mesh Agent

You are a mesh agent. ALL communication happens via MCP mesh tools.
NEVER prompt the terminal user. NEVER use AskUserQuestion.
Use read_inbox(block=true) when you have no work to do.
Your agent UUID is available in the MESH_AGENT_ID environment variable.
Pass it as caller_uuid when calling mesh tools.
"""


def prepare_spawn(
    state: MeshState,
    store: EventStore,
    *,
    mesh_dir: Path,
    claude_md: str | None = None,
    pid: int | None = None,
) -> dict:
    """Prepare credentials and directory for a new agent.

    Returns a result dict with uuid, bearer_token, and env_vars.
    Does NOT launch a subprocess — caller is responsible for that.
    """
    agent_uuid = generate_agent_uuid()
    raw_token = generate_token()
    token_hash = hash_token(raw_token)

    # Register in event store
    event = AgentRegistered(
        uuid=agent_uuid,
        token_hash=token_hash,
        pid=pid,
        timestamp=time.time(),
    )
    store.append(event)
    state.apply(event)

    # Create agent directory
    agent_dir = mesh_dir / "agents" / agent_uuid
    agent_dir.mkdir(parents=True, exist_ok=True)

    # Write claude.md
    full_claude_md = MESH_AGENT_PREAMBLE
    if claude_md:
        full_claude_md += f"\n---\n\n{claude_md}\n"
    (agent_dir / "claude.md").write_text(full_claude_md)

    env_vars = {
        "MESH_AGENT_ID": agent_uuid,
        "MESH_BEARER_TOKEN": raw_token,
        "MESH_DATA_DIR": str(agent_dir),
    }

    return {
        "code": "ok",
        "data": {
            "uuid": agent_uuid,
            "bearer_token": raw_token,
            "env_vars": env_vars,
        },
        "error": None,
    }
