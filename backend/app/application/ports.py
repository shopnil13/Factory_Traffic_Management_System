from dataclasses import dataclass
from datetime import datetime
from typing import Any, Protocol
from app.domain.model import Direction, Signal


class ControllerUnavailable(Exception):
    """Raised when the controller adapter cannot reach the controller."""
    pass


@dataclass(frozen=True)
class ControllerCommand:
    command_id: str
    junction_id: str
    direction: Direction
    requested_state: Signal
    issued_at: datetime


class ControllerPort(Protocol):
    async def send(self, command: ControllerCommand) -> None:
        """Sends command to physical/simulated controller. Raises ControllerUnavailable if unreachable."""
        ...


class EventPublisher(Protocol):
    async def publish(self, junction_id: str, event_type: str, data: dict[str, Any]) -> None:
        """Publishes real-time event (e.g. via SSE or websocket) to subscribers."""
        ...
