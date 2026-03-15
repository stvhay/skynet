"""Tests for the agent spawner."""

import time

import pytest

from mesh_server.auth import hash_token, verify_token
from mesh_server.events import EventStore
from mesh_server.projections import MeshState
from mesh_server.spawner import prepare_spawn
from mesh_server.types import AgentRegistered


@pytest.fixture
def store(tmp_path):
    return EventStore(tmp_path / "events.jsonl")


@pytest.fixture
def state():
    return MeshState()


def test_inv16_spawn_creates_agent(state, store, tmp_path):  # Tests INV-16
    """spawn creates agent dir and registers in event store."""
    result = prepare_spawn(
        state,
        store,
        mesh_dir=tmp_path / ".mesh",
        claude_md="You are a test agent.",
    )
    assert result["code"] == "ok"
    uuid = result["data"]["uuid"]

    # Agent should be registered
    agent = state.get_agent(uuid)
    assert agent is not None
    assert agent.alive is True

    # Agent dir should exist with claude.md
    agent_dir = tmp_path / ".mesh" / "agents" / uuid
    assert agent_dir.exists()
    claude_md = (agent_dir / "claude.md").read_text()
    assert "mesh agent" in claude_md.lower()
    assert "You are a test agent." in claude_md


def test_inv17_spawn_generates_credentials(state, store, tmp_path):  # Tests INV-17
    """spawn generates valid bearer token and UUID."""
    result = prepare_spawn(state, store, mesh_dir=tmp_path / ".mesh")
    assert result["code"] == "ok"

    uuid = result["data"]["uuid"]
    token = result["data"]["bearer_token"]
    env_vars = result["data"]["env_vars"]

    # UUID should be valid format
    assert len(uuid) == 36  # UUIDv4 with dashes
    assert env_vars["MESH_AGENT_ID"] == uuid
    assert env_vars["MESH_BEARER_TOKEN"] == token

    # Token should verify against stored hash
    agent = state.get_agent(uuid)
    assert verify_token(token, agent.token_hash) is True


def test_fail4_spawn_duplicate_uuid(state, store, tmp_path):  # Tests FAIL-4
    """After spawn, agent is registered and alive."""
    result1 = prepare_spawn(state, store, mesh_dir=tmp_path / ".mesh")
    assert result1["code"] == "ok"
    uuid = result1["data"]["uuid"]
    agent = state.get_agent(uuid)
    assert agent is not None
    assert agent.alive is True


def test_spawn_without_custom_claude_md(state, store, tmp_path):
    """spawn without custom claude_md still writes preamble."""
    result = prepare_spawn(state, store, mesh_dir=tmp_path / ".mesh")
    uuid = result["data"]["uuid"]
    agent_dir = tmp_path / ".mesh" / "agents" / uuid
    claude_md = (agent_dir / "claude.md").read_text()
    assert "mesh agent" in claude_md.lower()
    assert "NEVER prompt the terminal" in claude_md
