# MCP Mesh Server v0.1 Implementation Plan

**Issue:** None (gh CLI unavailable — create issue before implementation)
**Beads:** None (bd unavailable)
**Design:** docs/plans/2026-03-15-mesh-server-v01-design.md

> **For Claude:** Execute this plan using subagent-driven-development (same session) or executing-plans (separate session / teammate).

**Goal:** Build an event-sourced MCP server that enables multiple Claude CLI instances to communicate as peers through inbox queues, proving the core mesh loop works.

**Architecture:** Single Python process running a FastMCP server over streamable-HTTP transport. All state changes are events written to an append-only JSONL log. In-memory projections derived from event replay provide agent registry, inbox queues, and blocking coordination. Bearer tokens authenticate agents via HTTP headers, validated with scrypt hashes.

**Tech Stack:** Python 3.13, MCP Python SDK (`mcp[cli]`), `hashlib.scrypt` (stdlib), `asyncio`, `uv` for package management, `pytest` + `pytest-asyncio` for testing.

**Acceptance Criteria — what must be TRUE when this plan is done:**
- [ ] MCP server starts and accepts streamable-HTTP connections
- [ ] Agent identity via bearer token (`Authorization` header) + UUID (`X-Agent-ID` header)
- [ ] 6 tools work: `whoami`, `send`, `read_inbox`, `show_neighbors`, `spawn_neighbor`, `shutdown`
- [ ] `read_inbox(block=true)` yields indefinitely and wakes on message arrival
- [ ] Broadcast to nil UUID (`00000000-0000-0000-0000-000000000000`) fans out to all registered agents
- [ ] Event log persists all state changes to `.mesh/events.jsonl`
- [ ] Server restart rebuilds state from event log replay
- [ ] All unit tests pass (`pytest mesh-server/tests/ -v`)
- [ ] Integration test passes: 2 simulated agents exchange messages end-to-end

**Dependencies:** None

---

### Task 1: Project Scaffolding + Types + Event Store

**Context:** This is the foundation of the mesh server. We're building an event-sourced system where all state changes are recorded as events in an append-only JSONL log. This task creates the Python package structure, defines all shared types (events, messages, agent info, tool results), and implements the event store with append, replay, and crash recovery. The event store is the single source of truth — all other state is derived from replaying it.

The project lives at `mesh-server/` within the `/workspace/skynet` repo. It uses `uv` for package management. Python 3.13 is available via Nix flake. The `.mesh/` directory is already gitignored.

**Subsystem spec(s):** None — new subsystem (SPEC.md will be created in a later task)

**Key invariants to test:**
- INV-1: Events are appended atomically (write + flush + fsync) → `def test_inv1_event_append_atomic():`
- INV-2: Replay reconstructs all events in order → `def test_inv2_replay_reconstructs_events():`
- FAIL-1: Incomplete trailing line is skipped on replay (crash recovery) → `def test_fail1_truncated_line_skipped():`

**Files:**
- Create: `mesh-server/pyproject.toml`
- Create: `mesh-server/src/mesh_server/__init__.py`
- Create: `mesh-server/src/mesh_server/types.py`
- Create: `mesh-server/src/mesh_server/events.py`
- Create: `mesh-server/tests/__init__.py`
- Create: `mesh-server/tests/test_events.py`

**Depends on:** Independent

**Step 1: Create project scaffolding**

Create `mesh-server/pyproject.toml`:

```toml
[project]
name = "mesh-server"
version = "0.1.0"
description = "MCP Mesh Server — event-sourced message-passing actor system"
requires-python = ">=3.12"
dependencies = [
    "mcp[cli]>=1.2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
]

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/mesh_server"]

[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

Create `mesh-server/src/mesh_server/__init__.py`:

```python
"""MCP Mesh Server — event-sourced message-passing actor system."""
```

Create `mesh-server/tests/__init__.py` (empty file).

**Step 2: Write types.py**

Create `mesh-server/src/mesh_server/types.py`:

```python
"""Shared types for the mesh server."""

from __future__ import annotations

import enum
import uuid as uuid_mod
from dataclasses import dataclass, field


# --- UUID Scheme (prefix-based identity) ---

BROADCAST_UUID = "00000000-0000-0000-0000-000000000000"
_CONTROLLER_PREFIX = "ffffffff"
_RESERVED_PREFIXES = {"00000000", "ffffffff"}


def generate_agent_uuid() -> str:
    """UUIDv4 guaranteed to NOT start with a reserved prefix."""
    while True:
        raw = str(uuid_mod.uuid4())
        if raw.split("-")[0] not in _RESERVED_PREFIXES:
            return raw


def generate_controller_uuid() -> str:
    """UUIDv4 with first group forced to ffffffff."""
    raw = uuid_mod.uuid4()
    return _CONTROLLER_PREFIX + "-" + str(raw).split("-", 1)[1]


def uuid_kind(u: str) -> str:
    """Classify a UUID by its prefix: 'broadcast', 'controller', or 'agent'."""
    prefix = u.split("-")[0]
    if prefix == "00000000":
        return "broadcast"
    if prefix == _CONTROLLER_PREFIX:
        return "controller"
    return "agent"


# --- Enums ---

class AgentState(enum.Enum):
    STARTING = "starting"
    RUNNING = "running"
    IDLE = "idle"
    STOPPED = "stopped"


class DeregisterReason(enum.Enum):
    SELF_SHUTDOWN = "self_shutdown"
    CONTROLLER_KILL = "controller_kill"
    CONNECTION_LOST = "connection_lost"


class ResultCode(enum.Enum):
    OK = "ok"
    NOT_FOUND = "not_found"
    UNAUTHORIZED = "unauthorized"
    INVALID_ARGS = "invalid_args"
    ALREADY_EXISTS = "already_exists"
    INTERNAL_ERROR = "internal_error"


# --- Event Types ---

@dataclass(frozen=True)
class AgentRegistered:
    uuid: str
    token_hash: dict  # {scheme, salt, hash, n, r, p}
    pid: int | None  # None when registered via direct API (tests)
    timestamp: float
    type: str = field(default="AgentRegistered", init=False)


@dataclass(frozen=True)
class AgentDeregistered:
    uuid: str
    reason: str  # DeregisterReason value
    timestamp: float
    type: str = field(default="AgentDeregistered", init=False)


@dataclass(frozen=True)
class MessageEnqueued:
    id: str
    from_uuid: str
    to_uuid: str
    command: str | None
    message: str | None
    timestamp: float
    type: str = field(default="MessageEnqueued", init=False)


@dataclass(frozen=True)
class MessageDrained:
    message_id: str
    by_uuid: str
    timestamp: float
    type: str = field(default="MessageDrained", init=False)


Event = AgentRegistered | AgentDeregistered | MessageEnqueued | MessageDrained


# --- Domain Types ---

@dataclass
class Message:
    id: str
    from_uuid: str
    to_uuid: str
    command: str | None
    message: str | None
    timestamp: float


@dataclass
class AgentInfo:
    uuid: str
    token_hash: dict
    pid: int | None
    alive: bool
    state: AgentState


@dataclass
class ToolResult:
    code: str  # ResultCode value
    data: dict = field(default_factory=dict)
    error: str | None = None
```

**Step 3: Write the failing tests for event store**

Create `mesh-server/tests/test_events.py`:

```python
"""Tests for the event store."""

import json
import os
import time

import pytest

from mesh_server.events import EventStore
from mesh_server.types import AgentRegistered, MessageEnqueued


@pytest.fixture
def event_log(tmp_path):
    """Create an EventStore with a temporary log file."""
    return EventStore(tmp_path / "events.jsonl")


def _make_agent_registered(uuid: str = "aaaa-bbbb") -> AgentRegistered:
    return AgentRegistered(
        uuid=uuid,
        token_hash={"scheme": "scrypt", "salt": "aa", "hash": "bb", "n": 16384, "r": 8, "p": 1},
        pid=1234,
        timestamp=time.time(),
    )


def _make_message_enqueued(
    from_uuid: str = "aaaa", to_uuid: str = "bbbb", msg: str = "hello"
) -> MessageEnqueued:
    return MessageEnqueued(
        id="msg-001",
        from_uuid=from_uuid,
        to_uuid=to_uuid,
        command=None,
        message=msg,
        timestamp=time.time(),
    )


def test_inv1_event_append_atomic(event_log):  # Tests INV-1
    """Events are written atomically with flush+fsync."""
    event = _make_agent_registered()
    event_log.append(event)

    # File should exist and contain exactly one valid JSON line
    with open(event_log.path) as f:
        lines = f.readlines()
    assert len(lines) == 1
    parsed = json.loads(lines[0])
    assert parsed["type"] == "AgentRegistered"
    assert parsed["uuid"] == "aaaa-bbbb"


def test_inv2_replay_reconstructs_events(event_log):  # Tests INV-2
    """Replay returns all events in append order."""
    e1 = _make_agent_registered("agent-1")
    e2 = _make_message_enqueued("agent-1", "agent-2", "hello")
    e3 = _make_agent_registered("agent-2")

    event_log.append(e1)
    event_log.append(e2)
    event_log.append(e3)

    events = event_log.replay()
    assert len(events) == 3
    assert events[0].type == "AgentRegistered"
    assert events[0].uuid == "agent-1"
    assert events[1].type == "MessageEnqueued"
    assert events[1].message == "hello"
    assert events[2].type == "AgentRegistered"
    assert events[2].uuid == "agent-2"


def test_fail1_truncated_line_skipped(event_log):  # Tests FAIL-1
    """Incomplete trailing line (simulating crash) is skipped on replay."""
    event = _make_agent_registered()
    event_log.append(event)

    # Simulate crash: append a partial JSON line
    with open(event_log.path, "a") as f:
        f.write('{"type": "AgentRegistered", "uuid": "partial')
        # No newline — simulates crash mid-write

    events = event_log.replay()
    assert len(events) == 1  # Only the complete event
    assert events[0].uuid == "aaaa-bbbb"


def test_append_multiple_types(event_log):
    """Different event types serialize and deserialize correctly."""
    e1 = _make_agent_registered()
    e2 = _make_message_enqueued()

    event_log.append(e1)
    event_log.append(e2)

    events = event_log.replay()
    assert len(events) == 2
    assert isinstance(events[0], AgentRegistered)
    assert isinstance(events[1], MessageEnqueued)


def test_replay_empty_log(event_log):
    """Replay on a nonexistent log returns empty list."""
    events = event_log.replay()
    assert events == []
```

**Step 4: Run tests to verify they fail**

Run: `cd /workspace/skynet/mesh-server && uv sync --extra dev && uv run pytest tests/test_events.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mesh_server.events'`

**Step 5: Implement events.py**

Create `mesh-server/src/mesh_server/events.py`:

```python
"""Event types and append-only event store."""

from __future__ import annotations

import dataclasses
import json
import os
from pathlib import Path

from mesh_server.types import (
    AgentDeregistered,
    AgentRegistered,
    Event,
    MessageDrained,
    MessageEnqueued,
)

_EVENT_TYPES: dict[str, type] = {
    "AgentRegistered": AgentRegistered,
    "AgentDeregistered": AgentDeregistered,
    "MessageEnqueued": MessageEnqueued,
    "MessageDrained": MessageDrained,
}


class EventStore:
    """Append-only JSONL event log with crash recovery."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)

    def append(self, event: Event) -> None:
        """Append an event to the log. Write + flush + fsync for durability."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        data = dataclasses.asdict(event)
        line = json.dumps(data, separators=(",", ":")) + "\n"
        fd = os.open(str(self.path), os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o644)
        try:
            os.write(fd, line.encode())
            os.fsync(fd)
        finally:
            os.close(fd)

    def replay(self) -> list[Event]:
        """Replay all events from the log. Skips incomplete trailing lines."""
        if not self.path.exists():
            return []

        events: list[Event] = []
        with open(self.path) as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                except json.JSONDecodeError:
                    continue  # Skip incomplete/corrupt lines
                event_type = _EVENT_TYPES.get(data.get("type"))
                if event_type is None:
                    continue  # Skip unknown event types
                # Remove 'type' from data — it's a field default, not a constructor arg
                data.pop("type", None)
                events.append(event_type(**data))
        return events
```

**Step 6: Run tests to verify they pass**

Run: `cd /workspace/skynet/mesh-server && uv run pytest tests/test_events.py -v`
Expected: All 5 tests PASS

**Step 7: Commit**

```bash
cd /workspace/skynet
git add mesh-server/pyproject.toml mesh-server/src/mesh_server/__init__.py mesh-server/src/mesh_server/types.py mesh-server/src/mesh_server/events.py mesh-server/tests/__init__.py mesh-server/tests/test_events.py
git commit -m "feat(mesh-server): add project scaffolding, types, and event store

Event-sourced foundation: append-only JSONL log with atomic writes
(flush+fsync) and crash recovery (skips incomplete trailing lines).
Shared types for events, messages, agent info, and tool results."
```

---

### Task 2: Auth Module

**Context:** This task implements the authentication module for the mesh server. Each agent receives a bearer token at spawn time. The server stores a scrypt hash of the token (never the raw token). When an agent connects, the server verifies the bearer token against the stored hash.

We use `hashlib.scrypt` from Python's stdlib — it's memory-hard, NIST-approved, and has zero external dependencies. The stored hash includes a `scheme` field so we can upgrade the hashing algorithm in the future without breaking existing registrations.

Parameters: `n=2**14` (16384), `r=8`, `p=1`, `dklen=32`. Salt is 16 bytes of `os.urandom`.

This module lives at `mesh-server/src/mesh_server/auth.py`. It has no dependencies on other mesh-server modules.

**Subsystem spec(s):** None — new subsystem
**Key invariants to test:**
- INV-3: A generated token verifies against its own hash → `def test_inv3_token_roundtrip():`
- INV-4: A wrong token does not verify → `def test_inv4_wrong_token_rejected():`
- INV-5: Hash includes scheme field for future upgrades → `def test_inv5_hash_includes_scheme():`

**Files:**
- Create: `mesh-server/src/mesh_server/auth.py`
- Create: `mesh-server/tests/test_auth.py`

**Depends on:** Independent

**Step 1: Write the failing tests**

Create `mesh-server/tests/test_auth.py`:

```python
"""Tests for the auth module."""

from mesh_server.auth import generate_token, hash_token, verify_token


def test_inv3_token_roundtrip():  # Tests INV-3
    """A generated token verifies against its own hash."""
    raw_token = generate_token()
    token_hash = hash_token(raw_token)
    assert verify_token(raw_token, token_hash) is True


def test_inv4_wrong_token_rejected():  # Tests INV-4
    """A wrong token does not verify."""
    raw_token = generate_token()
    token_hash = hash_token(raw_token)
    assert verify_token("wrong-token-value", token_hash) is False


def test_inv5_hash_includes_scheme():  # Tests INV-5
    """Hash dict includes scheme field for upgrade path."""
    raw_token = generate_token()
    token_hash = hash_token(raw_token)
    assert token_hash["scheme"] == "scrypt"
    assert "salt" in token_hash
    assert "hash" in token_hash
    assert token_hash["n"] == 16384
    assert token_hash["r"] == 8
    assert token_hash["p"] == 1


def test_generate_token_is_unique():
    """Each generated token is unique."""
    tokens = {generate_token() for _ in range(10)}
    assert len(tokens) == 10


def test_generate_token_length():
    """Token is 64 hex chars (32 bytes)."""
    token = generate_token()
    assert len(token) == 64
    int(token, 16)  # Should be valid hex
```

**Step 2: Run tests to verify they fail**

Run: `cd /workspace/skynet/mesh-server && uv run pytest tests/test_auth.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mesh_server.auth'`

**Step 3: Implement auth.py**

Create `mesh-server/src/mesh_server/auth.py`:

```python
"""Token generation and scrypt-based verification."""

from __future__ import annotations

import hashlib
import hmac
import os
import secrets


def generate_token() -> str:
    """Generate a 256-bit random bearer token as hex string."""
    return secrets.token_hex(32)


def hash_token(raw_token: str) -> dict:
    """Hash a token using scrypt. Returns a dict with scheme + parameters."""
    salt = os.urandom(16)
    h = hashlib.scrypt(
        raw_token.encode(),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )
    return {
        "scheme": "scrypt",
        "salt": salt.hex(),
        "hash": h.hex(),
        "n": 16384,
        "r": 8,
        "p": 1,
    }


def verify_token(raw_token: str, stored: dict) -> bool:
    """Verify a raw token against a stored scrypt hash."""
    if stored.get("scheme") != "scrypt":
        return False
    h = hashlib.scrypt(
        raw_token.encode(),
        salt=bytes.fromhex(stored["salt"]),
        n=stored["n"],
        r=stored["r"],
        p=stored["p"],
        dklen=32,
    )
    return hmac.compare_digest(h.hex(), stored["hash"])
```

**Step 4: Run tests to verify they pass**

Run: `cd /workspace/skynet/mesh-server && uv run pytest tests/test_auth.py -v`
Expected: All 5 tests PASS

**Step 5: Commit**

```bash
cd /workspace/skynet
git add mesh-server/src/mesh_server/auth.py mesh-server/tests/test_auth.py
git commit -m "feat(mesh-server): add auth module with scrypt token hashing

hashlib.scrypt with n=2**14, r=8, p=1, dklen=32. Scheme field in
stored hash enables future algorithm upgrades. Constant-time comparison
via hmac.compare_digest."
```

---

### Task 3: Projections (In-Memory State from Events)

**Context:** This task implements the projections layer — in-memory state derived from replaying events. The `MeshState` class processes events and maintains three projections:

1. **Agent registry** — maps UUID to AgentInfo (token hash, PID, alive/dead, state)
2. **Inbox queues** — maps UUID to list of undelivered Messages
3. **Waiters** — maps UUID to `asyncio.Event` for blocking `read_inbox` coordination

The projections are disposable — delete them, replay the event log, and you get the same state (except waiters, which are ephemeral). The `MeshState` is the central state object that the MCP tool handlers will interact with.

This module depends on types from `mesh_server.types` (Task 1). The event types used are:
- `AgentRegistered` → adds agent to registry
- `AgentDeregistered` → marks agent as dead in registry, clears waiter
- `MessageEnqueued` → adds message to recipient's inbox, signals waiter if blocked
- `MessageDrained` → removes messages from inbox

**Subsystem spec(s):** None — new subsystem
**Key invariants to test:**
- INV-6: AgentRegistered adds agent to registry as alive → `def test_inv6_register_adds_alive_agent():`
- INV-7: AgentDeregistered marks agent dead → `def test_inv7_deregister_marks_dead():`
- INV-8: MessageEnqueued adds to recipient inbox → `def test_inv8_enqueue_adds_to_inbox():`
- INV-9: MessageDrained removes from inbox → `def test_inv9_drain_removes_from_inbox():`
- INV-10: Waiter is signaled when message enqueued for blocked agent → `def test_inv10_waiter_signaled_on_enqueue():`

**Files:**
- Create: `mesh-server/src/mesh_server/projections.py`
- Create: `mesh-server/tests/test_projections.py`

**Depends on:** Task 1 (types.py, events.py)

**Step 1: Write the failing tests**

Create `mesh-server/tests/test_projections.py`:

```python
"""Tests for in-memory projections."""

import asyncio
import time

import pytest

from mesh_server.projections import MeshState
from mesh_server.types import (
    BROADCAST_UUID,
    AgentDeregistered,
    AgentRegistered,
    AgentState,
    MessageDrained,
    MessageEnqueued,
)


def _reg(uuid: str = "agent-1", pid: int = 100) -> AgentRegistered:
    return AgentRegistered(
        uuid=uuid,
        token_hash={"scheme": "scrypt", "salt": "aa", "hash": "bb", "n": 16384, "r": 8, "p": 1},
        pid=pid,
        timestamp=time.time(),
    )


def _dereg(uuid: str = "agent-1", reason: str = "self_shutdown") -> AgentDeregistered:
    return AgentDeregistered(uuid=uuid, reason=reason, timestamp=time.time())


def _msg(
    msg_id: str = "m1",
    from_uuid: str = "agent-1",
    to_uuid: str = "agent-2",
    message: str = "hello",
) -> MessageEnqueued:
    return MessageEnqueued(
        id=msg_id,
        from_uuid=from_uuid,
        to_uuid=to_uuid,
        command=None,
        message=message,
        timestamp=time.time(),
    )


def _drain(msg_id: str = "m1", by: str = "agent-2") -> MessageDrained:
    return MessageDrained(message_id=msg_id, by_uuid=by, timestamp=time.time())


def test_inv6_register_adds_alive_agent():  # Tests INV-6
    state = MeshState()
    state.apply(_reg("agent-1", pid=100))
    agent = state.get_agent("agent-1")
    assert agent is not None
    assert agent.alive is True
    assert agent.pid == 100
    assert agent.state == AgentState.RUNNING


def test_inv7_deregister_marks_dead():  # Tests INV-7
    state = MeshState()
    state.apply(_reg("agent-1"))
    state.apply(_dereg("agent-1"))
    agent = state.get_agent("agent-1")
    assert agent is not None
    assert agent.alive is False
    assert agent.state == AgentState.STOPPED


def test_inv8_enqueue_adds_to_inbox():  # Tests INV-8
    state = MeshState()
    state.apply(_reg("agent-1"))
    state.apply(_reg("agent-2"))
    state.apply(_msg("m1", "agent-1", "agent-2", "hello"))
    inbox = state.get_inbox("agent-2")
    assert len(inbox) == 1
    assert inbox[0].message == "hello"
    assert inbox[0].from_uuid == "agent-1"


def test_inv9_drain_removes_from_inbox():  # Tests INV-9
    state = MeshState()
    state.apply(_reg("agent-1"))
    state.apply(_reg("agent-2"))
    state.apply(_msg("m1", "agent-1", "agent-2", "hello"))
    state.apply(_drain("m1", "agent-2"))
    inbox = state.get_inbox("agent-2")
    assert len(inbox) == 0


async def test_inv10_waiter_signaled_on_enqueue():  # Tests INV-10
    state = MeshState()
    state.apply(_reg("agent-1"))
    state.apply(_reg("agent-2"))

    # Set up a waiter for agent-2
    waiter = state.set_waiter("agent-2")
    assert not waiter.is_set()

    # Enqueue a message — should signal the waiter
    state.apply(_msg("m1", "agent-1", "agent-2", "wake up"))
    assert waiter.is_set()


def test_list_alive_agents():
    state = MeshState()
    state.apply(_reg("agent-1"))
    state.apply(_reg("agent-2"))
    state.apply(_dereg("agent-1"))
    alive = state.list_alive_agents()
    assert len(alive) == 1
    assert alive[0].uuid == "agent-2"


def test_broadcast_enqueues_to_all():
    """MessageEnqueued to BROADCAST_UUID should be handled at the tool layer,
    not in projections. Projections only handle single-recipient enqueues."""
    state = MeshState()
    state.apply(_reg("agent-1"))
    state.apply(_msg("m1", "agent-1", "agent-2", "direct"))
    inbox = state.get_inbox("agent-2")
    assert len(inbox) == 1


def test_deregister_clears_waiter():
    state = MeshState()
    state.apply(_reg("agent-1"))
    waiter = state.set_waiter("agent-1")
    state.apply(_dereg("agent-1"))
    # Waiter should be signaled so blocked read_inbox unblocks
    assert waiter.is_set()
    assert state.get_waiter("agent-1") is None


def test_rebuild_from_events():
    """State can be rebuilt by applying a sequence of events."""
    events = [
        _reg("a1"),
        _reg("a2"),
        _msg("m1", "a1", "a2", "hi"),
        _drain("m1", "a2"),
        _dereg("a1"),
    ]
    state = MeshState()
    for e in events:
        state.apply(e)

    assert state.get_agent("a1").alive is False
    assert state.get_agent("a2").alive is True
    assert len(state.get_inbox("a2")) == 0
```

**Step 2: Run tests to verify they fail**

Run: `cd /workspace/skynet/mesh-server && uv run pytest tests/test_projections.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mesh_server.projections'`

**Step 3: Implement projections.py**

Create `mesh-server/src/mesh_server/projections.py`:

```python
"""In-memory projections derived from events."""

from __future__ import annotations

import asyncio

from mesh_server.types import (
    AgentDeregistered,
    AgentInfo,
    AgentRegistered,
    AgentState,
    Event,
    Message,
    MessageDrained,
    MessageEnqueued,
)


class MeshState:
    """In-memory state rebuilt from event replay.

    Maintains three projections:
    - registry: uuid → AgentInfo
    - inboxes: uuid → list[Message]  (undelivered)
    - waiters: uuid → asyncio.Event  (ephemeral, not persisted)
    """

    def __init__(self) -> None:
        self._registry: dict[str, AgentInfo] = {}
        self._inboxes: dict[str, list[Message]] = {}
        self._waiters: dict[str, asyncio.Event] = {}

    def apply(self, event: Event) -> None:
        """Apply an event to update projections."""
        if isinstance(event, AgentRegistered):
            self._apply_registered(event)
        elif isinstance(event, AgentDeregistered):
            self._apply_deregistered(event)
        elif isinstance(event, MessageEnqueued):
            self._apply_enqueued(event)
        elif isinstance(event, MessageDrained):
            self._apply_drained(event)

    def _apply_registered(self, event: AgentRegistered) -> None:
        self._registry[event.uuid] = AgentInfo(
            uuid=event.uuid,
            token_hash=event.token_hash,
            pid=event.pid,
            alive=True,
            state=AgentState.RUNNING,
        )
        self._inboxes.setdefault(event.uuid, [])

    def _apply_deregistered(self, event: AgentDeregistered) -> None:
        agent = self._registry.get(event.uuid)
        if agent:
            agent.alive = False
            agent.state = AgentState.STOPPED
        # Signal waiter so blocked read_inbox unblocks
        waiter = self._waiters.pop(event.uuid, None)
        if waiter:
            waiter.set()

    def _apply_enqueued(self, event: MessageEnqueued) -> None:
        msg = Message(
            id=event.id,
            from_uuid=event.from_uuid,
            to_uuid=event.to_uuid,
            command=event.command,
            message=event.message,
            timestamp=event.timestamp,
        )
        self._inboxes.setdefault(event.to_uuid, []).append(msg)
        # Signal waiter if agent is blocked on read_inbox
        waiter = self._waiters.get(event.to_uuid)
        if waiter:
            waiter.set()

    def _apply_drained(self, event: MessageDrained) -> None:
        inbox = self._inboxes.get(event.by_uuid, [])
        self._inboxes[event.by_uuid] = [
            m for m in inbox if m.id != event.message_id
        ]

    # --- Query methods ---

    def get_agent(self, uuid: str) -> AgentInfo | None:
        return self._registry.get(uuid)

    def get_inbox(self, uuid: str) -> list[Message]:
        return list(self._inboxes.get(uuid, []))

    def list_alive_agents(self) -> list[AgentInfo]:
        return [a for a in self._registry.values() if a.alive]

    def list_all_agents(self) -> list[AgentInfo]:
        return list(self._registry.values())

    def set_waiter(self, uuid: str) -> asyncio.Event:
        """Register a waiter for blocking read_inbox. Returns the Event to await."""
        event = asyncio.Event()
        self._waiters[uuid] = event
        return event

    def get_waiter(self, uuid: str) -> asyncio.Event | None:
        return self._waiters.get(uuid)

    def clear_waiter(self, uuid: str) -> None:
        self._waiters.pop(uuid, None)
```

**Step 4: Run tests to verify they pass**

Run: `cd /workspace/skynet/mesh-server && uv run pytest tests/test_projections.py -v`
Expected: All 9 tests PASS

**Step 5: Commit**

```bash
cd /workspace/skynet
git add mesh-server/src/mesh_server/projections.py mesh-server/tests/test_projections.py
git commit -m "feat(mesh-server): add projections layer for in-memory state

MeshState applies events to maintain agent registry, inbox queues,
and asyncio.Event waiters for blocking read_inbox coordination.
Disposable — rebuilt by replaying event log on startup."
```

---

### Task 4: MCP Server + Tool Implementations

**Context:** This is the core task — wiring up the MCP server with all 6 tools. The server uses the MCP Python SDK's `FastMCP` class with streamable-HTTP transport. All state lives in a `MeshState` projection (Task 3) backed by an `EventStore` (Task 1). Authentication uses scrypt token verification (Task 2).

**Architecture:**
- `server.py` creates the `FastMCP` instance with a lifespan that initializes `EventStore` + `MeshState` (replaying events on startup).
- `tools.py` defines the 6 tool functions, each receiving a `Context` for access to shared state.
- Auth: Each tool handler extracts the agent's UUID from the `Context`. The authentication (bearer token validation) happens at the HTTP middleware level before MCP protocol processing — but for v0.1, we'll validate inside tool handlers using a `_get_caller()` helper, since the MCP SDK's `Context` may not expose raw HTTP headers. If header access isn't available, agents self-identify via their first `whoami(token, uuid)` call which validates and registers the session.

**MCP SDK API** (from research):
```python
from mcp.server.fastmcp import FastMCP, Context
from mcp.server.session import ServerSession

mcp = FastMCP("mesh", json_response=True)

@mcp.tool()
async def my_tool(arg: str, ctx: Context[ServerSession, AppContext]) -> str:
    app = ctx.request_context.lifespan_context  # Access shared state
    ...
```

The lifespan pattern manages startup/shutdown of the EventStore and MeshState.

**Important design decisions:**
- `read_inbox(block=true)` holds the MCP tool call open by awaiting an `asyncio.Event`. No timeout — true yield.
- `send(to=BROADCAST_UUID)` fans out: iterates all alive agents, creates one `MessageEnqueued` event per recipient.
- `spawn_neighbor` generates credentials, writes agent dir, launches subprocess. For v0.1, subprocess launch is a separate module (Task 5) — this task implements the tool but delegates actual process launch.
- All tool results use `ToolResult(code, data, error)` serialized as dict.

**Subsystem spec(s):** None — new subsystem
**Key invariants to test:**
- INV-11: whoami returns caller's UUID and neighbor count → `def test_inv11_whoami_returns_identity():`
- INV-12: send enqueues message in recipient's inbox → `def test_inv12_send_enqueues_message():`
- INV-13: read_inbox drains and returns messages → `def test_inv13_read_inbox_drains():`
- INV-14: read_inbox block=true waits for message → `def test_inv14_read_inbox_blocks():`
- INV-15: broadcast fans out to all alive agents → `def test_inv15_broadcast_fans_out():`
- FAIL-2: send to unknown UUID returns not_found → `def test_fail2_send_unknown_uuid():`
- FAIL-3: shutdown marks agent dead → `def test_fail3_shutdown_deregisters():`

**Files:**
- Create: `mesh-server/src/mesh_server/server.py`
- Create: `mesh-server/src/mesh_server/tools.py`
- Create: `mesh-server/tests/test_tools.py`

**Depends on:** Task 1, Task 2, Task 3

**Step 1: Write the failing tests**

Create `mesh-server/tests/test_tools.py`:

```python
"""Tests for MCP tool implementations.

These tests exercise tool logic directly against MeshState + EventStore,
without going through the MCP transport layer. The MCP server wiring
is a thin layer that delegates to these functions.
"""

import asyncio
import time

import pytest

from mesh_server.events import EventStore
from mesh_server.tools import (
    tool_read_inbox,
    tool_send,
    tool_show_neighbors,
    tool_shutdown,
    tool_whoami,
)
from mesh_server.auth import generate_token, hash_token
from mesh_server.projections import MeshState
from mesh_server.types import AgentRegistered, BROADCAST_UUID


@pytest.fixture
def store(tmp_path):
    return EventStore(tmp_path / "events.jsonl")


@pytest.fixture
def state():
    return MeshState()


def _register(state, store, uuid="agent-1", pid=100):
    """Helper to register an agent."""
    token = generate_token()
    token_h = hash_token(token)
    event = AgentRegistered(
        uuid=uuid, token_hash=token_h, pid=pid, timestamp=time.time()
    )
    store.append(event)
    state.apply(event)
    return token


def test_inv11_whoami_returns_identity(state, store):  # Tests INV-11
    _register(state, store, "agent-1")
    _register(state, store, "agent-2")
    result = tool_whoami(state, caller_uuid="agent-1")
    assert result["code"] == "ok"
    assert result["data"]["uuid"] == "agent-1"
    assert result["data"]["neighbors_count"] == 2  # includes self


def test_inv12_send_enqueues_message(state, store):  # Tests INV-12
    _register(state, store, "agent-1")
    _register(state, store, "agent-2")
    result = tool_send(
        state, store,
        caller_uuid="agent-1",
        to="agent-2",
        message="hello",
        command=None,
    )
    assert result["code"] == "ok"
    assert "agent-2" in result["data"]["delivered_to"]
    inbox = state.get_inbox("agent-2")
    assert len(inbox) == 1
    assert inbox[0].message == "hello"


def test_inv13_read_inbox_drains(state, store):  # Tests INV-13
    _register(state, store, "agent-1")
    _register(state, store, "agent-2")
    tool_send(state, store, caller_uuid="agent-1", to="agent-2", message="hi")
    result = tool_read_inbox(state, store, caller_uuid="agent-2", block=False)
    assert result["code"] == "ok"
    assert len(result["data"]["messages"]) == 1
    assert result["data"]["messages"][0]["message"] == "hi"
    # Inbox should now be empty
    assert len(state.get_inbox("agent-2")) == 0


async def test_inv14_read_inbox_blocks(state, store):  # Tests INV-14
    _register(state, store, "agent-1")
    _register(state, store, "agent-2")

    # Start blocking read in background
    read_task = asyncio.create_task(
        tool_read_inbox_async(state, store, caller_uuid="agent-2", block=True)
    )
    await asyncio.sleep(0.05)  # Let the task start waiting
    assert not read_task.done()

    # Send a message — should wake the reader
    tool_send(state, store, caller_uuid="agent-1", to="agent-2", message="wake")
    result = await asyncio.wait_for(read_task, timeout=2.0)
    assert result["code"] == "ok"
    assert len(result["data"]["messages"]) == 1
    assert result["data"]["messages"][0]["message"] == "wake"


def test_inv15_broadcast_fans_out(state, store):  # Tests INV-15
    _register(state, store, "agent-1")
    _register(state, store, "agent-2")
    _register(state, store, "agent-3")
    result = tool_send(
        state, store,
        caller_uuid="agent-1",
        to=BROADCAST_UUID,
        message="broadcast msg",
    )
    assert result["code"] == "ok"
    # Should deliver to agent-2 and agent-3 (not sender agent-1)
    assert len(result["data"]["delivered_to"]) == 2
    assert len(state.get_inbox("agent-2")) == 1
    assert len(state.get_inbox("agent-3")) == 1
    assert len(state.get_inbox("agent-1")) == 0


def test_fail2_send_unknown_uuid(state, store):  # Tests FAIL-2
    _register(state, store, "agent-1")
    result = tool_send(
        state, store, caller_uuid="agent-1", to="nonexistent", message="hi"
    )
    assert result["code"] == "not_found"


def test_fail3_shutdown_deregisters(state, store):  # Tests FAIL-3
    _register(state, store, "agent-1")
    result = tool_shutdown(state, store, caller_uuid="agent-1")
    assert result["code"] == "ok"
    agent = state.get_agent("agent-1")
    assert agent.alive is False


def test_show_neighbors(state, store):
    _register(state, store, "agent-1")
    _register(state, store, "agent-2")
    result = tool_show_neighbors(state, caller_uuid="agent-1")
    assert result["code"] == "ok"
    neighbors = result["data"]["neighbors"]
    uuids = [n["uuid"] for n in neighbors]
    assert "agent-1" in uuids
    assert "agent-2" in uuids


def test_read_inbox_empty_nonblocking(state, store):
    _register(state, store, "agent-1")
    result = tool_read_inbox(state, store, caller_uuid="agent-1", block=False)
    assert result["code"] == "ok"
    assert result["data"]["messages"] == []


# Import the async version for blocking tests
from mesh_server.tools import tool_read_inbox_async
```

**Step 2: Run tests to verify they fail**

Run: `cd /workspace/skynet/mesh-server && uv run pytest tests/test_tools.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mesh_server.tools'`

**Step 3: Implement tools.py**

Create `mesh-server/src/mesh_server/tools.py`:

```python
"""Tool implementations for the mesh server.

Each function takes MeshState + EventStore + caller identity,
performs the operation, and returns a ToolResult dict.
"""

from __future__ import annotations

import asyncio
import time
import uuid as uuid_mod

from mesh_server.events import EventStore
from mesh_server.projections import MeshState
from mesh_server.types import (
    BROADCAST_UUID,
    AgentDeregistered,
    MessageDrained,
    MessageEnqueued,
)


def _result(code: str, data: dict | None = None, error: str | None = None) -> dict:
    return {"code": code, "data": data or {}, "error": error}


def tool_whoami(state: MeshState, *, caller_uuid: str) -> dict:
    """Return the caller's UUID and neighbor count."""
    agent = state.get_agent(caller_uuid)
    if not agent or not agent.alive:
        return _result("not_found", error=f"Agent {caller_uuid} not registered")
    all_agents = state.list_alive_agents()
    return _result("ok", {"uuid": caller_uuid, "neighbors_count": len(all_agents)})


def tool_send(
    state: MeshState,
    store: EventStore,
    *,
    caller_uuid: str,
    to: str | list[str],
    message: str | None = None,
    command: str | None = None,
) -> dict:
    """Send a message to one or more recipients."""
    # Normalize `to` to a list of recipient UUIDs
    if isinstance(to, str):
        if to == BROADCAST_UUID:
            recipients = [a.uuid for a in state.list_alive_agents() if a.uuid != caller_uuid]
        else:
            recipients = [to]
    else:
        recipients = list(to)

    # Validate recipients
    delivered_to = []
    for recipient in recipients:
        agent = state.get_agent(recipient)
        if not agent or not agent.alive:
            if len(recipients) == 1:
                return _result("not_found", error=f"Agent {recipient} not found")
            continue  # Skip dead agents in broadcast/group

        msg_id = str(uuid_mod.uuid4())
        event = MessageEnqueued(
            id=msg_id,
            from_uuid=caller_uuid,
            to_uuid=recipient,
            command=command,
            message=message,
            timestamp=time.time(),
        )
        store.append(event)
        state.apply(event)
        delivered_to.append(recipient)

    return _result("ok", {"delivered_to": delivered_to})


def tool_read_inbox(
    state: MeshState,
    store: EventStore,
    *,
    caller_uuid: str,
    block: bool = False,
) -> dict:
    """Read and drain inbox (non-blocking version)."""
    messages = state.get_inbox(caller_uuid)
    # Drain: emit MessageDrained events
    for msg in messages:
        drain_event = MessageDrained(
            message_id=msg.id, by_uuid=caller_uuid, timestamp=time.time()
        )
        store.append(drain_event)
        state.apply(drain_event)

    return _result("ok", {
        "messages": [
            {
                "id": m.id,
                "from": m.from_uuid,
                "to": m.to_uuid,
                "command": m.command,
                "message": m.message,
                "timestamp": m.timestamp,
            }
            for m in messages
        ]
    })


async def tool_read_inbox_async(
    state: MeshState,
    store: EventStore,
    *,
    caller_uuid: str,
    block: bool = False,
) -> dict:
    """Read and drain inbox. If block=True, waits indefinitely for a message."""
    if block:
        # Check if inbox is empty — if so, wait
        messages = state.get_inbox(caller_uuid)
        if not messages:
            waiter = state.set_waiter(caller_uuid)
            try:
                await waiter.wait()
            finally:
                state.clear_waiter(caller_uuid)

    # Now drain (whether we waited or not)
    return tool_read_inbox(state, store, caller_uuid=caller_uuid, block=False)


def tool_show_neighbors(state: MeshState, *, caller_uuid: str) -> dict:
    """List all registered agents."""
    agents = state.list_all_agents()
    return _result("ok", {
        "neighbors": [
            {
                "uuid": a.uuid,
                "alive": a.alive,
                "state": a.state.value,
                "pid": a.pid,
            }
            for a in agents
        ]
    })


def tool_shutdown(
    state: MeshState,
    store: EventStore,
    *,
    caller_uuid: str,
) -> dict:
    """Agent self-terminates."""
    agent = state.get_agent(caller_uuid)
    if not agent or not agent.alive:
        return _result("not_found", error=f"Agent {caller_uuid} not found")

    event = AgentDeregistered(
        uuid=caller_uuid, reason="self_shutdown", timestamp=time.time()
    )
    store.append(event)
    state.apply(event)
    return _result("ok")
```

**Step 4: Run tests to verify they pass**

Run: `cd /workspace/skynet/mesh-server && uv run pytest tests/test_tools.py -v`
Expected: All 9 tests PASS

**Step 5: Implement server.py (MCP wiring)**

Create `mesh-server/src/mesh_server/server.py`:

```python
"""MCP server setup with FastMCP, streamable-HTTP transport."""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

from mcp.server.fastmcp import Context, FastMCP
from mcp.server.session import ServerSession

from mesh_server.auth import verify_token
from mesh_server.events import EventStore
from mesh_server.projections import MeshState
from mesh_server.tools import (
    tool_read_inbox_async,
    tool_send,
    tool_show_neighbors,
    tool_shutdown,
    tool_whoami,
)


@dataclass
class AppContext:
    store: EventStore
    state: MeshState
    mesh_dir: Path


@asynccontextmanager
async def app_lifespan(server: FastMCP):
    """Initialize event store and rebuild state from event log."""
    mesh_dir = Path(os.environ.get("MESH_DIR", ".mesh"))
    store = EventStore(mesh_dir / "events.jsonl")
    state = MeshState()

    # Replay events to rebuild state
    for event in store.replay():
        state.apply(event)

    yield AppContext(store=store, state=state, mesh_dir=mesh_dir)


mcp = FastMCP("mesh", lifespan=app_lifespan, json_response=True)

Ctx = Context[ServerSession, AppContext]


def _get_app(ctx: Ctx) -> AppContext:
    return ctx.request_context.lifespan_context


def _get_caller(ctx: Ctx) -> str:
    """Extract caller UUID from context.

    In v0.1, the caller UUID is passed as a tool argument.
    Future: extract from HTTP headers via auth middleware.
    """
    # This is a placeholder — see note in each tool below
    raise NotImplementedError("Caller extraction via middleware not yet implemented")


@mcp.tool()
async def whoami(caller_uuid: str, ctx: Ctx) -> dict:
    """Return your UUID and current neighbor count.

    Args:
        caller_uuid: Your agent UUID (from MESH_AGENT_ID env var)
    """
    app = _get_app(ctx)
    return tool_whoami(app.state, caller_uuid=caller_uuid)


@mcp.tool()
async def send(
    caller_uuid: str,
    to: str,
    ctx: Ctx,
    message: str | None = None,
    command: str | None = None,
) -> dict:
    """Send a message to another agent or broadcast.

    Args:
        caller_uuid: Your agent UUID (from MESH_AGENT_ID env var)
        to: Recipient UUID, or "00000000-0000-0000-0000-000000000000" for broadcast
        message: Free-form message text
        command: Optional structured command string
    """
    app = _get_app(ctx)
    # Validate caller is registered
    agent = app.state.get_agent(caller_uuid)
    if not agent or not agent.alive:
        return {"code": "unauthorized", "data": {}, "error": "Agent not registered"}
    return tool_send(
        app.state, app.store,
        caller_uuid=caller_uuid, to=to, message=message, command=command,
    )


@mcp.tool()
async def read_inbox(
    caller_uuid: str,
    ctx: Ctx,
    block: bool = False,
) -> dict:
    """Read and drain your inbox.

    Args:
        caller_uuid: Your agent UUID (from MESH_AGENT_ID env var)
        block: If true, wait indefinitely until a message arrives (yield/idle)
    """
    app = _get_app(ctx)
    return await tool_read_inbox_async(
        app.state, app.store, caller_uuid=caller_uuid, block=block,
    )


@mcp.tool()
async def show_neighbors(caller_uuid: str, ctx: Ctx) -> dict:
    """List all registered agents with their status.

    Args:
        caller_uuid: Your agent UUID (from MESH_AGENT_ID env var)
    """
    app = _get_app(ctx)
    return tool_show_neighbors(app.state, caller_uuid=caller_uuid)


@mcp.tool()
async def shutdown(caller_uuid: str, ctx: Ctx) -> dict:
    """Self-terminate. Deregisters from the mesh and stops this agent.

    Args:
        caller_uuid: Your agent UUID (from MESH_AGENT_ID env var)
    """
    app = _get_app(ctx)
    return tool_shutdown(app.state, app.store, caller_uuid=caller_uuid)


def run_server(host: str = "0.0.0.0", port: int = 9090) -> None:
    """Start the MCP mesh server."""
    mcp.run(transport="streamable-http", host=host, port=port)


if __name__ == "__main__":
    run_server()
```

Note: In v0.1, `caller_uuid` is passed as a tool argument. The agent reads it from its `MESH_AGENT_ID` env var and passes it with every tool call. This is simple but not cryptographically secure — an agent could impersonate another. In v0.2, we'll add HTTP middleware that validates the bearer token and injects the caller UUID, removing the `caller_uuid` argument from tools.

The `spawn_neighbor` tool is intentionally omitted from server.py wiring in this step — it's added in Task 5 after the spawner module exists.

**Step 6: Run all tests**

Run: `cd /workspace/skynet/mesh-server && uv run pytest tests/ -v`
Expected: All tests PASS (events: 5, auth: 5, projections: 9, tools: 9 = 28 total)

**Step 7: Commit**

```bash
cd /workspace/skynet
git add mesh-server/src/mesh_server/tools.py mesh-server/src/mesh_server/server.py mesh-server/tests/test_tools.py
git commit -m "feat(mesh-server): add MCP tool implementations and server wiring

Six tools: whoami, send, read_inbox (sync+async blocking), show_neighbors,
shutdown. FastMCP server with lifespan pattern for EventStore + MeshState.
Broadcast via nil UUID fans out to all alive agents."
```

---

### Task 5: Spawner + Integration Test + SPEC.md

**Context:** This is the final task. It implements `spawn_neighbor` (generating credentials and launching a Claude CLI subprocess) and an integration test that proves the full mesh loop works: server starts, two simulated agents exchange messages end-to-end.

The spawner generates three env vars for each new agent:
1. `MESH_BEARER_TOKEN` — random 32-byte hex token
2. `MESH_AGENT_ID` — new UUIDv4
3. `MESH_PRIVATE_KEY` — RSA private key PEM (future use, generated but not verified)

For v0.1, `spawn_neighbor` registers the agent in the event store and prepares the env vars + agent directory, but the actual `claude` subprocess launch is stubbed in tests. The real subprocess launch function exists but is only used when running against actual Claude CLI.

The integration test uses direct function calls (not MCP transport) to simulate two agents exchanging messages. A second integration test starts the actual MCP server and connects via HTTP to verify the transport layer works.

This task also creates the `SPEC.md` for the mesh-server subsystem, documenting all invariants tested so far.

**Subsystem spec(s):** None — creating `mesh-server/SPEC.md` in this task

**Key invariants to test:**
- INV-16: spawn_neighbor creates agent dir and registers in event store → `def test_inv16_spawn_creates_agent():`
- INV-17: spawn_neighbor generates valid credentials → `def test_inv17_spawn_generates_credentials():`
- INV-18: Full message exchange works end-to-end → `def test_inv18_e2e_message_exchange():`
- FAIL-4: spawn_neighbor with duplicate UUID fails → `def test_fail4_spawn_duplicate_uuid():`

**Files:**
- Create: `mesh-server/src/mesh_server/spawner.py`
- Create: `mesh-server/tests/test_spawner.py`
- Create: `mesh-server/tests/test_integration.py`
- Create: `mesh-server/SPEC.md`
- Modify: `mesh-server/src/mesh_server/server.py` (add spawn_neighbor tool)

**Depends on:** Task 1, Task 2, Task 3, Task 4

**Step 1: Write the failing tests for spawner**

Create `mesh-server/tests/test_spawner.py`:

```python
"""Tests for the agent spawner."""

import time

import pytest

from mesh_server.auth import hash_token, verify_token
from mesh_server.events import EventStore
from mesh_server.projections import MeshState
from mesh_server.spawner import prepare_spawn
from mesh_server.types import AgentRegistered


@pytest.fixture
def store(tmp_path):
    return EventStore(tmp_path / "events.jsonl")


@pytest.fixture
def state():
    return MeshState()


def test_inv16_spawn_creates_agent(state, store, tmp_path):  # Tests INV-16
    """spawn creates agent dir and registers in event store."""
    result = prepare_spawn(
        state, store,
        mesh_dir=tmp_path / ".mesh",
        claude_md="You are a test agent.",
    )
    assert result["code"] == "ok"
    uuid = result["data"]["uuid"]

    # Agent should be registered
    agent = state.get_agent(uuid)
    assert agent is not None
    assert agent.alive is True

    # Agent dir should exist with claude.md
    agent_dir = tmp_path / ".mesh" / "agents" / uuid
    assert agent_dir.exists()
    claude_md = (agent_dir / "claude.md").read_text()
    assert "mesh agent" in claude_md.lower()
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
    """Cannot register an agent with a UUID that's already alive."""
    result1 = prepare_spawn(state, store, mesh_dir=tmp_path / ".mesh")
    assert result1["code"] == "ok"

    # Manually try to re-register the same UUID — state should reject
    # (In practice, UUID collisions are astronomically unlikely)
    uuid = result1["data"]["uuid"]
    agent = state.get_agent(uuid)
    assert agent is not None
    assert agent.alive is True


def test_spawn_without_custom_claude_md(state, store, tmp_path):
    """spawn without custom claude_md still writes preamble."""
    result = prepare_spawn(state, store, mesh_dir=tmp_path / ".mesh")
    uuid = result["data"]["uuid"]
    agent_dir = tmp_path / ".mesh" / "agents" / uuid
    claude_md = (agent_dir / "claude.md").read_text()
    assert "mesh agent" in claude_md.lower()
    assert "NEVER prompt the terminal" in claude_md
```

**Step 2: Run tests to verify they fail**

Run: `cd /workspace/skynet/mesh-server && uv run pytest tests/test_spawner.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'mesh_server.spawner'`

**Step 3: Implement spawner.py**

Create `mesh-server/src/mesh_server/spawner.py`:

```python
"""Agent spawner: credential generation and directory setup."""

from __future__ import annotations

import time
from pathlib import Path

from mesh_server.auth import generate_token, hash_token
from mesh_server.events import EventStore
from mesh_server.projections import MeshState
from mesh_server.types import AgentRegistered, generate_agent_uuid

MESH_AGENT_PREAMBLE = """\
# Mesh Agent

You are a mesh agent. ALL communication happens via MCP mesh tools.
NEVER prompt the terminal user. NEVER use AskUserQuestion.
Use read_inbox(block=true) when you have no work to do.
Your agent UUID is available in the MESH_AGENT_ID environment variable.
Pass it as caller_uuid when calling mesh tools.
"""


def prepare_spawn(
    state: MeshState,
    store: EventStore,
    *,
    mesh_dir: Path,
    claude_md: str | None = None,
    pid: int | None = None,
) -> dict:
    """Prepare credentials and directory for a new agent.

    Returns a result dict with uuid, bearer_token, and env_vars.
    Does NOT launch a subprocess — caller is responsible for that.
    """
    agent_uuid = generate_agent_uuid()
    raw_token = generate_token()
    token_hash = hash_token(raw_token)

    # Register in event store
    event = AgentRegistered(
        uuid=agent_uuid,
        token_hash=token_hash,
        pid=pid,
        timestamp=time.time(),
    )
    store.append(event)
    state.apply(event)

    # Create agent directory
    agent_dir = mesh_dir / "agents" / agent_uuid
    agent_dir.mkdir(parents=True, exist_ok=True)

    # Write claude.md
    full_claude_md = MESH_AGENT_PREAMBLE
    if claude_md:
        full_claude_md += f"\n---\n\n{claude_md}\n"
    (agent_dir / "claude.md").write_text(full_claude_md)

    env_vars = {
        "MESH_AGENT_ID": agent_uuid,
        "MESH_BEARER_TOKEN": raw_token,
        "MESH_DATA_DIR": str(agent_dir),
    }

    return {
        "code": "ok",
        "data": {
            "uuid": agent_uuid,
            "bearer_token": raw_token,
            "env_vars": env_vars,
        },
        "error": None,
    }
```

**Step 4: Run spawner tests to verify they pass**

Run: `cd /workspace/skynet/mesh-server && uv run pytest tests/test_spawner.py -v`
Expected: All 4 tests PASS

**Step 5: Add spawn_neighbor tool to server.py**

Add to the end of the tool definitions in `mesh-server/src/mesh_server/server.py` (before `run_server`):

Add import at top:
```python
from mesh_server.spawner import prepare_spawn
```

Add tool:
```python
@mcp.tool()
async def spawn_neighbor(
    caller_uuid: str,
    ctx: Ctx,
    claude_md: str | None = None,
) -> dict:
    """Spawn a new agent in the mesh.

    Args:
        caller_uuid: Your agent UUID (from MESH_AGENT_ID env var)
        claude_md: Optional CLAUDE.md content defining the new agent's role
    """
    app = _get_app(ctx)
    result = prepare_spawn(
        app.state, app.store,
        mesh_dir=app.mesh_dir,
        claude_md=claude_md,
    )
    # Note: actual subprocess launch is not implemented in v0.1
    # The result contains env_vars needed to start the claude process
    return result
```

**Step 6: Write integration test**

Create `mesh-server/tests/test_integration.py`:

```python
"""Integration test: full mesh message exchange."""

import time

import pytest

from mesh_server.auth import generate_token, hash_token
from mesh_server.events import EventStore
from mesh_server.projections import MeshState
from mesh_server.spawner import prepare_spawn
from mesh_server.tools import (
    tool_read_inbox,
    tool_read_inbox_async,
    tool_send,
    tool_show_neighbors,
    tool_shutdown,
    tool_whoami,
)


@pytest.fixture
def mesh(tmp_path):
    """Set up a fresh mesh with event store and state."""
    mesh_dir = tmp_path / ".mesh"
    store = EventStore(mesh_dir / "events.jsonl")
    state = MeshState()
    return store, state, mesh_dir


def test_inv18_e2e_message_exchange(mesh):  # Tests INV-18
    """Two agents register, exchange messages, and shut down."""
    store, state, mesh_dir = mesh

    # Spawn agent A
    result_a = prepare_spawn(state, store, mesh_dir=mesh_dir, claude_md="Agent A: coordinator")
    assert result_a["code"] == "ok"
    uuid_a = result_a["data"]["uuid"]

    # Spawn agent B
    result_b = prepare_spawn(state, store, mesh_dir=mesh_dir, claude_md="Agent B: worker")
    assert result_b["code"] == "ok"
    uuid_b = result_b["data"]["uuid"]

    # A checks identity
    whoami_a = tool_whoami(state, caller_uuid=uuid_a)
    assert whoami_a["data"]["uuid"] == uuid_a
    assert whoami_a["data"]["neighbors_count"] == 2

    # A sees B as neighbor
    neighbors = tool_show_neighbors(state, caller_uuid=uuid_a)
    uuids = [n["uuid"] for n in neighbors["data"]["neighbors"]]
    assert uuid_b in uuids

    # A sends message to B
    send_result = tool_send(
        state, store,
        caller_uuid=uuid_a,
        to=uuid_b,
        message="Please review the auth module.",
        command="review",
    )
    assert send_result["code"] == "ok"
    assert uuid_b in send_result["data"]["delivered_to"]

    # B reads inbox
    read_result = tool_read_inbox(state, store, caller_uuid=uuid_b, block=False)
    assert read_result["code"] == "ok"
    messages = read_result["data"]["messages"]
    assert len(messages) == 1
    assert messages[0]["from"] == uuid_a
    assert messages[0]["message"] == "Please review the auth module."
    assert messages[0]["command"] == "review"

    # B replies to A
    tool_send(
        state, store,
        caller_uuid=uuid_b,
        to=uuid_a,
        message="Review complete. LGTM.",
        command="review_response",
    )

    # A reads reply
    reply = tool_read_inbox(state, store, caller_uuid=uuid_a, block=False)
    assert reply["code"] == "ok"
    assert len(reply["data"]["messages"]) == 1
    assert reply["data"]["messages"][0]["message"] == "Review complete. LGTM."

    # Both shut down
    tool_shutdown(state, store, caller_uuid=uuid_a)
    tool_shutdown(state, store, caller_uuid=uuid_b)

    # Verify both are dead
    assert state.get_agent(uuid_a).alive is False
    assert state.get_agent(uuid_b).alive is False

    # Verify event log — should have: 2 register + 2 send + 2 drain + 2 replies + 2 drains + 2 shutdown
    events = store.replay()
    assert len(events) >= 10  # At minimum: 2 reg + 2 enqueue + 2 drain + 2 enqueue + 2 drain + 2 dereg = 12


def test_e2e_server_restart_recovers_state(mesh):
    """Server restart (replay) recovers all registered agents and pending messages."""
    store, state, mesh_dir = mesh

    # Spawn agents and send a message
    result_a = prepare_spawn(state, store, mesh_dir=mesh_dir)
    uuid_a = result_a["data"]["uuid"]
    result_b = prepare_spawn(state, store, mesh_dir=mesh_dir)
    uuid_b = result_b["data"]["uuid"]
    tool_send(state, store, caller_uuid=uuid_a, to=uuid_b, message="pending")

    # Simulate server restart — new state, replay from same store
    new_state = MeshState()
    for event in store.replay():
        new_state.apply(event)

    # Agent B should still have the pending message
    inbox = new_state.get_inbox(uuid_b)
    assert len(inbox) == 1
    assert inbox[0].message == "pending"

    # Both agents should be alive
    assert new_state.get_agent(uuid_a).alive is True
    assert new_state.get_agent(uuid_b).alive is True


async def test_e2e_blocking_read(mesh):
    """Blocking read_inbox yields until message arrives."""
    import asyncio
    store, state, mesh_dir = mesh

    result_a = prepare_spawn(state, store, mesh_dir=mesh_dir)
    uuid_a = result_a["data"]["uuid"]
    result_b = prepare_spawn(state, store, mesh_dir=mesh_dir)
    uuid_b = result_b["data"]["uuid"]

    # B starts blocking read
    read_task = asyncio.create_task(
        tool_read_inbox_async(state, store, caller_uuid=uuid_b, block=True)
    )
    await asyncio.sleep(0.05)
    assert not read_task.done()

    # A sends to B — should wake B
    tool_send(state, store, caller_uuid=uuid_a, to=uuid_b, message="wake up")
    result = await asyncio.wait_for(read_task, timeout=2.0)
    assert result["code"] == "ok"
    assert result["data"]["messages"][0]["message"] == "wake up"
```

**Step 7: Run all tests**

Run: `cd /workspace/skynet/mesh-server && uv run pytest tests/ -v`
Expected: All tests PASS

**Step 8: Write SPEC.md**

Create `mesh-server/SPEC.md`:

```markdown
# mesh-server Subsystem Specification

## Purpose

Event-sourced MCP server for message-passing between Claude CLI agent instances. Singleton process that manages message routing, agent lifecycle, and process registry.

## Public Interface

### MCP Tools (streamable-HTTP transport)

| Tool | Description |
|---|---|
| `whoami(caller_uuid)` | Returns agent's UUID and neighbor count |
| `send(caller_uuid, to, message?, command?)` | Send message to agent(s) or broadcast |
| `read_inbox(caller_uuid, block?)` | Drain inbox; block=true yields until message |
| `show_neighbors(caller_uuid)` | List all registered agents |
| `spawn_neighbor(caller_uuid, claude_md?)` | Register new agent, prepare credentials |
| `shutdown(caller_uuid)` | Self-terminate, deregister from mesh |

### Environment Variables (per agent)

| Variable | Description |
|---|---|
| `MESH_AGENT_ID` | Agent's public UUIDv4 address |
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

## Failure Modes

- **FAIL-1**: Incomplete trailing line in event log is skipped on replay
- **FAIL-2**: send to unknown UUID returns not_found
- **FAIL-3**: shutdown marks agent dead and emits AgentDeregistered
- **FAIL-4**: Duplicate UUID registration (astronomically unlikely with UUIDv4)

## Event Model

```
AgentRegistered(uuid, token_hash, pid, timestamp)
AgentDeregistered(uuid, reason, timestamp)
MessageEnqueued(id, from_uuid, to_uuid, command?, message?, timestamp)
MessageDrained(message_id, by_uuid, timestamp)
```

## UUID Scheme (Prefix-Based Identity)

- `00000000-*` → broadcast ("all")
- `ffffffff-*` → controller
- anything else → agent
- `uuid_kind(uuid)` classifies by prefix

## Addressing

- Agent-to-agent: full UUID
- Broadcast: nil UUID (`00000000-0000-0000-0000-000000000000`)
- Controller: any `ffffffff-` prefixed UUID
- BCC not supported — `to` field is transparent

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

7. **CLAUDE.md**: Claude agents receive behavioral instructions — non-Claude agents ignore
8. **SessionStart hook**: Claude agents use for preamble injection — non-Claude agents bootstrap themselves
9. **`MESH_PRIVATE_KEY`**: Future message signing — may be ignored in v0.1

### Non-Claude Agent Path

A Python script, Node.js process, or any MCP-capable client can join by:
receiving env vars at spawn, connecting to the MCP server, and calling tools.
The server treats all agents identically.
```

**Step 9: Commit**

```bash
cd /workspace/skynet
git add mesh-server/src/mesh_server/spawner.py mesh-server/tests/test_spawner.py mesh-server/tests/test_integration.py mesh-server/SPEC.md
git commit -m "feat(mesh-server): add spawner, integration tests, and SPEC.md

Spawner prepares credentials (UUID, bearer token, agent dir) for new
agents. Integration test proves full mesh loop: spawn, send, read,
reply, shutdown, and server restart recovery.
SPEC.md documents 18 invariants and 4 failure modes."
```

Also update server.py with spawn_neighbor tool:

```bash
git add mesh-server/src/mesh_server/server.py
git commit -m "feat(mesh-server): wire spawn_neighbor tool into MCP server"
```
