"""Tests for the agent spawner."""

import pytest

from mesh_server.auth import verify_token
from mesh_server.events import EventStore
from mesh_server.projections import MeshState
from mesh_server.spawner import MODEL_MAP, prepare_spawn


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

    # Agent dir should exist with CLAUDE.md (role-only)
    agent_dir = tmp_path / ".mesh" / "agents" / uuid
    assert agent_dir.exists()
    claude_md = (agent_dir / "CLAUDE.md").read_text()
    assert "Agent Role" in claude_md
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
    """spawn without custom claude_md writes role-only CLAUDE.md with default role."""
    result = prepare_spawn(state, store, mesh_dir=tmp_path / ".mesh")
    uuid = result["data"]["uuid"]
    agent_dir = tmp_path / ".mesh" / "agents" / uuid
    claude_md = (agent_dir / "CLAUDE.md").read_text()
    assert "Agent Role" in claude_md
    assert "General-purpose mesh agent." in claude_md


# --- Model and thinking_budget tests ---


def test_model_mapping():
    """MODEL_MAP contains expected short names and full IDs."""
    assert "opus" in MODEL_MAP
    assert "sonnet" in MODEL_MAP
    assert "haiku" in MODEL_MAP
    assert MODEL_MAP["opus"] == "claude-opus-4-6"
    assert MODEL_MAP["sonnet"] == "claude-sonnet-4-6"
    assert MODEL_MAP["haiku"] == "claude-haiku-4-5-20251001"


def test_inv20_spawn_default_model(state, store, tmp_path):
    """INV-20: spawn_neighbor defaults to sonnet model."""
    result = prepare_spawn(state, store, mesh_dir=tmp_path / ".mesh")
    assert result["code"] == "ok"
    assert result["data"]["model"] == "claude-sonnet-4-6"
    assert result["data"]["thinking_budget"] is None


def test_inv20_spawn_model_param(state, store, tmp_path):
    """INV-20: spawn_neighbor accepts model parameter."""
    result = prepare_spawn(state, store, mesh_dir=tmp_path / ".mesh", model="opus")
    assert result["code"] == "ok"
    assert result["data"]["model"] == "claude-opus-4-6"


def test_inv20_spawn_thinking_budget(state, store, tmp_path):
    """INV-20: spawn_neighbor accepts thinking_budget parameter."""
    result = prepare_spawn(
        state, store, mesh_dir=tmp_path / ".mesh", model="sonnet", thinking_budget=8000
    )
    assert result["code"] == "ok"
    assert result["data"]["thinking_budget"] == 8000
    assert result["data"]["model"] == "claude-sonnet-4-6"


def test_inv20_spawn_no_thinking(state, store, tmp_path):
    """INV-20: spawn_neighbor with no thinking_budget returns None."""
    result = prepare_spawn(state, store, mesh_dir=tmp_path / ".mesh", model="haiku")
    assert result["code"] == "ok"
    assert result["data"]["thinking_budget"] is None


def test_fail5_invalid_model(state, store, tmp_path):
    """FAIL-5: Invalid model string returns error."""
    result = prepare_spawn(state, store, mesh_dir=tmp_path / ".mesh", model="gpt-4")
    assert result["code"] == "invalid_args"
    assert result["error"] is not None
    assert "model" in result["error"].lower()


def test_fail6_invalid_thinking_budget(tmp_path, store, state):
    """thinking_budget below minimum is rejected."""
    result = prepare_spawn(state, store, mesh_dir=tmp_path, thinking_budget=100)
    assert result["code"] == "invalid_args"
    assert "1024" in result["error"]


def test_inv20_spawn_returns_agent_dir(state, store, tmp_path):
    """INV-20: spawn result includes agent_dir path."""
    result = prepare_spawn(state, store, mesh_dir=tmp_path / ".mesh")
    assert result["code"] == "ok"
    assert "agent_dir" in result["data"]
    uuid = result["data"]["uuid"]
    assert result["data"]["agent_dir"] == str(tmp_path / ".mesh" / "agents" / uuid)


def test_inv20_spawn_claude_md_role_only(state, store, tmp_path):
    """INV-20: CLAUDE.md contains role only, no mesh preamble."""
    result = prepare_spawn(
        state, store, mesh_dir=tmp_path / ".mesh", claude_md="You are a code reviewer."
    )
    uuid = result["data"]["uuid"]
    agent_dir = tmp_path / ".mesh" / "agents" / uuid
    claude_md = (agent_dir / "CLAUDE.md").read_text()
    assert "# Agent Role" in claude_md
    assert "You are a code reviewer." in claude_md
    # Should NOT contain the old mesh preamble
    assert "NEVER prompt the terminal" not in claude_md
