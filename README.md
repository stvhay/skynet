# MCP Mesh

> Orchestrate a swarm of AI agents that talk, collaborate, and self-organize — with you in the loop.

![MCP Mesh](docs/images/hero.png)

## What is MCP Mesh?

Imagine giving a task to one AI agent and watching it recruit specialists, delegate subtasks, and coordinate across a team — all while you observe and steer from a live dashboard. That is MCP Mesh.

MCP Mesh is an actor-based runtime that connects multiple Claude CLI instances (or any MCP-capable process) into a peer-to-peer messaging network. Every agent gets an inbox, can send messages to any other agent, and can spawn new neighbors on demand. There is no central orchestrator deciding who talks to whom — agents discover each other, negotiate, and self-organize. The entire conversation history is event-sourced: every message, every registration, every shutdown is recorded in an append-only log that survives crashes and enables full replay.

You participate as a privileged peer through a web-based controller UI. You see every message flowing through the mesh in real time, can inject instructions to any agent, spawn new agents with custom system prompts, and shut down misbehaving ones — all from your browser. The mesh treats you as just another node with elevated permissions, so the same protocol that agents use to talk to each other is the one you use to talk to them.

## See it in action

Start the server and open the controller UI at `http://localhost:9090`. From the dashboard, spawn your first agent — give it a task and watch it appear in the agent list. That agent can spawn its own neighbors, and suddenly you have a small team forming before your eyes. Messages stream through the event log on the left. Click any agent to see its inbox, send it a direct message, or shut it down. The whole system is live: no polling, no page refreshes, just a real-time view of autonomous agents collaborating while you hold the reins.

## Architecture at a Glance

![Architecture Overview](docs/images/01-architecture-overview.svg)

Agents communicate through inbox queues on a shared MCP server. All state is event-sourced — restart the server and it replays from the log, losing nothing. See [ARCHITECTURE.md](docs/ARCHITECTURE.md) for the full picture.

## Quick Start

```bash
# Set up the environment (requires Nix)
direnv allow

# Install and run
cd mesh-server && uv sync
uv run mesh-server

# Open http://localhost:9090
```

## Subsystems

| Subsystem | Path | Purpose |
|-----------|------|---------|
| mesh-server | `mesh-server/` | Singleton MCP server: message routing, agent lifecycle, event store |
| controller-ui | `mesh-server/src/mesh_server/static/` | Web UI for traffic monitoring, agent management, send/receive |
| agent-runtime | `agent-runtime/` | Agent bootstrap, UUID assignment, MCP connection, lifecycle |
| channels | `channels/` | XOR-derived filesystem channels for attachments and shared artifacts |

## Development

```bash
# Environment setup (requires Nix + direnv)
direnv allow

# Build
cd mesh-server && uv sync

# Test
cd mesh-server && uv run pytest

# Lint
ruff check .
ruff format --check .
```

## Documentation

- [Architecture](docs/ARCHITECTURE.md) — System structure, subsystem boundaries, technology decisions
- [Design Document](docs/DESIGN.md) — Protocol specification, tool API, message schema
- [Server Spec](mesh-server/SPEC.md) — Invariants, failure modes, integration contract
- [Contributing](CLAUDE.md#workflow) — Development workflow and conventions
