"""Tests for in-memory projections."""

import time

from mesh_server.projections import MeshState
from mesh_server.types import (
    AgentDeregistered,
    AgentRegistered,
    AgentState,
    MessageDrained,
    MessageEnqueued,
)


def _reg(uuid: str = "agent-1", pid: int = 100) -> AgentRegistered:
    return AgentRegistered(
        uuid=uuid,
        token_hash={
            "scheme": "scrypt",
            "salt": "aa",
            "hash": "bb",
            "n": 16384,
            "r": 8,
            "p": 1,
        },
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
