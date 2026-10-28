from dataclasses import dataclass
from datetime import datetime
from typing import Any, Optional
from app.domain.model import Direction, Signal


@dataclass(frozen=True)
class SendControllerCommand:
    command_id: str
    junction_id: str
    direction: Direction
    requested_state: Signal
    issued_at: datetime


@dataclass(frozen=True)
class RecordAudit:
    junction_id: str
    server_ts: datetime
    event_type: str
    message: str
    sensor_ts: Optional[datetime] = None
    direction: Optional[Direction] = None
    previous_state: Optional[str] = None
    new_state: Optional[str] = None
    command_id: Optional[str] = None
    correlation_id: Optional[str] = None
    mode: Optional[str] = None
    details: Optional[dict[str, Any]] = None


@dataclass(frozen=True)
class ScheduleWakeup:
    at: datetime


@dataclass(frozen=True)
class PublishUpdate:
    junction_id: str


DomainEffect = SendControllerCommand | RecordAudit | ScheduleWakeup | PublishUpdate
