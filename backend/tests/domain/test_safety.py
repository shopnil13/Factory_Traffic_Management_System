import pytest
from app.domain.config import JunctionConfig
from app.domain.model import Direction, JunctionState, Mode, Signal, StageKind
from app.domain.safety import SafetyViolation, check_invariants


def test_safety_catches_conflicting_desired_green():
    config = JunctionConfig(junction_id="J1", name="Junction 1")
    state = JunctionState(
        junction_id="J1",
        stage=StageKind.GREEN,
        desired_signals={
            Direction.NORTH: Signal.GREEN,
            Direction.SOUTH: Signal.GREEN,
            Direction.EAST: Signal.GREEN,  # Conflicting GREEN!
            Direction.WEST: Signal.RED,
        },
        actual_signals={d: Signal.RED for d in Direction},
    )
    with pytest.raises(SafetyViolation, match="Conflicting GREEN"):
        check_invariants(state, config)


def test_safety_catches_degraded_non_red():
    config = JunctionConfig(junction_id="J1", name="Junction 1")
    state = JunctionState(
        junction_id="J1",
        mode=Mode.DEGRADED,
        stage=StageKind.ALL_RED,
        desired_signals={
            Direction.NORTH: Signal.YELLOW,  # In DEGRADED all must be RED
            Direction.SOUTH: Signal.RED,
            Direction.EAST: Signal.RED,
            Direction.WEST: Signal.RED,
        },
        actual_signals={d: Signal.RED for d in Direction},
    )
    with pytest.raises(SafetyViolation, match="DEGRADED invariant violated"):
        check_invariants(state, config)


def test_safety_catches_desired_green_when_conflicting_actual_not_red():
    config = JunctionConfig(junction_id="J1", name="Junction 1")
    state = JunctionState(
        junction_id="J1",
        stage=StageKind.GREEN,
        active_phase="NORTH_SOUTH",
        desired_signals={
            Direction.NORTH: Signal.GREEN,
            Direction.SOUTH: Signal.GREEN,
            Direction.EAST: Signal.RED,
            Direction.WEST: Signal.RED,
        },
        actual_signals={
            Direction.NORTH: Signal.GREEN,
            Direction.SOUTH: Signal.GREEN,
            Direction.EAST: Signal.YELLOW,  # Actual is not RED!
            Direction.WEST: Signal.RED,
        },
    )
    with pytest.raises(SafetyViolation, match="Invariant 3 violated"):
        check_invariants(state, config)
