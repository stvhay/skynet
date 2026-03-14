# skynet

## Project Overview

MCP Mesh — a message-passing actor system for orchestrating multiple Claude CLI instances as a collaborative mesh network. Agents communicate as peers through a shared MCP server using inbox queues, with a human controller participating as a privileged peer via a web UI.

The preliminary design lives in `chat-bridge/DESIGN.md`.

## Architecture

Multiple planned subsystems (to be finalized during brainstorming):

- **mesh-server** — Singleton MCP server: message routing, agent lifecycle, process registry
- **controller-ui** — Web UI for the human controller: traffic monitoring, agent management, send/receive
- **agent-runtime** — Agent bootstrap, UUID assignment, MCP connection, lifecycle management
- **channels** — XOR-derived filesystem channels for attachments and shared artifacts

See `chat-bridge/DESIGN.md` for the full design document with diagrams.

## Development

### Environment Setup

This project uses Nix flakes + direnv for reproducible environments:

- `flake.nix` — Dev tooling (Python, linters, etc.)
- `.envrc` — Loads flake and sources `.envrc.d/` and `.envrc.local.d/`
- `.envrc.d/` — Tracked initialization scripts (committed)
- `.envrc.local.d/` — Local-only initialization scripts (gitignored)

```bash
direnv allow    # Load environment
```

### Build

```bash
# TBD — finalize during brainstorming
```

### Test

```bash
# TBD — finalize during brainstorming
```

### Lint

```bash
ruff check .
ruff format --check .
```

## Workflow

All changes follow the dev-workflow-toolkit process:

1. File a GitHub issue
2. Create a branch (`/using-git-worktrees`)
3. Brainstorm (`/brainstorming`)
4. Write a plan (`/writing-plans` → `docs/plans/`)
5. Execute (`/executing-plans`)
6. Verify (`/verification-before-completion`)
7. Self-review (`/requesting-code-review`)
8. PR and finish (`/finishing-a-development-branch`)

## Conventions

- Vertical Slice Architecture: organize by feature/subsystem, not by technical layer
- Each subsystem gets a `SPEC.md` with invariants, failure modes, and public interface
- Test names encode spec item IDs: `test_inv1_description()`, `test_fail2_description()`

## Key Paths

- `chat-bridge/` — Preliminary design document and prototypes
- `docs/plans/` — Implementation plans
- `.github/` — Issue and PR templates
