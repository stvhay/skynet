# MCP Mesh

> A message-passing actor system for orchestrating AI agents as a collaborative mesh network.

![MCP Mesh](docs/images/hero.png)

MCP Mesh lets multiple Claude CLI instances (or any MCP-capable process) communicate as peers through a shared server. Agents send messages, spawn neighbors, and self-organize — while a human controller participates as a privileged peer through a web UI. The system is event-sourced, crash-recoverable, and uses deterministic XOR-based filesystem channels for file exchange.

## Key Concepts

### Peer-to-Peer Messaging

Agents communicate through inbox queues. No direct inter-process calls. The `from` field is the primary discovery mechanism.

### Human-in-the-Loop

The controller has the same send/inbox interface as agents, plus traffic monitoring and agent lifecycle management.

### Event-Sourced

All state changes are persisted as append-only events. Full replay reconstructs state on startup. Crash recovery is built in.

### XOR Channels

Deterministic filesystem paths derived from participant UUIDs. Symmetric, associative, no coordination needed.

## Architecture at a Glance

![Architecture Overview](docs/images/01-architecture-overview.svg)

See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for subsystem boundaries and technology decisions.

## Subsystems

| Subsystem | Purpose | Status |
|-----------|---------|--------|
| [mesh-server](mesh-server/) | Message routing, agent lifecycle, event store | v0.2 |
| [controller-ui](mesh-server/src/mesh_server/static/) | Web UI for human controller | v0.2 |
| [agent-runtime](agent-runtime/) | Agent bootstrap and lifecycle management | v0.2 |
| channels | XOR-derived filesystem channels | Planned |

## Quick Start

```bash
# Environment setup (requires Nix)
direnv allow
# or: nix develop

# Install dependencies
cd mesh-server && uv sync

# Run tests
uv run pytest

# Start the server (includes web UI)
uv run mesh-server
# Open http://localhost:9090 for the controller UI
```

## Documentation

- [Design Document](docs/DESIGN.md) — Protocol specification, tool API, message schema
- [Architecture](docs/ARCHITECTURE.md) — System structure, technology decisions, data flow
- [Server Spec](mesh-server/SPEC.md) — Invariants, failure modes, integration contract

## Development

```bash
# Build
cd mesh-server && uv sync

# Test
cd mesh-server && uv run pytest

# Lint
ruff check .
ruff format --check .
```

## Contributing

See the [Workflow section in CLAUDE.md](CLAUDE.md#workflow) for the development process.
