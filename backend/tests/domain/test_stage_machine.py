from datetime import datetime, timezone, timedelta
import pytest
from app.domain.config import JunctionConfig, TimingConfig
from app.domain.engine import TrafficEngine
from app.domain.inputs import ControllerAck, Recover, SensorEvent, Tick
from app.domain.model import (
    CommandStatus,
    Direction,
    JunctionState,
    Mode,
    Signal,
    StageKind,
    StageStatus,
    VehicleType,
)
from app.domain.safety import SafetyViolation, check_invariants


def test_recovery_initializes_safe_all_red():
    engine = TrafficEngine()
    config = JunctionConfig(junction_id="J1", name="Junction 1")
    t0 = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)

    state = JunctionState(junction_id="J1")
    result = engine.handle(state, config, Recover(junction_id="J1", now=t0), t0)

    # All actual signals must be UNKNOWN
    for d in Direction:
        assert result.state.actual_signals[d] == Signal.UNKNOWN
        assert result.state.desired_signals[d] == Signal.RED

    assert result.state.stage == StageKind.ALL_RED
    assert result.state.stage_status == StageStatus.AWAITING_ACK
    assert len(result.state.pending_commands) == 4  # 4 directions commanded to RED


def test_ack_gating_stage_status_timing():
    engine = TrafficEngine()
    config = JunctionConfig(junction_id="J1", name="Junction 1")
    t0 = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)

    state = JunctionState(junction_id="J1")
    engine.handle(state, config, Recover(junction_id="J1", now=t0), t0)

    # Awaiting ACKs; stage timer should not have started
    assert state.stage_status == StageStatus.AWAITING_ACK
    assert state.stage_timer_started_at is None

    # ACK 3 directions
    pending_ids = list(state.pending_commands.keys())
    for cmd_id in pending_ids[:3]:
        cmd = state.pending_commands[cmd_id]
        t1 = t0 + timedelta(milliseconds=100)
        engine.handle(
            state,
            config,
            ControllerAck(
                command_id=cmd_id,
                junction_id="J1",
                direction=cmd.direction,
                reported_state=Signal.RED,
                status="SUCCESS",
                received_at=t1,
            ),
            t1,
        )

    # Still waiting for 4th ACK
    assert state.stage_status == StageStatus.AWAITING_ACK
    assert state.stage_timer_started_at is None

    # ACK the 4th command
    last_cmd_id = pending_ids[3]
    last_cmd = state.pending_commands[last_cmd_id]
    t2 = t0 + timedelta(milliseconds=200)
    engine.handle(
        state,
        config,
        ControllerAck(
            command_id=last_cmd_id,
            junction_id="J1",
            direction=last_cmd.direction,
            reported_state=Signal.RED,
            status="SUCCESS",
            received_at=t2,
        ),
        t2,
    )

    # All ACKed -> stage status TIMING, timer started
    assert state.stage_status == StageStatus.TIMING
    assert state.stage_timer_started_at == t2
    assert len(state.pending_commands) == 0


def test_green_not_issued_until_conflicting_actual_red():
    engine = TrafficEngine()
    config = JunctionConfig(junction_id="J1", name="Junction 1")
    t0 = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)

    # Manually setup ALL_RED TIMING, but with EAST actual signal still GREEN
    state = JunctionState(
        junction_id="J1",
        stage=StageKind.ALL_RED,
        stage_status=StageStatus.TIMING,
        stage_started_at=t0,
        stage_timer_started_at=t0,
        desired_signals={d: Signal.RED for d in Direction},
        actual_signals={
            Direction.NORTH: Signal.RED,
            Direction.SOUTH: Signal.RED,
            Direction.EAST: Signal.GREEN,  # Conflicting actual signal not RED
            Direction.WEST: Signal.RED,
        },
    )

    # Advance time beyond all_red_s
    t_after = t0 + timedelta(seconds=config.timing.all_red_s + 1)
    res = engine.handle(state, config, Tick(now=t_after), t_after)

    # Stage should NOT transition to GREEN(NORTH_SOUTH) because EAST is still actual GREEN
    assert res.state.stage == StageKind.ALL_RED
    assert res.state.desired_signals[Direction.NORTH] == Signal.RED


def test_full_stage_cycle():
    engine = TrafficEngine()
    timing = TimingConfig(green_min_s=5, green_max_s=15, yellow_s=3, all_red_s=2)
    config = JunctionConfig(junction_id="J1", name="Junction 1", timing=timing)
    t = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)

    state = JunctionState(
        junction_id="J1",
        stage=StageKind.ALL_RED,
        stage_status=StageStatus.TIMING,
        stage_started_at=t,
        stage_timer_started_at=t,
        desired_signals={d: Signal.RED for d in Direction},
        actual_signals={d: Signal.RED for d in Direction},
    )

    # 1. Advance past ALL_RED -> Enters GREEN(NORTH_SOUTH) AWAITING_ACK
    t = t + timedelta(seconds=3)
    engine.handle(state, config, Tick(now=t), t)
    assert state.stage == StageKind.GREEN
    assert state.active_phase == "NORTH_SOUTH"
    assert state.stage_status == StageStatus.AWAITING_ACK
    assert state.desired_signals[Direction.NORTH] == Signal.GREEN
    assert state.desired_signals[Direction.SOUTH] == Signal.GREEN

    # 2. ACK GREEN commands
    for cmd_id in list(state.pending_commands.keys()):
        cmd = state.pending_commands[cmd_id]
        engine.handle(
            state,
            config,
            ControllerAck(
                command_id=cmd_id,
                junction_id="J1",
                direction=cmd.direction,
                reported_state=Signal.GREEN,
                status="SUCCESS",
                received_at=t,
            ),
            t,
        )
    assert state.stage_status == StageStatus.TIMING

    # 3. Tick before green_max_s -> stays in GREEN
    t = t + timedelta(seconds=10)
    engine.handle(state, config, Tick(now=t), t)
    assert state.stage == StageKind.GREEN

    # Add demand on EAST so it switches when green_max_s is hit
    engine.handle(
        state,
        config,
        SensorEvent(
            event_id="e-east",
            junction_id="J1",
            event_type="VEHICLE_ARRIVED",
            direction=Direction.EAST,
            vehicle_id="TRUCK-E",
            vehicle_type=VehicleType.TRUCK,
            sequence_no=1,
            sensor_timestamp=t,
            received_at=t,
        ),
        t,
    )

    # 4. Tick at green_max_s -> enters YELLOW
    t = t + timedelta(seconds=6)  # Total 16s > green_max_s
    engine.handle(state, config, Tick(now=t), t)
    assert state.stage == StageKind.YELLOW
    assert state.stage_status == StageStatus.AWAITING_ACK
    assert state.desired_signals[Direction.NORTH] == Signal.YELLOW

    # 5. ACK YELLOW commands
    for cmd_id in list(state.pending_commands.keys()):
        cmd = state.pending_commands[cmd_id]
        engine.handle(
            state,
            config,
            ControllerAck(
                command_id=cmd_id,
                junction_id="J1",
                direction=cmd.direction,
                reported_state=Signal.YELLOW,
                status="SUCCESS",
                received_at=t,
            ),
            t,
        )
    assert state.stage_status == StageStatus.TIMING

    # 6. Tick past yellow_s -> enters ALL_RED
    t = t + timedelta(seconds=4)
    engine.handle(state, config, Tick(now=t), t)
    assert state.stage == StageKind.ALL_RED
    assert state.desired_signals[Direction.NORTH] == Signal.RED


def test_ack_timeout_retry_and_degraded():
    engine = TrafficEngine()
    timing = TimingConfig(ack_timeout_s=3, ack_max_retries=2)
    config = JunctionConfig(junction_id="J1", name="Junction 1", timing=timing)
    t = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)

    state = JunctionState(junction_id="J1")
    engine.handle(state, config, Recover(junction_id="J1", now=t), t)

    assert len(state.pending_commands) == 4
    first_cmd_id = list(state.pending_commands.keys())[0]
    assert state.pending_commands[first_cmd_id].attempts == 1

    # Advance time by 3s (timeout) -> Tick triggers retry with SAME command_id
    t = t + timedelta(seconds=3)
    res = engine.handle(state, config, Tick(now=t), t)
    assert first_cmd_id in state.pending_commands
    assert state.pending_commands[first_cmd_id].attempts == 2

    # Advance time by another 3s -> Retries exhausted -> DEGRADED fail-safe
    t = t + timedelta(seconds=3)
    res = engine.handle(state, config, Tick(now=t), t)
    assert state.mode == Mode.DEGRADED
    for d in Direction:
        assert state.desired_signals[d] == Signal.RED


def test_controller_ack_conflicting_actual_green_immediate_degraded():
    engine = TrafficEngine()
    config = JunctionConfig(junction_id="J1", name="Junction 1")
    t0 = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)
    state = JunctionState(
        junction_id="J1",
        stage=StageKind.GREEN,
        active_phase="NORTH_SOUTH",
        desired_signals={Direction.NORTH: Signal.GREEN, Direction.SOUTH: Signal.GREEN, Direction.EAST: Signal.RED, Direction.WEST: Signal.RED},
        actual_signals={Direction.NORTH: Signal.GREEN, Direction.SOUTH: Signal.GREEN, Direction.EAST: Signal.RED, Direction.WEST: Signal.RED},
    )

    # Controller sends orphan/corrupt ACK claiming EAST is GREEN
    ack = ControllerAck(
        command_id="cmd_corrupted_123",
        junction_id="J1",
        direction=Direction.EAST,
        reported_state=Signal.GREEN,
        status="SUCCESS",
        received_at=t0,
    )
    res = engine.handle(state, config, ack, t0)
    assert res.outcome == "ACTUAL_CONFLICT_DEGRADED"
    assert state.mode == Mode.DEGRADED
    for d in Direction:
        assert state.desired_signals[d] == Signal.RED
    assert any(e.event_type == "SAFETY_VIOLATION_OBSERVED" for e in res.effects if hasattr(e, "event_type"))


def test_controller_nack_retry_and_exhaustion():
    engine = TrafficEngine()
    timing = TimingConfig(ack_max_retries=2, ack_timeout_s=3)
    config = JunctionConfig(junction_id="J1", name="Junction 1", timing=timing)
    t = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)
    state = JunctionState(junction_id="J1")
    engine.handle(state, config, Recover(junction_id="J1", now=t), t)

    cmd_id = list(state.pending_commands.keys())[0]
    cmd = state.pending_commands[cmd_id]
    assert cmd.attempts == 1

    # Attempt 1 -> NACK arrives -> should retry with attempts=2
    t = t + timedelta(seconds=1)
    nack = ControllerAck(
        command_id=cmd_id,
        junction_id="J1",
        direction=cmd.direction,
        reported_state=Signal.UNKNOWN,
        status="FAILED",
        received_at=t,
    )
    res = engine.handle(state, config, nack, t)
    assert res.outcome == "NACK_RETRY"
    assert state.pending_commands[cmd_id].attempts == 2

    # Attempt 2 -> NACK arrives -> retries exhausted -> DEGRADED
    t = t + timedelta(seconds=1)
    nack2 = ControllerAck(
        command_id=cmd_id,
        junction_id="J1",
        direction=cmd.direction,
        reported_state=Signal.UNKNOWN,
        status="FAILED",
        received_at=t,
    )
    res2 = engine.handle(state, config, nack2, t)
    assert res2.outcome == "NACK_DEGRADED"
    assert state.mode == Mode.DEGRADED
    for d in Direction:
        assert state.desired_signals[d] == Signal.RED


def test_engine_atomic_rollback_on_unhandled_error():
    engine = TrafficEngine()
    config = JunctionConfig(junction_id="J1", name="Junction 1")
    t = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)
    state = JunctionState(junction_id="J1", mode=Mode.AUTOMATIC, version=5)

    # Monkey-patch an internal handler to throw an unexpected RuntimeError
    orig_handle_tick = engine._handle_tick
    try:
        def bad_handle_tick(s, c, tick, now, effects):
            s.mode = Mode.MANUAL  # partial mutation
            s.version = 999
            raise RuntimeError("Unexpected simulated crash")

        engine._handle_tick = bad_handle_tick

        with pytest.raises(RuntimeError, match="Unexpected simulated crash"):
            engine.handle(state, config, Tick(now=t), t)

        # State must be completely restored!
        assert state.mode == Mode.AUTOMATIC
        assert state.version == 5
    finally:
        engine._handle_tick = orig_handle_tick
