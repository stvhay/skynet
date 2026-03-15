# Design: MCP Mesh Server v0.1

**Issue:** None (gh CLI unavailable — create issue before implementation)
**Beads:** None (bd unavailable)
**Date:** 2026-03-15
**Branch:** main (worktree to be created before implementation)

## Summary

Minimal MCP mesh server: an event-sourced MCP server that enables multiple Claude CLI instances to communicate as peers through a shared message-passing system. v0.1 proves the core loop — agents register, exchange messages, and yield when idle.

## Architecture

Single Python process running an MCP server over SSE transport. All state changes are events written to an append-only log. In-memory projections provide fast queries and blocking coordination.

### Components

- **Event store**: Append-only JSONL log (`.mesh/events.jsonl`). Source of truth. Replayed on startup to rebuild state.
- **Projections**: In-memory dicts derived from events — agent registry, inbox queues, waiter coordination.
- **MCP tools**: 6 tools exposed via MCP SSE transport (`whoami`, `send`, `read_inbox`, `show_neighbors`, `spawn_neighbor`, `shutdown`).
- **Auth**: Bearer token per agent, scrypt-hashed (scheme field for upgrade path).
- **Spawner**: Generates identity (UUID, token, RSA keypair stub), launches `claude` subprocess with env vars.

### Agent Identity

Each agent receives three environment variables at spawn:

1. `MESH_BEARER_TOKEN` — secret, used in `Authorization` header to authenticate to MCP server
2. `MESH_AGENT_ID` — public UUIDv4, the agent's address on the mesh
3. `MESH_PRIVATE_KEY` — RSA private key (future use, stored but not verified in v0.1)

All agents share identical `.mcp.json` config. Identity is passed via HTTP headers, resolved from env vars.

### Event Model

```
AgentRegistered(uuid, token_hash, pid, timestamp)
AgentDeregistered(uuid, reason, timestamp)       # reason: self_shutdown | controller_kill | connection_lost
MessageEnqueued(id, from_uuid, to_uuid, command?, message?, timestamp)
MessageDrained(message_id, by_uuid, timestamp)
```

Events are written with `file.write() + flush() + fsync()`. Incomplete trailing lines are skipped on replay.

### Token Security

- `hashlib.scrypt(token, salt, n=2**14, r=8, p=1, dklen=32)`
- Stored as `{scheme: "scrypt", salt, hash, n, r, p}`
- Scheme field enables future upgrade (argon2, KDF-derived, RSA-signed)

### UUID Scheme (Prefix-Based Identity)

Peer type is encoded in the UUID prefix — inspectable without lookup:

```
00000000-0000-0000-0000-000000000000  →  broadcast ("all")
ffffffff-XXXX-XXXX-XXXX-XXXXXXXXXXXX  →  controller (prefix ffffffff-)
XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX  →  agent (any other prefix)
```

- **Broadcast**: nil UUID, well-known constant
- **Controller**: UUIDv4 with first group forced to `ffffffff`
- **Agent**: UUIDv4, regenerated if prefix collides with `00000000` or `ffffffff` (~1 in 4B chance)
- `uuid_kind(uuid) → "broadcast" | "controller" | "agent"` — classify any UUID by prefix

### Addressing

- Agent-to-agent: full UUID in `to` field
- Broadcast: nil UUID (`00000000-0000-0000-0000-000000000000`) — fans out to all registered agents
- Controller: any UUID with `ffffffff-` prefix (privileged peer, v0.2)
- BCC is explicitly not supported — `to` field is transparent (recipients need UUIDs for XOR channel derivation)

### Tool API

| Tool | Args | Returns | Events |
|---|---|---|---|
| `whoami()` | — | `{uuid, neighbors_count}` | — |
| `read_inbox(block)` | `block: bool` | `Message[]` | `MessageDrained` per msg |
| `send(to, message, command?)` | `to: str\|str[]`, `message`, `command?` | `{code, delivered_to}` | `MessageEnqueued` per recipient |
| `spawn_neighbor(claude_md?)` | `claude_md?: str` | `{code, uuid}` | `AgentRegistered` |
| `show_neighbors()` | — | `Neighbor[]` | — |
| `shutdown()` | — | `{code}` | `AgentDeregistered` |

Tool results use structured error codes: `ok`, `not_found`, `unauthorized`, `invalid_args`, `queue_full`.

### read_inbox behavior

- `block=false`: Drain and return all queued messages immediately (may be empty).
- `block=true`: True yield — hold MCP tool call open indefinitely until a message arrives. No timeout. Agent lifecycle: RUNNING → IDLE → RUNNING.
- Inbox auto-empties on read. Agent-side hook writes received messages to local `received.jsonl`.

### spawn_neighbor behavior

1. Generate UUIDv4, bearer token (32-byte hex), RSA keypair
2. Write `AgentRegistered` event
3. Create `.mesh/agents/<uuid>/` directory
4. Write `.mesh/agents/<uuid>/claude.md` with mesh agent preamble + custom instructions
5. Launch `claude` subprocess with `MESH_AGENT_ID`, `MESH_BEARER_TOKEN`, `MESH_PRIVATE_KEY`, `MESH_DATA_DIR` env vars
6. Return `{code: "ok", uuid}` to spawner

### Agent Bootstrap

SessionStart hook detects `MESH_AGENT_ID` env var and outputs mesh agent preamble:

```
You are a mesh agent. ALL communication happens via MCP mesh tools.
NEVER prompt the terminal user. NEVER use AskUserQuestion.
Use read_inbox(block=true) when you have no work to do.
```

## Filesystem Layout

```
.mesh/                                          # Runtime data root (gitignored)
├── events.jsonl                                # Server event log
├── server.pid                                  # Server PID
├── server.url                                  # Server URL
├── agents/
│   └── <uuid>/                                 # Per-agent home directory
│       ├── received.jsonl                      # Messages received (agent-side hook)
│       ├── sent.jsonl                          # Messages sent (agent-side hook)
│       ├── status.json                         # Last known status
│       └── claude.md                           # Role/instructions
├── channels/                                   # Future v0.2
│   └── 00000000-0000-0000-0000-000000000000/   # Broadcast channel
│       └── attachments/
└── controller/                                 # Future v0.2
    └── received.jsonl
```

## Project Structure

```
mesh-server/
├── SPEC.md
├── pyproject.toml
├── src/
│   └── mesh_server/
│       ├── __init__.py
│       ├── server.py           # MCP server setup, transport, tool registration
│       ├── tools.py            # Tool implementations
│       ├── events.py           # Event types + event store
│       ├── projections.py      # In-memory state from events
│       ├── auth.py             # Token gen, scrypt, verification
│       ├── spawner.py          # Subprocess launch, env var gen
│       └── types.py            # Shared types
├── tests/
│   ├── test_events.py
│   ├── test_projections.py
│   ├── test_tools.py
│   ├── test_auth.py
│   └── test_spawner.py
└── .mesh/                      # Runtime (gitignored)
```

### Dependencies

- `mcp` — MCP Python SDK (SSE transport)
- Python 3.12+ (stdlib: hashlib, secrets, asyncio, subprocess, dataclasses)

## Testing Strategy

Unit tests against event-sourced core. No actual Claude CLI needed for most tests.

- **Event store**: append, replay, crash recovery (truncated lines)
- **Projections**: registry/inbox correctness from event sequences
- **Tool logic**: mock MCP transport, verify events + responses
- **Auth**: round-trip token generation and verification
- **Blocking read**: asyncio test — blocked read wakes on message arrival
- **Broadcast**: nil UUID fans out to all registered agents
- **Error cases**: unknown UUID, double registration, shutdown dead agent

### Integration test

Simulated 2-agent message exchange without Claude CLI:
1. Start server → register agent A, B → A sends to B → B reads → B replies → A reads → both shutdown → verify event log

## Success Criteria

- MCP server starts and accepts SSE connections
- Agent identity via bearer token + UUID header
- 6 tools work: whoami, send, read_inbox, spawn_neighbor, show_neighbors, shutdown
- read_inbox(block=true) yields and wakes on message
- Broadcast to nil UUID fans out to all agents
- Event log persists all state changes
- Server restart rebuilds state from event log
- All unit tests pass
- Integration test passes

## Open Questions Resolved

| # | Question | Decision |
|---|---|---|
| 1 | Persistence | Event-sourced. Full log on disk. Inboxes are transient queues. |
| 2 | Ordering | FIFO per-sender. Single event loop gives natural ordering. |
| 3 | Backpressure | Deferred. No limits for v0.1. |
| 4 | Channel cleanup | Deferred (channels are v0.2). Agent dirs preserved. |
| 5 | Authentication | Bearer token + scrypt. Scheme field for upgrades. |
| 6 | Controller UI | SSE. Deferred to v0.2. |
| 7 | Group semantics | Transparent to-field. No BCC. |
| 8 | Standard commands | Agent-defined. No standard set for v0.1. |

## Agent Requirements (Integration Contract)

Any process that can do the following can participate as an agent in the mesh — it does not need to be Claude CLI.

### Minimum Requirements

1. **MCP client**: Must speak MCP protocol over streamable-HTTP transport (connect to `http://<host>:9090/mcp`)
2. **Environment variables**: Must read `MESH_AGENT_ID` (its UUID) and `MESH_BEARER_TOKEN` (its auth token) from the environment
3. **HTTP headers**: Must send `Authorization: Bearer <token>` and `X-Agent-ID: <uuid>` headers with MCP connections
4. **Tool calls**: Must call mesh tools with `caller_uuid` set to its own `MESH_AGENT_ID`

### Behavioral Contract

5. **Identity**: Agent must pass its `MESH_AGENT_ID` as `caller_uuid` in every tool call
6. **Inbox polling**: Agent should call `read_inbox(block=true)` when idle to yield execution
7. **Shutdown**: Agent should call `shutdown()` before exiting to cleanly deregister

### Optional (Claude-specific)

8. **CLAUDE.md**: Claude CLI agents receive a `claude.md` file with behavioral instructions — non-Claude agents ignore this
9. **SessionStart hook**: Claude CLI agents use this for preamble injection — non-Claude agents handle their own bootstrapping
10. **`MESH_PRIVATE_KEY`**: RSA private key for future message signing — agents may ignore this in v0.1

### Implications for Non-Claude Agents

A Python script, a Node.js process, or any MCP-capable client can join the mesh by:
- Receiving the three env vars at spawn time (or obtaining them through an out-of-band registration API, future work)
- Connecting to the MCP server and calling tools
- Following the behavioral contract (poll inbox, shut down cleanly)

The mesh server treats all agents identically — it has no concept of "Claude agent" vs "other agent." The only Claude-specific components are the spawner (which launches `claude` CLI) and the CLAUDE.md/hook preamble injection.

## What's NOT in v0.1

- Controller web UI (v0.2)
- XOR channel directories and attachments (v0.2)
- Agent runtime library (v0.2 — bootstrap is env vars + CLAUDE.md for now)
- Status block telemetry (stubbed)
- Message backpressure / TTL
- RSA signature verification

## Documentation Updates

- Update `CLAUDE.md` to reflect mesh-server as first implemented subsystem
- Add `.mesh/` to `.gitignore`
- Create `mesh-server/SPEC.md` during implementation
