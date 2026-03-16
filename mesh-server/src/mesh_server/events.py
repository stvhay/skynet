"""Event types and append-only event store."""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
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
    """Append-only JSONL event log with crash recovery and pub/sub."""

    # Auto-remove subscribers after this many consecutive dropped events
    _MAX_DROPS = 10

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._subscribers: list[asyncio.Queue] = []
        self._drop_counts: dict[int, int] = {}  # id(queue) -> consecutive drops

    def subscribe(self, queue: asyncio.Queue) -> None:
        """Register a queue to receive all future appended events."""
        self._subscribers.append(queue)
        self._drop_counts[id(queue)] = 0

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Remove a queue from the subscriber list."""
        self._drop_counts.pop(id(queue), None)
        try:
            self._subscribers.remove(queue)
        except ValueError:
            pass

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

        # Notify subscribers (non-blocking); auto-remove stale ones
        stale: list[asyncio.Queue] = []
        for queue in self._subscribers:
            try:
                queue.put_nowait(event)
                self._drop_counts[id(queue)] = 0
            except asyncio.QueueFull:
                drops = self._drop_counts.get(id(queue), 0) + 1
                self._drop_counts[id(queue)] = drops
                if drops >= self._MAX_DROPS:
                    logging.warning(
                        "Event subscriber queue full for %d consecutive events — removing",
                        drops,
                    )
                    stale.append(queue)
                else:
                    logging.warning("Event subscriber queue full — event dropped")
        for queue in stale:
            self.unsubscribe(queue)

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
