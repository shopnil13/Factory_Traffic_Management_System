from datetime import datetime, timezone, timedelta
from typing import Optional

from app.domain.config import JunctionConfig
from app.domain.effects import DomainEffect, RecordAudit
from app.domain.inputs import SensorEvent
from app.domain.model import (
    Direction,
    EmergencyRecord,
    EmergencyStatus,
    JunctionState,
    VehicleRecord,
    VehicleStatus,
    VehicleType,
)

MAX_STALE_SENSOR_SECONDS = 600       # 10 minutes
MAX_FUTURE_SKEW_SECONDS = 60         # 60 seconds


def process_sensor_event(
    state: JunctionState,
    config: JunctionConfig,
    event: SensorEvent,
    now: datetime,
) -> tuple[str, list[DomainEffect]]:
    """
    Processes vehicle arrival and clearance sensor events according to ordering,
    deduplication, and timestamp sanity rules.
    """
    effects: list[DomainEffect] = []

    # 1. Timestamp Sanity Check (sensor_ts is informational, server received_at is authoritative)
    skew_s = (event.sensor_timestamp - now).total_seconds()
    if skew_s > MAX_FUTURE_SKEW_SECONDS:
        effects.append(
            RecordAudit(
                junction_id=state.junction_id,
                server_ts=now,
                sensor_ts=event.sensor_timestamp,
                event_type="SENSOR_TIMESTAMP_CLOCK_SKEW",
                direction=event.direction,
                correlation_id=event.event_id,
                mode=state.mode.value,
                message=f"Sensor timestamp rejected due to clock skew: {skew_s:.1f}s in the future",
                details={"event_id": event.event_id, "vehicle_id": event.vehicle_id},
            )
        )
        return "REJECTED_CLOCK_SKEW", effects

    age_s = (now - event.sensor_timestamp).total_seconds()
    if age_s > MAX_STALE_SENSOR_SECONDS:
        effects.append(
            RecordAudit(
                junction_id=state.junction_id,
                server_ts=now,
                sensor_ts=event.sensor_timestamp,
                event_type="SENSOR_TIMESTAMP_STALE",
                direction=event.direction,
                correlation_id=event.event_id,
                mode=state.mode.value,
                message=f"Sensor event ignored due to stale timestamp: {age_s:.1f}s old",
                details={"event_id": event.event_id, "vehicle_id": event.vehicle_id},
            )
        )
        return "IGNORED_STALE", effects

    # 2. Exact Duplicate Check (by event_id)
    if event.event_id in state.processed_event_ids:
        effects.append(
            RecordAudit(
                junction_id=state.junction_id,
                server_ts=now,
                sensor_ts=event.sensor_timestamp,
                event_type="SENSOR_EVENT_DUPLICATE",
                direction=event.direction,
                correlation_id=event.event_id,
                mode=state.mode.value,
                message=f"Duplicate event_id {event.event_id} ignored",
                details={"vehicle_id": event.vehicle_id},
            )
        )
        return "DUPLICATE", effects

    # Mark event_id as processed
    state.processed_event_ids.add(event.event_id)

    # 3. Logical Duplicate / Sequence Ordering (per vehicle_id)
    existing_vehicle = state.vehicles.get(event.vehicle_id)

    if event.event_type == "VEHICLE_ARRIVED":
        if existing_vehicle is None:
            # First arrival of vehicle
            vehicle = VehicleRecord(
                junction_id=state.junction_id,
                vehicle_id=event.vehicle_id,
                direction=event.direction,
                vehicle_type=event.vehicle_type,
                status=VehicleStatus.WAITING,
                received_at=now,
                sensor_ts=event.sensor_timestamp,
                last_sequence_no=event.sequence_no,
            )
            state.vehicles[event.vehicle_id] = vehicle
            effects.append(
                RecordAudit(
                    junction_id=state.junction_id,
                    server_ts=now,
                    sensor_ts=event.sensor_timestamp,
                    event_type="VEHICLE_ARRIVED",
                    direction=event.direction,
                    correlation_id=event.event_id,
                    mode=state.mode.value,
                    message=f"Vehicle {event.vehicle_id} ({event.vehicle_type.value if event.vehicle_type else 'UNKNOWN'}) arrived at {event.direction.value}",
                    details={"queue_counts": {d.value: c for d, c in state.get_queue_counts().items()}},
                )
            )
            return "ACCEPTED", effects

        elif existing_vehicle.status == VehicleStatus.WAITING:
            # Vehicle is already waiting! Logical duplicate
            effects.append(
                RecordAudit(
                    junction_id=state.junction_id,
                    server_ts=now,
                    sensor_ts=event.sensor_timestamp,
                    event_type="VEHICLE_ALREADY_WAITING",
                    direction=event.direction,
                    correlation_id=event.event_id,
                    mode=state.mode.value,
                    message=f"Vehicle {event.vehicle_id} already WAITING at {existing_vehicle.direction.value}; treated as duplicate",
                )
            )
            return "DUPLICATE", effects

        elif existing_vehicle.status == VehicleStatus.CLEARED:
            # Vehicle has a CLEARED record. Compare sequence numbers
            if event.sequence_no <= existing_vehicle.last_sequence_no:
                # Arrival was delayed and arrived after clearance! Out of order
                effects.append(
                    RecordAudit(
                        junction_id=state.junction_id,
                        server_ts=now,
                        sensor_ts=event.sensor_timestamp,
                        event_type="SENSOR_OUT_OF_ORDER_ARRIVAL",
                        direction=event.direction,
                        correlation_id=event.event_id,
                        mode=state.mode.value,
                        message=f"Delayed arrival for vehicle {event.vehicle_id} (seq {event.sequence_no} <= cleared seq {existing_vehicle.last_sequence_no}) ignored; queue unchanged",
                    )
                )
                return "IGNORED_OUT_OF_ORDER", effects
            else:
                # Vehicle returns on a new trip with higher sequence_no
                existing_vehicle.direction = event.direction
                existing_vehicle.vehicle_type = event.vehicle_type
                existing_vehicle.status = VehicleStatus.WAITING
                existing_vehicle.received_at = now
                existing_vehicle.sensor_ts = event.sensor_timestamp
                existing_vehicle.last_sequence_no = event.sequence_no
                effects.append(
                    RecordAudit(
                        junction_id=state.junction_id,
                        server_ts=now,
                        sensor_ts=event.sensor_timestamp,
                        event_type="VEHICLE_REARRIVED",
                        direction=event.direction,
                        correlation_id=event.event_id,
                        mode=state.mode.value,
                        message=f"Vehicle {event.vehicle_id} returned to {event.direction.value} with new seq {event.sequence_no}",
                    )
                )
                return "ACCEPTED", effects

        else:  # EXPIRED
            existing_vehicle.direction = event.direction
            existing_vehicle.vehicle_type = event.vehicle_type
            existing_vehicle.status = VehicleStatus.WAITING
            existing_vehicle.received_at = now
            existing_vehicle.sensor_ts = event.sensor_timestamp
            existing_vehicle.last_sequence_no = event.sequence_no
            return "ACCEPTED", effects

    elif event.event_type == "VEHICLE_CLEARED":
        if existing_vehicle is None:
            # Cleared without arrival! Create tombstone
            tombstone = VehicleRecord(
                junction_id=state.junction_id,
                vehicle_id=event.vehicle_id,
                direction=event.direction,
                vehicle_type=event.vehicle_type,
                status=VehicleStatus.CLEARED,
                received_at=now,
                sensor_ts=event.sensor_timestamp,
                last_sequence_no=event.sequence_no,
            )
            state.vehicles[event.vehicle_id] = tombstone
            effects.append(
                RecordAudit(
                    junction_id=state.junction_id,
                    server_ts=now,
                    sensor_ts=event.sensor_timestamp,
                    event_type="CLEARED_WITHOUT_ARRIVAL",
                    direction=event.direction,
                    correlation_id=event.event_id,
                    mode=state.mode.value,
                    message=f"Warning: vehicle {event.vehicle_id} cleared without an arrival event; tombstone created, queue count unchanged",
                )
            )
            return "ACCEPTED", effects

        elif existing_vehicle.status == VehicleStatus.WAITING:
            if event.sequence_no < existing_vehicle.last_sequence_no:
                effects.append(
                    RecordAudit(
                        junction_id=state.junction_id,
                        server_ts=now,
                        sensor_ts=event.sensor_timestamp,
                        event_type="SENSOR_OUT_OF_ORDER_CLEARANCE",
                        direction=event.direction,
                        correlation_id=event.event_id,
                        mode=state.mode.value,
                        message=f"Clearance for {event.vehicle_id} has stale seq {event.sequence_no} < arrival seq {existing_vehicle.last_sequence_no}; ignored",
                    )
                )
                return "IGNORED_OUT_OF_ORDER", effects
            else:
                existing_vehicle.status = VehicleStatus.CLEARED
                existing_vehicle.last_sequence_no = event.sequence_no
                effects.append(
                    RecordAudit(
                        junction_id=state.junction_id,
                        server_ts=now,
                        sensor_ts=event.sensor_timestamp,
                        event_type="VEHICLE_CLEARED",
                        direction=event.direction,
                        correlation_id=event.event_id,
                        mode=state.mode.value,
                        message=f"Vehicle {event.vehicle_id} cleared from {existing_vehicle.direction.value}",
                        details={"queue_counts": {d.value: c for d, c in state.get_queue_counts().items()}},
                    )
                )
                return "ACCEPTED", effects

        elif existing_vehicle.status == VehicleStatus.CLEARED:
            # Already cleared
            return "DUPLICATE", effects

        else:
            existing_vehicle.status = VehicleStatus.CLEARED
            return "ACCEPTED", effects

    return "UNKNOWN_EVENT_TYPE", effects


def expire_ghost_vehicles(
    state: JunctionState,
    config: JunctionConfig,
    now: datetime,
) -> list[DomainEffect]:
    """Expires any waiting vehicle exceeding vehicle_ttl_s to prevent ghost queues."""
    effects: list[DomainEffect] = []
    ttl = config.timing.vehicle_ttl_s

    for v in state.vehicles.values():
        if v.status == VehicleStatus.WAITING and v.received_at:
            wait_s = (now - v.received_at).total_seconds()
            if wait_s > ttl:
                v.status = VehicleStatus.EXPIRED
                effects.append(
                    RecordAudit(
                        junction_id=state.junction_id,
                        server_ts=now,
                        event_type="GHOST_VEHICLE_EXPIRED",
                        direction=v.direction,
                        mode=state.mode.value,
                        message=f"Vehicle {v.vehicle_id} expired after waiting {wait_s:.0f}s (exceeded TTL {ttl}s); purged from queue",
                        details={"vehicle_id": v.vehicle_id, "direction": v.direction.value},
                    )
                )
    return effects
