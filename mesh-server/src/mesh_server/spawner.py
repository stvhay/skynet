"""Agent spawner: credential generation and directory setup."""

from __future__ import annotations

import time
from pathlib import Path

from mesh_server.auth import generate_token, hash_token
from mesh_server.events import EventStore
from mesh_server.projections import MeshState
from mesh_server.types import AgentRegistered, generate_agent_uuid

MODEL_MAP: dict[str, str] = {
    "opus": "claude-opus-4-6",
    "sonnet": "claude-sonnet-4-6",
    "haiku": "claude-haiku-4-5-20251001",
}


def validate_model(model: str) -> str | None:
    """Validate a model short name. Returns full model ID or None if invalid."""
    return MODEL_MAP.get(model)


def prepare_spawn(
    state: MeshState,
    store: EventStore,
    *,
    mesh_dir: Path,
    claude_md: str | None = None,
    pid: int | None = None,
    model: str = "sonnet",
    thinking_budget: int | None = None,
) -> dict:
    """Prepare credentials and directory for a new agent.

    Returns a result dict with uuid, bearer_token, env_vars, model,
    thinking_budget, and agent_dir.
    Does NOT launch a subprocess — caller is responsible for that.
    """
    # Validate model
    full_model_id = validate_model(model)
    if full_model_id is None:
        valid = ", ".join(sorted(MODEL_MAP.keys()))
        return {
            "code": "invalid_args",
            "data": {},
            "error": f"Invalid model '{model}'. Valid models: {valid}",
        }

    # Validate thinking_budget
    if thinking_budget is not None and thinking_budget < 1024:
        return {
            "code": "invalid_args",
            "data": {},
            "error": f"thinking_budget must be >= 1024, got {thinking_budget}",
        }

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

    # Write CLAUDE.md (role-only; mesh behavior injected via hooks in agent-runtime)
    role_text = claude_md or "General-purpose mesh agent."
    (agent_dir / "CLAUDE.md").write_text(f"# Agent Role\n\n{role_text}\n")

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
            "model": full_model_id,
            "thinking_budget": thinking_budget,
            "agent_dir": str(agent_dir),
        },
        "error": None,
    }
