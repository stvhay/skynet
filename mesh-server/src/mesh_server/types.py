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
