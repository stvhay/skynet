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
