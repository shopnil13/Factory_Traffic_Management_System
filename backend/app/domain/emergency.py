from datetime import datetime, timedelta
from typing import Optional

from app.domain.config import JunctionConfig
from app.domain.effects import DomainEffect, RecordAudit
from app.domain.model import (
    Direction,
    EmergencyRecord,
    EmergencyStatus,
    JunctionState,
    Mode,
    VehicleStatus,
    VehicleType,
)


def register_emergency(
    state: JunctionState,
    config: JunctionConfig,
    vehicle_id: str,
    direction: Direction,
    now: datetime,
) -> tuple[EmergencyRecord, list[DomainEffect]]:
    """Registers or refreshes an emergency vehicle arrival."""
    effects: list[DomainEffect] = []

    # Check if already registered
    existing = next((e for e in state.emergencies if e.vehicle_id == vehicle_id), None)
    if existing:
        existing.last_seen_at = now
        if existing.status == EmergencyStatus.EXPIRED:
            existing.status = EmergencyStatus.ACTIVE
        return existing, effects

    existing_ids = [e.id for e in state.emergencies if e.id is not None]
    next_id = (max(existing_ids) + 1) if existing_ids else 1
    record = EmergencyRecord(
        id=next_id,
        junction_id=state.junction_id,
        direction=direction,
        vehicle_id=vehicle_id,
        status=EmergencyStatus.ACTIVE,
        detected_at=now,
        last_seen_at=now,
    )
    state.emergencies.append(record)

    effects.append(
        RecordAudit(
            junction_id=state.junction_id,
            server_ts=now,
            event_type="EMERGENCY_DETECTED",
            direction=direction,
            mode=state.mode.value,
            message=f"Emergency vehicle {vehicle_id} detected at {direction.value}; queued in FIFO priority",
            details={"emergency_id": next_id, "vehicle_id": vehicle_id},
        )
    )
    return record, effects


def clear_emergency(
    state: JunctionState,
    config: JunctionConfig,
    vehicle_id: str,
    now: datetime,
) -> list[DomainEffect]:
    """Marks an emergency as CLEARED when the vehicle leaves."""
    effects: list[DomainEffect] = []
    record = next((e for e in state.emergencies if e.vehicle_id == vehicle_id), None)
    if record and record.status in (EmergencyStatus.ACTIVE, EmergencyStatus.SERVING):
        record.status = EmergencyStatus.CLEARED
        effects.append(
            RecordAudit(
                junction_id=state.junction_id,
                server_ts=now,
                event_type="EMERGENCY_CLEARED",
                direction=record.direction,
                mode=state.mode.value,
                message=f"Emergency vehicle {vehicle_id} cleared from {record.direction.value}",
                details={"emergency_id": record.id},
            )
        )
    return effects


def evaluate_emergencies(
    state: JunctionState,
    config: JunctionConfig,
    now: datetime,
) -> tuple[Optional[EmergencyRecord], list[DomainEffect]]:
    """
    Evaluates emergency list for timeouts and selects the next emergency to serve via FIFO.
    - Stale timeout: marks stale emergencies as EXPIRED if not refreshed for emergency_stale_s.
    - Max hold: if served for > emergency_max_hold_s, expires or steps aside for next in FIFO.
    """
    effects: list[DomainEffect] = []
    stale_limit = config.timing.emergency_stale_s
    max_hold = config.timing.emergency_max_hold_s

    # 1. Check stale and max hold timeouts
    for em in state.emergencies:
        if em.status in (EmergencyStatus.ACTIVE, EmergencyStatus.SERVING):
            # Check stale
            stale_s = (now - em.last_seen_at).total_seconds()
            if stale_s >= stale_limit:
                em.status = EmergencyStatus.EXPIRED
                effects.append(
                    RecordAudit(
                        junction_id=state.junction_id,
                        server_ts=now,
                        event_type="EMERGENCY_EXPIRED_STALE",
                        direction=em.direction,
                        mode=state.mode.value,
                        message=f"Emergency {em.vehicle_id} expired due to stale detection ({stale_s:.0f}s >= {stale_limit}s)",
                        details={"emergency_id": em.id},
                    )
                )
                continue

            # Check max hold for currently serving emergency
            if em.status == EmergencyStatus.SERVING and em.serving_since:
                held_s = (now - em.serving_since).total_seconds()
                if held_s >= max_hold:
                    em.status = EmergencyStatus.EXPIRED
                    effects.append(
                        RecordAudit(
                            junction_id=state.junction_id,
                            server_ts=now,
                            event_type="EMERGENCY_MAX_HOLD_EXCEEDED",
                            direction=em.direction,
                            mode=state.mode.value,
                            message=f"Emergency {em.vehicle_id} exceeded maximum hold duration ({held_s:.0f}s >= {max_hold}s); yielding preemption",
                            details={"emergency_id": em.id},
                        )
                    )

    # 2. Pick next active/serving emergency in FIFO order
    eligible = [
        e for e in state.emergencies
        if e.status in (EmergencyStatus.ACTIVE, EmergencyStatus.SERVING)
    ]
    if not eligible:
        return None, effects

    # Sort by ID (FIFO)
    eligible.sort(key=lambda e: e.id)
    return eligible[0], effects


def has_active_emergency(state: JunctionState) -> bool:
    """Returns True if any unexpired emergency is present."""
    return any(
        e.status in (EmergencyStatus.ACTIVE, EmergencyStatus.SERVING)
        for e in state.emergencies
    )
