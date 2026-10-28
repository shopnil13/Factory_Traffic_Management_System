from datetime import datetime, timedelta, timezone
import random
import pytest

from app.domain.config import JunctionConfig, TimingConfig
from app.domain.engine import TrafficEngine
from app.domain.inputs import (
    AdminCommand,
    ControllerAck,
    DeviceStatusUpdate,
    Recover,
    SensorEvent,
    Tick,
)
from app.domain.model import (
    DeviceStatus,
    Direction,
    JunctionState,
    Mode,
    Signal,
    StageKind,
    StageStatus,
    VehicleType,
)
from app.domain.safety import check_invariants


def test_emergency_overrides_manual_and_resumes():
    engine = TrafficEngine()
    timing = TimingConfig(green_min_s=5, manual_lease_s=100)
    config = JunctionConfig(junction_id="J1", name="Junction 1", timing=timing)
    t = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)

    state = JunctionState(
        junction_id="J1",
        stage=StageKind.GREEN,
        stage_status=StageStatus.TIMING,
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
            Direction.EAST: Signal.RED,
            Direction.WEST: Signal.RED,
        },
    )

    # 1. Admin 1 requests manual green for WEST
    cmd = AdminCommand(
        command_type="MANUAL_GREEN_REQUEST",
        junction_id="J1",
        direction=Direction.WEST,
        requested_by="admin_alice",
        received_at=t,
    )
    res = engine.handle(state, config, cmd, t)
    assert res.outcome == "COMMAND_ACCEPTED"
    assert state.mode == Mode.MANUAL
    assert state.manual_owner == "admin_alice"

    # 2. Emergency vehicle arrives at NORTH
    em_arr = SensorEvent(
        event_id="em-1",
        junction_id="J1",
        event_type="VEHICLE_ARRIVED",
        direction=Direction.NORTH,
        vehicle_id="AMBULANCE-01",
        vehicle_type=VehicleType.EMERGENCY,
        sequence_no=1,
        sensor_timestamp=t,
        received_at=t,
    )
    res2 = engine.handle(state, config, em_arr, t)
    assert state.mode == Mode.EMERGENCY
    assert state.suspended_mode == Mode.MANUAL

    # 3. Emergency vehicle clears
    em_clr = SensorEvent(
        event_id="em-1-clr",
        junction_id="J1",
        event_type="VEHICLE_CLEARED",
        direction=Direction.NORTH,
        vehicle_id="AMBULANCE-01",
        vehicle_type=VehicleType.EMERGENCY,
        sequence_no=2,
        sensor_timestamp=t,
        received_at=t,
    )
    res3 = engine.handle(state, config, em_clr, t)
    assert state.mode == Mode.MANUAL
    assert state.suspended_mode is None
    assert state.manual_owner == "admin_alice"


def test_manual_multi_admin_lock():
    engine = TrafficEngine()
    timing = TimingConfig(manual_lease_s=60)
    config = JunctionConfig(junction_id="J1", name="Junction 1", timing=timing)
    t = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)

    state = JunctionState(
        junction_id="J1",
        stage=StageKind.GREEN,
        stage_status=StageStatus.TIMING,
        active_phase="NORTH_SOUTH",
        desired_signals={d: Signal.RED for d in Direction},
        actual_signals={d: Signal.RED for d in Direction},
    )

    # Admin Alice locks manual
    engine.handle(
        state,
        config,
        AdminCommand(
            command_type="MANUAL_GREEN_REQUEST",
            junction_id="J1",
            direction=Direction.NORTH,
            requested_by="admin_alice",
            received_at=t,
        ),
        t,
    )
    assert state.mode == Mode.MANUAL
    assert state.manual_owner == "admin_alice"

    # Admin Bob tries to command -> Rejected with MANUAL_LOCKED
    res_bob = engine.handle(
        state,
        config,
        AdminCommand(
            command_type="MANUAL_GREEN_REQUEST",
            junction_id="J1",
            direction=Direction.EAST,
            requested_by="admin_bob",
            received_at=t,
        ),
        t,
    )
    assert res_bob.outcome == "MANUAL_LOCKED"

    # Advance time past lease -> Alice's lease expires
    t_expired = t + timedelta(seconds=65)
    engine.handle(state, config, Tick(now=t_expired), t_expired)
    assert state.mode == Mode.AUTOMATIC
    assert state.manual_owner is None


def test_invariant_fuzz_simulation():
    """Fuzz testing with 2,000 mixed random inputs to rigorously verify safety invariants."""
    random.seed(42)
    engine = TrafficEngine()
    config = JunctionConfig(junction_id="J1", name="Junction 1", timing=TimingConfig.demo_profile())
    t = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)

    state = JunctionState(junction_id="J1")
    engine.handle(state, config, Recover(junction_id="J1", now=t), t)

    directions = list(Direction)
    v_types = [VehicleType.TRUCK, VehicleType.FORKLIFT, VehicleType.EMPLOYEE_VEHICLE, VehicleType.EMERGENCY]

    event_counter = 0

    for step in range(2000):
        t = t + timedelta(milliseconds=random.randint(50, 500))
        action = random.choice(["tick", "sensor", "ack", "admin", "device", "recover"])

        if action == "tick":
            inp = Tick(now=t)

        elif action == "sensor":
            event_counter += 1
            d = random.choice(directions)
            v_type = random.choice(v_types)
            v_id = f"V-{random.randint(1, 20)}"
            ev_type = random.choice(["VEHICLE_ARRIVED", "VEHICLE_CLEARED"])
            inp = SensorEvent(
                event_id=f"fuzz-ev-{event_counter}",
                junction_id="J1",
                event_type=ev_type,
                direction=d,
                vehicle_id=v_id,
                vehicle_type=v_type if ev_type == "VEHICLE_ARRIVED" else None,
                sequence_no=random.randint(1, 100),
                sensor_timestamp=t,
                received_at=t,
            )

        elif action == "ack":
            if state.pending_commands:
                cmd_id = random.choice(list(state.pending_commands.keys()))
                cmd = state.pending_commands[cmd_id]
                inp = ControllerAck(
                    command_id=cmd_id,
                    junction_id="J1",
                    direction=cmd.direction,
                    reported_state=cmd.requested_state,
                    status="SUCCESS",
                    received_at=t,
                )
            else:
                inp = Tick(now=t)

        elif action == "admin":
            admin_user = random.choice(["admin_1", "admin_2"])
            if random.random() < 0.5:
                inp = AdminCommand(
                    command_type="MANUAL_GREEN_REQUEST",
                    junction_id="J1",
                    direction=random.choice(directions),
                    requested_by=admin_user,
                    received_at=t,
                )
            else:
                inp = AdminCommand(
                    command_type="RETURN_TO_AUTOMATIC",
                    junction_id="J1",
                    requested_by=admin_user,
                    received_at=t,
                )

        elif action == "device":
            status = random.choice([DeviceStatus.ONLINE, DeviceStatus.ONLINE, DeviceStatus.OFFLINE])
            inp = DeviceStatusUpdate(
                junction_id="J1",
                component_type="SIGNAL_CONTROLLER",
                identifier="controller",
                status=status,
                reported_at=t,
            )

        else:  # recover
            inp = Recover(junction_id="J1", now=t)

        # Execute step
        res = engine.handle(state, config, inp, t)

        # Invariant verification after every single step
        check_invariants(state, config)
