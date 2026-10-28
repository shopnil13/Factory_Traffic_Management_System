from datetime import datetime
from typing import Optional

from app.domain.config import JunctionConfig
from app.domain.model import (
    DeviceStatus,
    Direction,
    JunctionState,
    VehicleRecord,
    VehicleStatus,
    VehicleType,
)

VEHICLE_WEIGHTS: dict[VehicleType, float] = {
    VehicleType.EMERGENCY: 50.0,
    VehicleType.TRUCK: 3.0,
    VehicleType.FORKLIFT: 2.0,
    VehicleType.EMPLOYEE_VEHICLE: 1.0,
}
DEFAULT_WEIGHT: float = 1.0
PHANTOM_SENSOR_OFFLINE_SCORE: float = 3.0


def calculate_phase_score(
    state: JunctionState,
    config: JunctionConfig,
    phase: str,
    now: datetime,
) -> float:
    """
    Computes priority score for a phase:
    score = sum(weight(type) * (1 + age_s / 60))
    Includes phantom score if any sensor in phase is OFFLINE.
    """
    phase_dirs = config.directions_for_phase(phase)
    score = 0.0

    for d in phase_dirs:
        # Check sensor status
        sensor_status = state.device_status.get(f"sensor_{d.value}", DeviceStatus.UNKNOWN)
        if sensor_status == DeviceStatus.OFFLINE:
            score += PHANTOM_SENSOR_OFFLINE_SCORE

        # Add waiting vehicles
        for v in state.get_waiting_vehicles(direction=d):
            w = VEHICLE_WEIGHTS.get(v.vehicle_type, DEFAULT_WEIGHT) if v.vehicle_type else DEFAULT_WEIGHT
            age_s = (now - v.received_at).total_seconds() if v.received_at else 0.0
            if age_s < 0:
                age_s = 0.0
            score += w * (1.0 + (age_s / 60.0))

    return score


def get_oldest_waiting_age_s(
    state: JunctionState,
    config: JunctionConfig,
    phase: str,
    now: datetime,
) -> float:
    """Returns the age in seconds of the oldest waiting vehicle in the phase, or 0.0."""
    phase_dirs = config.directions_for_phase(phase)
    oldest_age = 0.0

    for d in phase_dirs:
        for v in state.get_waiting_vehicles(direction=d):
            if v.received_at:
                age_s = (now - v.received_at).total_seconds()
                if age_s > oldest_age:
                    oldest_age = age_s
    return oldest_age


def phase_has_demand(
    state: JunctionState,
    config: JunctionConfig,
    phase: str,
) -> bool:
    """Returns True if phase has any waiting vehicles or an offline sensor."""
    phase_dirs = config.directions_for_phase(phase)
    for d in phase_dirs:
        if state.device_status.get(f"sensor_{d.value}") == DeviceStatus.OFFLINE:
            return True
        if len(state.get_waiting_vehicles(direction=d)) > 0:
            return True
    return False


def select_best_candidate_phase(
    state: JunctionState,
    config: JunctionConfig,
    exclude_phase: Optional[str],
    now: datetime,
) -> Optional[str]:
    """Selects the highest scoring competing phase, breaking ties with oldest wait, then config order."""
    candidates = [p for p in config.phases.keys() if p != exclude_phase]
    if not candidates:
        return None

    def candidate_key(p: str):
        score = calculate_phase_score(state, config, p, now)
        oldest_age = get_oldest_waiting_age_s(state, config, p, now)
        return (score, oldest_age)

    best_phase = max(candidates, key=candidate_key)
    return best_phase


def should_switch_phase(
    state: JunctionState,
    config: JunctionConfig,
    current_phase: str,
    now: datetime,
    green_elapsed_s: float,
) -> tuple[bool, Optional[str], str]:
    """
    Evaluates whether to switch away from current green phase according to Section 7.1.
    Returns (should_switch, target_phase, reason).
    """
    # Invariant: Must satisfy green_min_s in automatic mode
    if green_elapsed_s < config.timing.green_min_s:
        return False, None, "Green minimum time not met"

    competing_phases = [p for p in config.phases.keys() if p != current_phase]
    if not competing_phases:
        return False, None, "No competing phases"

    # Rule 1: No demand on other phases -> stay
    any_competing_demand = any(phase_has_demand(state, config, p) for p in competing_phases)
    if not any_competing_demand:
        return False, None, "No demand on competing phases; staying green"

    best_other = select_best_candidate_phase(state, config, current_phase, now)
    if not best_other:
        return False, None, "No candidate phase"

    # Rule 2: Starvation protection
    # Check if any competing phase is starved (oldest wait > starvation_max_wait_s,
    # or phase not served for that long while having demand)
    for p in competing_phases:
        if phase_has_demand(state, config, p):
            oldest_wait = get_oldest_waiting_age_s(state, config, p, now)
            last_green = state.phase_last_green_at.get(p)
            ref_time = last_green or state.stage_started_at or now
            unserved_s = (now - ref_time).total_seconds()

            if oldest_wait >= config.timing.starvation_max_wait_s or unserved_s >= config.timing.starvation_max_wait_s:
                return True, p, f"Starvation override: phase {p} starved (wait: {oldest_wait:.1f}s, unserved: {unserved_s:.1f}s)"

    # Rule 3: green_elapsed >= green_max_s and competing demand exists
    if green_elapsed_s >= config.timing.green_max_s:
        return True, best_other, f"Max green exceeded ({green_elapsed_s:.1f}s >= {config.timing.green_max_s}s) with competing demand"

    # Rule 4: Gap-out (current phase empty and competing phase has demand)
    curr_has_demand = phase_has_demand(state, config, current_phase)
    if not curr_has_demand:
        return True, best_other, f"Current phase {current_phase} has no demand; gapping out to {best_other}"

    # Rule 5: Hysteresis (score(other) > 1.25 * score(current))
    curr_score = calculate_phase_score(state, config, current_phase, now)
    other_score = calculate_phase_score(state, config, best_other, now)

    if other_score > (1.25 * curr_score):
        return True, best_other, f"Demand score switch: competing {best_other} ({other_score:.2f}) > 1.25 * current ({curr_score:.2f})"

    # Rule 6: Otherwise stay
    return False, None, f"Current phase retains priority ({curr_score:.2f} vs {other_score:.2f})"
