from datetime import datetime
from typing import Any, Optional
from pydantic import BaseModel, Field

from app.domain.model import DeviceStatus, Direction, Signal, VehicleType


class JunctionCreateSchema(BaseModel):
    junction_id: str = Field(..., description="Unique alphanumeric identifier for the junction")
    name: str = Field(..., description="Human-readable name")
    timing: Optional[dict[str, int]] = Field(default=None, description="Optional custom timing parameters")
    phases: Optional[dict[str, list[Direction]]] = Field(default=None, description="Optional phase definitions")


class SensorEventSchema(BaseModel):
    event_id: str
    junction_id: str
    event_type: str  # VEHICLE_ARRIVED | VEHICLE_CLEARED
    direction: Direction
    vehicle_id: str
    vehicle_type: Optional[VehicleType] = None
    sequence_no: int
    timestamp: datetime


class AdminCommandSchema(BaseModel):
    command_type: str  # MANUAL_GREEN_REQUEST | RETURN_TO_AUTOMATIC
    direction: Optional[Direction] = None
    requested_by: Optional[str] = "admin"


class ControllerAckSchema(BaseModel):
    command_id: str
    junction_id: str
    direction: Direction
    reported_state: Signal
    status: Optional[str] = "SUCCESS"


class DeviceStatusSchema(BaseModel):
    junction_id: str
    component_type: str  # SIGNAL_CONTROLLER | SENSOR | SIGNAL
    identifier: str
    status: DeviceStatus


class SimulatorConfigSchema(BaseModel):
    mode: str  # NORMAL | DELAYED | DROP | OFFLINE | WRONG_STATE
    delay_ms: Optional[int] = 50
    auto_ack: Optional[bool] = True
