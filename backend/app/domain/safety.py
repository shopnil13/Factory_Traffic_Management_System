from app.domain.config import JunctionConfig
from app.domain.model import Direction, JunctionState, Mode, Signal, StageKind


class SafetyViolation(Exception):
    """Raised when any traffic safety invariant is violated."""
    pass


def check_invariants(state: JunctionState, config: JunctionConfig) -> None:
    """
    Validates all safety invariants.
    Called before returning any new state, and in tests after every step.
    """
    # Invariant 6: mode == DEGRADED => desired signals are all RED
    if state.mode == Mode.DEGRADED:
        for direction, sig in state.desired_signals.items():
            if sig != Signal.RED:
                raise SafetyViolation(
                    f"DEGRADED invariant violated: direction {direction.value} has desired signal {sig.value}, must be RED"
                )

    # Invariant 1: no two directions in different phases are ever both desired GREEN
    green_directions = [
        d for d, s in state.desired_signals.items() if s == Signal.GREEN
    ]
    if green_directions:
        green_phases = {
            config.phase_for_direction(d) for d in green_directions
        }
        # Filter out None if any direction is not in config
        green_phases.discard(None)
        if len(green_phases) > 1:
            raise SafetyViolation(
                f"Conflicting GREEN invariant violated: multiple conflicting phases have GREEN desired signals: {green_phases}"
            )

    # Invariant 2: desired GREEN for phase q only if desired for all conflicting directions is RED
    for d in green_directions:
        conflicts = config.conflicting_directions(d)
        for conflict_d in conflicts:
            if state.desired_signals.get(conflict_d) != Signal.RED:
                raise SafetyViolation(
                    f"Invariant 2 violated: direction {d.value} is GREEN but conflicting direction {conflict_d.value} is desired {state.desired_signals.get(conflict_d)}"
                )

    # Invariant 3: desired GREEN for phase q only if actual for all conflicting directions == RED
    # This ensures GREEN cannot be commanded or held unless controller physically confirmed RED
    for d in green_directions:
        conflicts = config.conflicting_directions(d)
        for conflict_d in conflicts:
            actual = state.actual_signals.get(conflict_d)
            if actual != Signal.RED:
                raise SafetyViolation(
                    f"Invariant 3 violated: direction {d.value} has desired GREEN but conflicting direction {conflict_d.value} has actual status {actual} (must be RED)"
                )

    # Invariant 4: stage consistency - if stage is GREEN(p), desired non-phase directions must be RED
    if state.stage == StageKind.GREEN and state.active_phase:
        active_dirs = set(config.directions_for_phase(state.active_phase))
        for d, sig in state.desired_signals.items():
            if d not in active_dirs and sig != Signal.RED:
                raise SafetyViolation(
                    f"Stage invariant violated: stage is GREEN({state.active_phase}) but non-phase direction {d.value} is {sig.value}"
                )
    elif state.stage in (StageKind.YELLOW, StageKind.ALL_RED):
        # In ALL_RED, all desired signals must be RED
        if state.stage == StageKind.ALL_RED:
            for d, sig in state.desired_signals.items():
                if sig != Signal.RED:
                    raise SafetyViolation(
                        f"ALL_RED invariant violated: direction {d.value} has desired signal {sig.value}, must be RED"
                    )

    # Invariant 5: queue counts must be non-negative
    for direction, count in state.get_queue_counts().items():
        if count < 0:
            raise SafetyViolation(
                f"Queue invariant violated: direction {direction.value} has negative queue count {count}"
            )

    # Physical safety: no two directions in different phases are ever both actual GREEN
    actual_green_dirs = [
        d for d, s in state.actual_signals.items() if s == Signal.GREEN
    ]
    if actual_green_dirs:
        actual_green_phases = {
            config.phase_for_direction(d) for d in actual_green_dirs
        }
        actual_green_phases.discard(None)
        if len(actual_green_phases) > 1:
            raise SafetyViolation(
                f"Conflicting physical GREEN invariant violated: conflicting phases have actual GREEN signals: {actual_green_phases}"
            )
