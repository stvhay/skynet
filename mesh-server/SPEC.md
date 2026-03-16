# mesh-server Subsystem Specification

## Purpose

Event-sourced MCP server for message-passing between agent instances. Singleton process that manages message routing, agent lifecycle, and process registry.

## Public Interface

### MCP Tools (streamable-HTTP transport)

| Tool | Description |
|---|---|
| `whoami(caller_uuid)` | Returns agent's UUID and neighbor count |
| `send(caller_uuid, to, message?, command?)` | Send message to agent(s) or broadcast |
| `read_inbox(caller_uuid, block?)` | Drain inbox; block=true yields until message |
| `show_neighbors(caller_uuid)` | List all registered agents |
| `spawn_neighbor(caller_uuid, claude_md?, model?, thinking_budget?)` | Register new agent, prepare credentials |
| `shutdown(caller_uuid)` | Self-terminate, deregister from mesh |

### REST/SSE API (controller web UI)

| Endpoint | Method | Description |
|---|---|---|
| `GET /api/events` | GET | SSE stream of all events (keepalive every 30s) |
| `GET /api/agents` | GET | List all agents as JSON |
| `POST /api/send` | POST | Send message from controller `{to, message?, command?}` |
| `POST /api/spawn` | POST | Spawn agent `{model?, thinking_budget?, claude_md?, initial_message?}` |
| `POST /api/agents/{uuid}/shutdown` | POST | Shut down a specific agent |
| `GET /api/inbox` | GET | Read and drain controller's inbox |
| `GET /` | GET | Serve controller UI (placeholder) |

### Environment Variables (per agent)

| Variable | Description |
|---|---|
| `MESH_AGENT_ID` | Agent's public UUID address |
| `MESH_BEARER_TOKEN` | Secret bearer token for auth |
| `MESH_PRIVATE_KEY` | RSA private key (future use) |
| `MESH_DATA_DIR` | Path to agent's `.mesh/agents/<uuid>/` directory |

## Invariants

- **INV-1**: Events are appended atomically (write + flush + fsync)
- **INV-2**: Replay reconstructs all events in order
- **INV-3**: A generated token verifies against its own hash
- **INV-4**: A wrong token does not verify
- **INV-5**: Hash includes scheme field for future upgrades
- **INV-6**: AgentRegistered adds agent to registry as alive
- **INV-7**: AgentDeregistered marks agent dead
- **INV-8**: MessageEnqueued adds to recipient inbox
- **INV-9**: MessageDrained removes from inbox
- **INV-10**: Waiter is signaled when message enqueued for blocked agent
- **INV-11**: whoami returns caller's UUID and neighbor count
- **INV-12**: send enqueues message in recipient's inbox
- **INV-13**: read_inbox drains and returns messages
- **INV-14**: read_inbox block=true waits for message
- **INV-15**: broadcast fans out to all alive agents (excluding sender)
- **INV-16**: spawn_neighbor creates agent dir and registers in event store
- **INV-17**: spawn_neighbor generates valid credentials
- **INV-18**: Full message exchange works end-to-end
- **INV-19**: EventStore subscribers receive every appended event
- **INV-20**: spawn_neighbor accepts model and thinking_budget parameters
- **INV-21**: GET /api/events streams events via SSE
- **INV-22**: GET /api/agents returns all agents as JSON
- **INV-23**: POST /api/send enqueues message from controller
- **INV-24**: POST /api/spawn registers agent and auto-sends initial_message
- **INV-25**: POST /api/agents/{uuid}/shutdown deregisters agent
- **INV-26**: GET /api/inbox returns controller's messages
- **INV-27**: Spawn chain with mock agents completes end-to-end
- **INV-28**: spawn_neighbor (MCP) launches Claude CLI subprocess via AgentSupervisor
- **INV-29**: REST /api/spawn launches Claude CLI subprocess via AgentSupervisor
- **INV-30**: Supervisor emits AgentDeregistered when process exits unexpectedly
- **INV-31**: Mock CLI agent completes full spawn→connect→message→shutdown cycle

## Failure Modes

- **FAIL-1**: Incomplete trailing line in event log is skipped on replay
- **FAIL-2**: send to unknown UUID returns not_found
- **FAIL-3**: shutdown marks agent dead and emits AgentDeregistered
- **FAIL-4**: Duplicate UUID registration (astronomically unlikely with UUIDv4)
- **FAIL-5**: Invalid model string returns error
- **FAIL-6**: Invalid thinking_budget (< 1024) returns error

## Event Model

```
AgentRegistered(uuid, token_hash, pid, timestamp)
AgentDeregistered(uuid, reason, timestamp)
MessageEnqueued(id, from_uuid, to_uuid, command?, message?, timestamp)
MessageDrained(message_id, by_uuid, timestamp)
```

## UUID Scheme (Prefix-Based Identity)

- `00000000-*` -> broadcast ("all")
- `ffffffff-*` -> controller
- anything else -> agent
- `uuid_kind(uuid)` classifies by prefix

## Addressing

- Agent-to-agent: full UUID
- Broadcast: nil UUID (`00000000-0000-0000-0000-000000000000`)
- Controller: any `ffffffff-` prefixed UUID
- BCC not supported -- `to` field is transparent

## Token Security

- `hashlib.scrypt(token, salt, n=2**14, r=8, p=1, dklen=32)`
- Stored as `{scheme, salt, hash, n, r, p}`

## Agent Requirements (Integration Contract)

Any process that meets these requirements can participate as a mesh agent.

### Minimum Requirements

1. **MCP client**: Must speak MCP protocol over streamable-HTTP transport
2. **Environment variables**: Must read `MESH_AGENT_ID` and `MESH_BEARER_TOKEN` from env
3. **HTTP headers**: Must send `Authorization: Bearer <token>` and `X-Agent-ID: <uuid>`
4. **Tool calls**: Must pass own `MESH_AGENT_ID` as `caller_uuid` in every tool call

### Behavioral Contract

5. **Inbox polling**: Should call `read_inbox(block=true)` when idle to yield execution
6. **Shutdown**: Should call `shutdown()` before exiting to cleanly deregister

### Optional (Claude-specific)

7. **CLAUDE.md**: Claude agents receive behavioral instructions -- non-Claude agents ignore
8. **SessionStart hook**: Claude agents use for preamble injection -- non-Claude agents bootstrap themselves
9. **`MESH_PRIVATE_KEY`**: Future message signing -- may be ignored in v0.1

### Non-Claude Agent Path

A Python script, Node.js process, or any MCP-capable client can join by:
receiving env vars at spawn, connecting to the MCP server, and calling tools.
The server treats all agents identically.
