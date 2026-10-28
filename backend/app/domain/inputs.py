from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from app.domain.model import Direction, Signal, VehicleType, DeviceStatus


@dataclass(frozen=True)
class Tick:
    now: datetime


@dataclass(frozen=True)
class ControllerAck:
    command_id: str
    junction_id: str
    direction: Direction
    reported_state: Signal
    status: str  # "SUCCESS" | "FAILED" / "NACK"
    received_at: datetime


@dataclass(frozen=True)
class SensorEvent:
    event_id: str
    junction_id: str
    event_type: str  # "VEHICLE_ARRIVED" | "VEHICLE_CLEARED"
    direction: Direction
    vehicle_id: str
    vehicle_type: Optional[VehicleType]
    sequence_no: int
    sensor_timestamp: datetime
    received_at: datetime


@dataclass(frozen=True)
class AdminCommand:
    command_type: str  # "MANUAL_GREEN_REQUEST" | "RETURN_TO_AUTOMATIC"
    junction_id: str
    direction: Optional[Direction] = None
    requested_by: str = "admin"
    received_at: Optional[datetime] = None


@dataclass(frozen=True)
class DeviceStatusUpdate:
    junction_id: str
    component_type: str  # "SIGNAL_CONTROLLER" | "SENSOR" | "SIGNAL"
    identifier: str      # "controller" or "NORTH", etc.
    status: DeviceStatus
    reported_at: datetime


@dataclass(frozen=True)
class Recover:
    junction_id: str
    now: datetime


DomainInput = Tick | ControllerAck | SensorEvent | AdminCommand | DeviceStatusUpdate | Recover
