"""Agent configuration generation — MCP config, hooks, CLAUDE.md, settings."""

import json
import os
import stat

DEFAULT_ROLE = "You are a mesh agent. Follow instructions from your spawner and collaborate with other agents."


def generate_mcp_config(server_url: str, agent_uuid: str, bearer_token: str) -> dict:
    """Generate MCP config dict with mesh server connection details.

    INV-1: Config contains correct server URL and auth headers.
    """
    return {
        "mcpServers": {
            "mesh": {
                "type": "http",
                "url": server_url,
                "headers": {
                    "Authorization": f"Bearer {bearer_token}",
                    "X-Agent-ID": agent_uuid,
                },
            }
        }
    }


def generate_session_start_hook(agent_uuid: str, spawner_uuid: str, model: str) -> str:
    """Generate SessionStart hook bash script.

    INV-2: Outputs agent UUID, spawner UUID, and tool reference.
    """
    return f"""#!/usr/bin/env bash
# SessionStart hook — identity injection for agent {agent_uuid}
cat <<'PREAMBLE'
## Mesh Agent Identity

You are a mesh agent in the MCP Mesh network.

- **Your UUID:** {agent_uuid}
- **Spawner UUID:** {spawner_uuid}
- **Model:** {model}

## Available Mesh Tools

Use these MCP tools to communicate with the mesh:

- `mcp__mesh__whoami` — Returns your UUID and neighbor count
- `mcp__mesh__send` — Send a message to another agent or broadcast
- `mcp__mesh__read_inbox` — Read messages from your inbox (use block=true when idle)
- `mcp__mesh__show_neighbors` — List all registered agents
- `mcp__mesh__spawn_neighbor` — Spawn a new agent into the mesh
- `mcp__mesh__shutdown` — Cleanly deregister from the mesh

## Protocol

1. Your `caller_uuid` is automatically injected into mesh tool calls.
2. Always check your inbox regularly with `mcp__mesh__read_inbox(block=true)`.
3. Respond to messages promptly.
4. Call `mcp__mesh__shutdown` before exiting.
PREAMBLE
"""


def generate_pre_tool_use_hook(agent_uuid: str) -> str:
    """Generate PreToolUse hook bash script.

    INV-5: Injects caller_uuid into mesh tool calls.
    Uses JSON-safe escaping for agent_uuid to prevent injection.
    """
    # JSON-encode the UUID to safely embed in the Python string literal
    safe_uuid = json.dumps(agent_uuid)  # e.g. '"abc-123"'
    return f"""#!/usr/bin/env bash
# PreToolUse hook — auto-inject caller_uuid for agent {agent_uuid}

# Read the hook input from stdin
input=$(cat)

# Use python3 for JSON processing (no jq dependency)
echo "$input" | python3 -c "
import sys, json
data = json.load(sys.stdin)
tool_name = data.get('tool_name', '')
if tool_name.startswith('mcp__mesh__'):
    tool_input = data.get('tool_input', {{}})
    tool_input['caller_uuid'] = {safe_uuid}
    print(json.dumps({{'decision': 'allow', 'updatedInput': tool_input}}))
else:
    print(json.dumps({{'hookSpecificOutput': {{'hookEventName': 'PreToolUse', 'permissionDecision': 'allow'}}}}))
"
"""


def generate_stop_hook(agent_uuid: str, server_base_url: str) -> str:
    """Generate Stop hook bash script.

    INV-6: Calls shutdown endpoint on agent stop.
    Uses python3 for JSON parsing (no jq dependency).
    """
    return f"""#!/usr/bin/env bash
# Stop hook — clean shutdown for agent {agent_uuid}
input=$(cat -)
stop_hook_active=$(echo "$input" | python3 -c "import sys,json; print(json.load(sys.stdin).get('stop_hook_active', False))" 2>/dev/null)

if [[ "$stop_hook_active" == "True" ]]; then
    exit 0
fi

curl -s -X POST "{server_base_url}/api/agents/{agent_uuid}/shutdown" >/dev/null 2>&1 || true
"""


def generate_claude_md(role: str | None) -> str:
    """Generate CLAUDE.md with role text only.

    INV-3: Contains only role text, no mesh instructions.
    """
    if role is None:
        role = DEFAULT_ROLE
    return f"# Agent Role\n\n{role}\n"


def generate_settings_json(hooks_dir: str) -> dict:
    """Generate settings.json with hooks and auto-approved mesh tools.

    INV-7: Settings configures SessionStart, PreToolUse, and Stop hooks.
    """
    return {
        "permissions": {
            "allow": [
                "mcp__mesh__whoami",
                "mcp__mesh__send",
                "mcp__mesh__read_inbox",
                "mcp__mesh__show_neighbors",
                "mcp__mesh__spawn_neighbor",
                "mcp__mesh__shutdown",
            ],
        },
        "hooks": {
            "SessionStart": [
                {
                    "type": "command",
                    "command": os.path.join(hooks_dir, "session_start.sh"),
                }
            ],
            "PreToolUse": [
                {
                    "type": "command",
                    "command": os.path.join(hooks_dir, "pre_tool_use.sh"),
                }
            ],
            "Stop": [
                {
                    "type": "command",
                    "command": os.path.join(hooks_dir, "stop.sh"),
                }
            ],
        },
    }


def write_agent_configs(
    agent_dir: str,
    agent_uuid: str,
    spawner_uuid: str,
    bearer_token: str,
    model: str,
    server_url: str,
    server_base_url: str,
    role: str | None,
) -> dict:
    """Write all agent config files to agent_dir.

    Returns dict of paths: mcp_config, claude_md, settings_json, hooks_dir.
    """
    agent_dir = os.path.abspath(agent_dir)
    os.makedirs(agent_dir, exist_ok=True)

    # Hooks directory
    hooks_dir = os.path.join(agent_dir, "hooks")
    os.makedirs(hooks_dir, exist_ok=True)

    # MCP config
    mcp_config_path = os.path.join(agent_dir, "mcp_config.json")
    config = generate_mcp_config(server_url, agent_uuid, bearer_token)
    with open(mcp_config_path, "w") as f:
        json.dump(config, f, indent=2)

    # CLAUDE.md
    claude_md_path = os.path.join(agent_dir, "CLAUDE.md")
    md = generate_claude_md(role)
    with open(claude_md_path, "w") as f:
        f.write(md)

    # Hook scripts
    hooks = {
        "session_start.sh": generate_session_start_hook(
            agent_uuid, spawner_uuid, model
        ),
        "pre_tool_use.sh": generate_pre_tool_use_hook(agent_uuid),
        "stop.sh": generate_stop_hook(agent_uuid, server_base_url),
    }
    for filename, script in hooks.items():
        path = os.path.join(hooks_dir, filename)
        with open(path, "w") as f:
            f.write(script)
        os.chmod(
            path,
            stat.S_IRWXU | stat.S_IRGRP | stat.S_IXGRP | stat.S_IROTH | stat.S_IXOTH,
        )

    # Settings JSON — placed in .claude/ so Claude CLI picks it up as project settings
    claude_dir = os.path.join(agent_dir, ".claude")
    os.makedirs(claude_dir, exist_ok=True)
    settings_path = os.path.join(claude_dir, "settings.json")
    settings = generate_settings_json(hooks_dir)
    with open(settings_path, "w") as f:
        json.dump(settings, f, indent=2)

    return {
        "mcp_config": mcp_config_path,
        "claude_md": claude_md_path,
        "settings_json": settings_path,
        "hooks_dir": hooks_dir,
    }
