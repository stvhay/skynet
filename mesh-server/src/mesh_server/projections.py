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
    - registry: uuid -> AgentInfo
    - inboxes: uuid -> list[Message]  (undelivered)
    - waiters: uuid -> asyncio.Event  (ephemeral, not persisted)
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
