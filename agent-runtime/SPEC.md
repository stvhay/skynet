# agent-runtime Subsystem Specification

## Purpose

Agent bootstrap and lifecycle management for MCP Mesh. Generates configuration artifacts (MCP config, Claude Code hooks, CLAUDE.md, settings.json) and launches Claude CLI processes as mesh agents with supervision.

This package is independently testable and does NOT import from mesh-server.

## Public Interface

### config.py — Configuration Generation

| Function | Description |
|---|---|
| `generate_mcp_config(server_url, agent_uuid, bearer_token)` | Returns MCP config dict with mesh server connection |
| `generate_session_start_hook(agent_uuid, spawner_uuid, model)` | Returns bash script for identity injection |
| `generate_pre_tool_use_hook(agent_uuid)` | Returns bash script for caller_uuid auto-injection |
| `generate_stop_hook(agent_uuid, server_base_url)` | Returns bash script for clean shutdown |
| `generate_claude_md(role)` | Returns CLAUDE.md content with role text only |
| `generate_settings_json(agent_uuid, hooks_dir)` | Returns settings dict with all three hooks |
| `write_agent_configs(agent_dir, ...)` | Writes all config files, returns paths dict |

### launcher.py — Process Management

| Class / Method | Description |
|---|---|
| `AgentProcess(uuid, model, agent_dir, bearer_token, ...)` | Wraps a Claude CLI subprocess |
| `AgentProcess._build_env()` | Build env dict with MESH_* variables |
| `AgentProcess._build_cli_args()` | Build CLI argument list |
| `AgentProcess.start()` | Launch subprocess, return PID |
| `AgentProcess.wait()` | Wait for exit, return code |
| `AgentProcess.pid` | PID property |
| `AgentSupervisor(shutdown_callback)` | Manages multiple agent processes |
| `AgentSupervisor.launch(...)` | Write configs, start process, begin supervision |
| `AgentSupervisor.get_process(uuid)` | Get AgentProcess by UUID |
| `AgentSupervisor.active_agents` | Dict of active UUID -> AgentProcess |

## Invariants

- **INV-1**: MCP config contains correct server URL and auth headers (Authorization: Bearer, X-Agent-ID)
- **INV-2**: SessionStart hook outputs agent UUID, spawner UUID, and tool reference (mcp__mesh__*)
- **INV-3**: CLAUDE.md contains only role text — no mesh protocol instructions
- **INV-4**: Model names translate to correct CLI flags (--model, --thinking-budget when set)
- **INV-5**: PreToolUse hook injects caller_uuid into mesh tool calls (mcp__mesh__* only)
- **INV-6**: Stop hook calls shutdown endpoint (/api/agents/{uuid}/shutdown) with stop_hook_active guard
- **INV-7**: Agent settings.json configures all three hooks (SessionStart, PreToolUse, Stop)
- **INV-8**: Environment variables (MESH_AGENT_ID, MESH_BEARER_TOKEN, MESH_DATA_DIR) are set correctly for subprocess

## Failure Modes

- **FAIL-1**: Invalid model string (empty or None) is rejected with ValueError/TypeError

## Hook Architecture

Three Claude Code hooks are generated per agent:

### SessionStart Hook
- **Purpose**: Identity injection — tells the agent who it is and what tools are available
- **Output**: Multiline preamble with UUID, spawner UUID, model, and mesh tool reference
- **Trigger**: Runs once when Claude CLI session starts

### PreToolUse Hook
- **Purpose**: Auto-inject `caller_uuid` into every mesh tool call
- **Behavior**: Reads stdin JSON, checks if `tool_name` starts with `mcp__mesh__`, outputs `updatedInput` with `caller_uuid` added
- **Trigger**: Runs before every tool invocation

### Stop Hook
- **Purpose**: Clean shutdown — deregister agent from mesh when Claude CLI exits
- **Behavior**: Reads stdin, checks `stop_hook_active` flag (prevents recursion), calls POST to shutdown endpoint
- **Trigger**: Runs when Claude CLI session ends

## Generated Artifacts

Per agent, `write_agent_configs` creates:

```
<agent_dir>/
  mcp_config.json      # MCP server connection config
  CLAUDE.md             # Role-only instructions
  settings.json         # Hook configuration
  hooks/
    session_start.sh    # Identity injection (executable)
    pre_tool_use.sh     # caller_uuid injection (executable)
    stop.sh             # Clean shutdown (executable)
```
