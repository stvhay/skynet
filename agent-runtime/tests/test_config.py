"""Tests for agent_runtime.config — INV-1 through INV-7."""

import json
import os
import tempfile

from agent_runtime.config import (
    generate_claude_md,
    generate_mcp_config,
    generate_pre_tool_use_hook,
    generate_session_start_hook,
    generate_settings_json,
    generate_stop_hook,
    write_agent_configs,
)


AGENT_UUID = "abcd1234-0000-0000-0000-000000000001"
SPAWNER_UUID = "abcd1234-0000-0000-0000-000000000002"
SERVER_URL = "http://localhost:8080/mcp"
SERVER_BASE_URL = "http://localhost:8080"
BEARER_TOKEN = "secret-token-123"
MODEL = "sonnet"


class TestInv1McpConfigGeneration:
    """INV-1: MCP config contains correct server URL and auth headers."""

    def test_inv1_mcp_config_generation(self):
        config = generate_mcp_config(SERVER_URL, AGENT_UUID, BEARER_TOKEN)

        assert "mcpServers" in config
        mesh = config["mcpServers"]["mesh"]
        assert mesh["type"] == "http"
        assert mesh["url"] == SERVER_URL
        assert mesh["headers"]["Authorization"] == f"Bearer {BEARER_TOKEN}"
        assert mesh["headers"]["X-Agent-ID"] == AGENT_UUID


class TestInv2SessionStartHook:
    """INV-2: SessionStart hook outputs agent UUID, spawner UUID, and tool reference."""

    def test_inv2_session_start_hook(self):
        script = generate_session_start_hook(AGENT_UUID, SPAWNER_UUID, MODEL)

        assert AGENT_UUID in script
        assert SPAWNER_UUID in script
        # Should reference mesh tools
        assert "mcp__mesh__" in script
        # Should be a bash script
        assert script.startswith("#!/bin/bash") or script.startswith(
            "#!/usr/bin/env bash"
        )


class TestInv3ClaudeMd:
    """INV-3: CLAUDE.md contains only role text."""

    def test_inv3_claude_md_role_only(self):
        role = "You are a code reviewer specializing in Python."
        md = generate_claude_md(role)

        assert "# Agent Role" in md
        assert role in md
        # Should NOT contain mesh instructions
        assert "mcp__mesh__" not in md
        assert "caller_uuid" not in md

    def test_inv3_claude_md_default_role(self):
        md = generate_claude_md(None)

        assert "# Agent Role" in md
        # Should have some default text
        assert len(md.strip()) > len("# Agent Role")


class TestInv5PreToolUseHook:
    """INV-5: PreToolUse hook injects caller_uuid into mesh tool calls."""

    def test_inv5_pre_tool_use_hook(self):
        script = generate_pre_tool_use_hook(AGENT_UUID)

        assert AGENT_UUID in script
        assert "mcp__mesh__" in script
        assert "updatedInput" in script
        assert "caller_uuid" in script
        assert script.startswith("#!/bin/bash") or script.startswith(
            "#!/usr/bin/env bash"
        )


class TestInv6StopHook:
    """INV-6: Stop hook calls shutdown endpoint."""

    def test_inv6_stop_hook(self):
        script = generate_stop_hook(AGENT_UUID, SERVER_BASE_URL)

        assert AGENT_UUID in script
        assert f"{SERVER_BASE_URL}/api/agents/{AGENT_UUID}/shutdown" in script
        assert "stop_hook_active" in script
        assert script.startswith("#!/bin/bash") or script.startswith(
            "#!/usr/bin/env bash"
        )


class TestInv7SettingsJson:
    """INV-7: Agent settings.json configures all three hooks."""

    def test_inv7_settings_json(self):
        hooks_dir = "/tmp/test-hooks"
        settings = generate_settings_json(hooks_dir)

        assert "hooks" in settings
        hooks = settings["hooks"]

        # All three hook types must be present
        assert "SessionStart" in hooks
        assert "PreToolUse" in hooks
        assert "Stop" in hooks

        # Each hook should have a command entry
        for hook_type in ("SessionStart", "PreToolUse", "Stop"):
            hook_list = hooks[hook_type]
            assert isinstance(hook_list, list)
            assert len(hook_list) > 0
            entry = hook_list[0]
            assert "type" in entry
            assert "command" in entry


class TestWriteAgentConfigs:
    """Integration: write_agent_configs writes all files correctly."""

    def test_write_agent_configs(self):
        with tempfile.TemporaryDirectory() as agent_dir:
            paths = write_agent_configs(
                agent_dir=agent_dir,
                agent_uuid=AGENT_UUID,
                spawner_uuid=SPAWNER_UUID,
                bearer_token=BEARER_TOKEN,
                model=MODEL,
                server_url=SERVER_URL,
                server_base_url=SERVER_BASE_URL,
                role="Test role",
            )

            # All expected files should exist
            assert os.path.isfile(paths["mcp_config"])
            assert os.path.isfile(paths["claude_md"])
            assert os.path.isfile(paths["settings_json"])
            assert os.path.isdir(paths["hooks_dir"])

            # MCP config is valid JSON
            with open(paths["mcp_config"]) as f:
                config = json.load(f)
            assert "mcpServers" in config

            # CLAUDE.md has role
            with open(paths["claude_md"]) as f:
                md = f.read()
            assert "Test role" in md

            # settings.json is valid JSON with hooks
            with open(paths["settings_json"]) as f:
                settings = json.load(f)
            assert "hooks" in settings

            # Hook scripts exist and are executable
            hooks_dir = paths["hooks_dir"]
            for hook_file in os.listdir(hooks_dir):
                hook_path = os.path.join(hooks_dir, hook_file)
                assert os.access(hook_path, os.X_OK)
