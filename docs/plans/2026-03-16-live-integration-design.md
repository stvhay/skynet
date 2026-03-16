# Design: Live Integration

**Issue:** #10 — Live integration: launch real Claude CLI agents through mesh
**Beads:** skynet-5tj
**Date:** 2026-03-16
**Branch:** feature/10-live-integration

## Problem

`spawn_neighbor` and `/api/spawn` register agents in the event store and create credentials, but never launch a real Claude CLI process. The `AgentSupervisor` in agent-runtime is fully implemented but not wired into mesh-server. The system works end-to-end with mock agents in tests but cannot run real agents.

## Decision

Make agent-runtime a direct dependency of mesh-server. Instantiate `AgentSupervisor` in `create_app()` and pass it to both MCP tool handlers and REST API routes. Both `spawn_neighbor` (MCP) and `/api/spawn` (REST) will launch real Claude CLI subprocesses.

Agents inherit the parent environment's Claude Code subscription — no Anthropic API key is required.

## Architecture

```
create_app()
  ├── _init_app_context()     → store, state, controller_uuid
  ├── AgentSupervisor(shutdown_callback=_on_agent_exit)
  ├── create_api_routes(..., agent_supervisor=supervisor)  # already accepts it
  └── AppContext gains supervisor field → MCP tools access it
```

### Spawn Flow

```
spawn request (MCP or REST)
  → prepare_spawn() registers agent, creates creds, returns data
  → supervisor.launch() writes configs via agent-runtime, starts Claude CLI
  → Claude CLI connects back to mesh-server via MCP (streamable-HTTP)
  → SessionStart hook fires, agent gets identity preamble
  → Agent calls read_inbox(block=true), waits for work
  → Controller/spawner sends initial_message → agent wakes up
```

### Shutdown Callback

When a supervised process exits (clean or crash), the supervisor calls `_on_agent_exit(uuid, exit_code)` which emits `AgentDeregistered` if the agent is still alive in the registry (prevents double-deregister if the Stop hook already called shutdown).

## Components

### mesh-server changes

1. `AppContext` adds `supervisor: AgentSupervisor | None` field
2. `create_app()` creates supervisor with shutdown callback, stores in AppContext
3. `spawn_neighbor` MCP tool calls `supervisor.launch()` after `prepare_spawn()`
4. `api.py` already calls `supervisor.launch()` — just needs the supervisor passed in (already wired via parameter)
5. `pyproject.toml` adds `agent-runtime` as path dependency
6. Shutdown callback: emit `AgentDeregistered` when process exits unexpectedly

### Parameter alignment

`prepare_spawn()` returns `{uuid, bearer_token, env_vars, model, thinking_budget, agent_dir}`.

`AgentSupervisor.launch()` additionally needs: `spawner_uuid`, `server_url`, `server_base_url`, `role`.

These are caller-supplied from runtime config (server URL depends on how the server is started). The caller (MCP tool or REST handler) provides them.

### No changes to agent-runtime

The package is already complete. All changes are in mesh-server.

## Testing

### Mock CLI (CI)

A `fake_claude.py` script that:
1. Reads `MESH_AGENT_ID` and `MESH_BEARER_TOKEN` from env
2. Parses its `mcp_config.json` for the server URL
3. Connects to the MCP server, calls `whoami`
4. Calls `read_inbox`, sends a reply to the spawner
5. Calls `shutdown`, exits cleanly

Tests the full pipeline without API costs: spawn → config gen → subprocess → MCP connection → message exchange → shutdown.

### Real Claude (manual smoke test)

A script that starts the server and spawns a haiku agent with a simple task. Developer runs manually. Not in CI.

## Error Handling

- **Claude CLI not found:** `AgentProcess.start()` raises `FileNotFoundError` → catch, deregister, return error
- **Agent crashes:** Supervisor detects exit, calls shutdown callback → `AgentDeregistered` emitted
- **MCP connection failure:** Agent can't reach server → CLI exits → supervisor handles as crash
- **Duplicate spawn:** Prevented by UUIDv4 uniqueness

## Documentation Updates

### docs/ARCHITECTURE.md

Add "Process Supervision" section after Hook Architecture:

> In the context of needing spawn_neighbor to launch real Claude CLI processes, facing the choice between mesh-server orchestrating launches directly or delegating to an external supervisor, we decided to make agent-runtime a direct dependency of mesh-server and instantiate an AgentSupervisor within create_app(), accepting the coupling in exchange for single-process operational simplicity.
>
> The supervisor writes config artifacts (MCP config, hooks, CLAUDE.md, settings.json) to the agent's directory, launches `claude` as a subprocess, and monitors it. If an agent process exits unexpectedly, the supervisor emits an AgentDeregistered event automatically.
>
> Spawned agents inherit the parent process environment, including Claude Code subscription credentials — no API key is required.

Update subsystem map: agent-runtime row links to `[SPEC.md](../agent-runtime/SPEC.md)`.

### mesh-server/SPEC.md

Add invariants:
- **INV-28**: spawn_neighbor (MCP) launches Claude CLI subprocess via AgentSupervisor
- **INV-29**: REST /api/spawn launches Claude CLI subprocess via AgentSupervisor
- **INV-30**: Supervisor emits AgentDeregistered when process exits unexpectedly
- **INV-31**: Mock CLI agent completes full spawn→connect→message→shutdown cycle

### README.md

Rewrite as a more compelling introduction — lead with the vision and what's possible, reduce implementation details. Keep Quick Start but make it secondary to the narrative.
