import asyncio
from datetime import datetime, timezone
import json
import logging
from typing import Any, AsyncGenerator, Optional

from app.application.ports import EventPublisher

logger = logging.getLogger(__name__)


class SSEBroadcaster(EventPublisher):
    def __init__(self):
        self._subscribers: set[asyncio.Queue[str]] = set()

    async def publish(self, junction_id: str, event_type: str, data: dict[str, Any]) -> None:
        payload = {
            "junction_id": junction_id,
            "event_type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "data": data,
        }
        msg = f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"

        dead = set()
        for q in self._subscribers:
            try:
                q.put_nowait(msg)
            except asyncio.QueueFull:
                dead.add(q)
            except Exception:
                dead.add(q)

        for d in dead:
            self._subscribers.discard(d)

    async def event_generator(self) -> AsyncGenerator[str, None]:
        q: asyncio.Queue[str] = asyncio.Queue(maxsize=100)
        self._subscribers.add(q)
        try:
            # Send initial connection comment
            yield ": connected\n\n"
            while True:
                try:
                    msg = await asyncio.wait_for(q.get(), timeout=15.0)
                    yield msg
                except asyncio.TimeoutError:
                    yield ": heartbeat\n\n"
        finally:
            self._subscribers.discard(q)


sse_broadcaster = SSEBroadcaster()
