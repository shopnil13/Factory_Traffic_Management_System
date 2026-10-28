from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Optional


class Direction(str, Enum):
    NORTH = "NORTH"
    SOUTH = "SOUTH"
    EAST = "EAST"
    WEST = "WEST"


class Signal(str, Enum):
    RED = "RED"
    YELLOW = "YELLOW"
    GREEN = "GREEN"
    UNKNOWN = "UNKNOWN"  # Physical/actual only, never desired


class Mode(str, Enum):
    AUTOMATIC = "AUTOMATIC"
    MANUAL = "MANUAL"
    EMERGENCY = "EMERGENCY"
    DEGRADED = "DEGRADED"


class StageKind(str, Enum):
    GREEN = "GREEN"
    YELLOW = "YELLOW"
    ALL_RED = "ALL_RED"


class StageStatus(str, Enum):
    AWAITING_ACK = "AWAITING_ACK"
    TIMING = "TIMING"


class DeviceStatus(str, Enum):
    ONLINE = "ONLINE"
    OFFLINE = "OFFLINE"
    DEGRADED = "DEGRADED"
    WARNING = "WARNING"
    UNKNOWN = "UNKNOWN"


class VehicleType(str, Enum):
    EMERGENCY = "EMERGENCY"
    TRUCK = "TRUCK"
    FORKLIFT = "FORKLIFT"
    EMPLOYEE_VEHICLE = "EMPLOYEE_VEHICLE"


class VehicleStatus(str, Enum):
    WAITING = "WAITING"
    CLEARED = "CLEARED"
    EXPIRED = "EXPIRED"


class CommandStatus(str, Enum):
    PENDING = "PENDING"
    ACKED = "ACKED"
    FAILED = "FAILED"
    SUPERSEDED = "SUPERSEDED"


class EmergencyStatus(str, Enum):
    ACTIVE = "ACTIVE"
    SERVING = "SERVING"
    CLEARED = "CLEARED"
    EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class PendingCommand:
    command_id: str
    junction_id: str
    direction: Direction
    requested_state: Signal
    stage: str
    attempts: int
    sent_at: datetime
    status: CommandStatus = CommandStatus.PENDING


@dataclass
class VehicleRecord:
    junction_id: str
    vehicle_id: str
    direction: Direction
    vehicle_type: Optional[VehicleType]
    status: VehicleStatus
    received_at: Optional[datetime]
    sensor_ts: Optional[datetime]
    last_sequence_no: int


@dataclass
class EmergencyRecord:
    id: int
    junction_id: str
    direction: Direction
    vehicle_id: str
    status: EmergencyStatus
    detected_at: datetime
    last_seen_at: datetime
    serving_since: Optional[datetime] = None


@dataclass
class JunctionState:
    junction_id: str
    version: int = 1
    mode: Mode = Mode.AUTOMATIC
    suspended_mode: Optional[Mode] = None
    stage: StageKind = StageKind.ALL_RED
    stage_status: StageStatus = StageStatus.AWAITING_ACK
    active_phase: Optional[str] = None
    target_phase: Optional[str] = None
    stage_started_at: Optional[datetime] = None
    stage_timer_started_at: Optional[datetime] = None

    desired_signals: dict[Direction, Signal] = field(
        default_factory=lambda: {d: Signal.RED for d in Direction}
    )
    actual_signals: dict[Direction, Signal] = field(
        default_factory=lambda: {d: Signal.UNKNOWN for d in Direction}
    )
    pending_commands: dict[str, PendingCommand] = field(default_factory=dict)

    controller_status: DeviceStatus = DeviceStatus.UNKNOWN
    device_status: dict[str, DeviceStatus] = field(
        default_factory=lambda: {
            "controller": DeviceStatus.UNKNOWN,
            **{f"sensor_{d.value}": DeviceStatus.UNKNOWN for d in Direction},
            **{f"signal_{d.value}": DeviceStatus.UNKNOWN for d in Direction},
        }
    )

    manual_owner: Optional[str] = None
    manual_direction: Optional[Direction] = None
    manual_expires_at: Optional[datetime] = None

    phase_last_green_at: dict[str, datetime] = field(default_factory=dict)
    last_processed_seq: dict[Direction, int] = field(default_factory=dict)

    vehicles: dict[str, VehicleRecord] = field(default_factory=dict)
    emergencies: list[EmergencyRecord] = field(default_factory=list)
    processed_event_ids: set[str] = field(default_factory=set)

    updated_at: Optional[datetime] = None

    def get_queue_counts(self) -> dict[Direction, int]:
        """Calculates derived waiting vehicle queue count per direction."""
        counts = {d: 0 for d in Direction}
        for v in self.vehicles.values():
            if v.status == VehicleStatus.WAITING:
                counts[v.direction] += 1
        return counts

    def get_waiting_vehicles(self, direction: Optional[Direction] = None) -> list[VehicleRecord]:
        """Returns list of waiting vehicles, optionally filtered by direction."""
        if direction is not None:
            return [v for v in self.vehicles.values() if v.status == VehicleStatus.WAITING and v.direction == direction]
        return [v for v in self.vehicles.values() if v.status == VehicleStatus.WAITING]
