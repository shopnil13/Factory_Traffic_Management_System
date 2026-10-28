from datetime import datetime, timedelta, timezone
import pytest

from app.domain.config import JunctionConfig, TimingConfig
from app.domain.engine import TrafficEngine
from app.domain.inputs import ControllerAck, Recover, SensorEvent, Tick
from app.domain.model import (
    Direction,
    JunctionState,
    Mode,
    Signal,
    StageKind,
    StageStatus,
    VehicleStatus,
    VehicleType,
)
from app.domain.scheduler import calculate_phase_score, should_switch_phase


def make_test_junction(t0: datetime) -> tuple[TrafficEngine, JunctionConfig, JunctionState]:
    engine = TrafficEngine()
    timing = TimingConfig(green_min_s=5, green_max_s=20, starvation_max_wait_s=60, vehicle_ttl_s=120)
    config = JunctionConfig(junction_id="J1", name="Junction 1", timing=timing)
    state = JunctionState(
        junction_id="J1",
        stage=StageKind.GREEN,
        stage_status=StageStatus.TIMING,
        active_phase="NORTH_SOUTH",
        stage_started_at=t0,
        stage_timer_started_at=t0,
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
    return engine, config, state


def test_sensor_deduplication():
    t0 = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)
    engine, config, state = make_test_junction(t0)

    event = SensorEvent(
        event_id="evt-1",
        junction_id="J1",
        event_type="VEHICLE_ARRIVED",
        direction=Direction.NORTH,
        vehicle_id="TRUCK-01",
        vehicle_type=VehicleType.TRUCK,
        sequence_no=1,
        sensor_timestamp=t0,
        received_at=t0,
    )

    res1 = engine.handle(state, config, event, t0)
    assert res1.outcome == "ACCEPTED"
    assert state.get_queue_counts()[Direction.NORTH] == 1

    # Exact duplicate event_id
    res2 = engine.handle(state, config, event, t0)
    assert res2.outcome == "DUPLICATE"
    assert state.get_queue_counts()[Direction.NORTH] == 1

    # Logical duplicate: different event_id, same vehicle already WAITING
    event_dup = SensorEvent(
        event_id="evt-2",
        junction_id="J1",
        event_type="VEHICLE_ARRIVED",
        direction=Direction.NORTH,
        vehicle_id="TRUCK-01",
        vehicle_type=VehicleType.TRUCK,
        sequence_no=2,
        sensor_timestamp=t0,
        received_at=t0,
    )
    res3 = engine.handle(state, config, event_dup, t0)
    assert res3.outcome == "DUPLICATE"
    assert state.get_queue_counts()[Direction.NORTH] == 1


def test_out_of_order_clearance_and_tombstone():
    t0 = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)
    engine, config, state = make_test_junction(t0)

    # Clearance arrives before arrival event! (e.g. arrival was delayed)
    clear_evt = SensorEvent(
        event_id="evt-clear-1",
        junction_id="J1",
        event_type="VEHICLE_CLEARED",
        direction=Direction.EAST,
        vehicle_id="CAR-99",
        vehicle_type=None,
        sequence_no=5,
        sensor_timestamp=t0,
        received_at=t0,
    )
    res1 = engine.handle(state, config, clear_evt, t0)
    assert res1.outcome == "ACCEPTED"
    # Queue must remain 0! (No negative queue)
    assert state.get_queue_counts()[Direction.EAST] == 0
    assert state.vehicles["CAR-99"].status == VehicleStatus.CLEARED

    # Delayed arrival arrives with sequence_no = 4 <= 5
    delayed_arrival = SensorEvent(
        event_id="evt-arr-delayed",
        junction_id="J1",
        event_type="VEHICLE_ARRIVED",
        direction=Direction.EAST,
        vehicle_id="CAR-99",
        vehicle_type=VehicleType.EMPLOYEE_VEHICLE,
        sequence_no=4,
        sensor_timestamp=t0 - timedelta(seconds=1),
        received_at=t0,
    )
    res2 = engine.handle(state, config, delayed_arrival, t0)
    assert res2.outcome == "IGNORED_OUT_OF_ORDER"
    assert state.get_queue_counts()[Direction.EAST] == 0


def test_timestamp_sanity_rejection():
    t0 = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)
    engine, config, state = make_test_junction(t0)

    # Stale: > 10 minutes old
    stale_event = SensorEvent(
        event_id="evt-stale",
        junction_id="J1",
        event_type="VEHICLE_ARRIVED",
        direction=Direction.WEST,
        vehicle_id="V-STALE",
        vehicle_type=VehicleType.FORKLIFT,
        sequence_no=1,
        sensor_timestamp=t0 - timedelta(minutes=15),
        received_at=t0,
    )
    res1 = engine.handle(state, config, stale_event, t0)
    assert res1.outcome == "IGNORED_STALE"
    assert state.get_queue_counts()[Direction.WEST] == 0

    # Future skew: > 60s in the future
    future_event = SensorEvent(
        event_id="evt-future",
        junction_id="J1",
        event_type="VEHICLE_ARRIVED",
        direction=Direction.WEST,
        vehicle_id="V-FUTURE",
        vehicle_type=VehicleType.FORKLIFT,
        sequence_no=2,
        sensor_timestamp=t0 + timedelta(seconds=90),
        received_at=t0,
    )
    res2 = engine.handle(state, config, future_event, t0)
    assert res2.outcome == "REJECTED_CLOCK_SKEW"
    assert state.get_queue_counts()[Direction.WEST] == 0


def test_ghost_vehicle_expiration():
    t0 = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)
    engine, config, state = make_test_junction(t0)

    # Arrive at t0
    engine.handle(
        state,
        config,
        SensorEvent(
            event_id="evt-ghost",
            junction_id="J1",
            event_type="VEHICLE_ARRIVED",
            direction=Direction.NORTH,
            vehicle_id="GHOST-1",
            vehicle_type=VehicleType.FORKLIFT,
            sequence_no=1,
            sensor_timestamp=t0,
            received_at=t0,
        ),
        t0,
    )
    assert state.get_queue_counts()[Direction.NORTH] == 1

    # Tick at 100s (< TTL 120s): still waiting
    t1 = t0 + timedelta(seconds=100)
    engine.handle(state, config, Tick(now=t1), t1)
    assert state.get_queue_counts()[Direction.NORTH] == 1

    # Tick at 130s (> TTL 120s): expired!
    t2 = t0 + timedelta(seconds=130)
    engine.handle(state, config, Tick(now=t2), t2)
    assert state.get_queue_counts()[Direction.NORTH] == 0
    assert state.vehicles["GHOST-1"].status == VehicleStatus.EXPIRED


def test_scheduler_scoring_and_starvation():
    t0 = datetime(2026, 10, 28, 12, 0, 0, tzinfo=timezone.utc)
    engine, config, state = make_test_junction(t0)

    # Truck (weight 3) at NORTH vs Employee Vehicle (weight 1) at EAST
    engine.handle(
        state,
        config,
        SensorEvent(
            event_id="e1",
            junction_id="J1",
            event_type="VEHICLE_ARRIVED",
            direction=Direction.NORTH,
            vehicle_id="TRUCK-1",
            vehicle_type=VehicleType.TRUCK,
            sequence_no=1,
            sensor_timestamp=t0,
            received_at=t0,
        ),
        t0,
    )
    engine.handle(
        state,
        config,
        SensorEvent(
            event_id="e2",
            junction_id="J1",
            event_type="VEHICLE_ARRIVED",
            direction=Direction.EAST,
            vehicle_id="CAR-1",
            vehicle_type=VehicleType.EMPLOYEE_VEHICLE,
            sequence_no=1,
            sensor_timestamp=t0,
            received_at=t0,
        ),
        t0,
    )

    # At t0: NORTH_SOUTH score = 3.0, EAST_WEST score = 1.0
    s_ns = calculate_phase_score(state, config, "NORTH_SOUTH", t0)
    s_ew = calculate_phase_score(state, config, "EAST_WEST", t0)
    assert s_ns > s_ew

    # Minimum green not met (< 5s): stays GREEN
    t_early = t0 + timedelta(seconds=3)
    sw, p, reason = should_switch_phase(state, config, "NORTH_SOUTH", t_early, 3.0)
    assert sw is False

    # Hysteresis test: NORTH score is higher, so at 6s it shouldn't switch
    t_mid = t0 + timedelta(seconds=6)
    sw, p, reason = should_switch_phase(state, config, "NORTH_SOUTH", t_mid, 6.0)
    assert sw is False

    # Starvation test: Advance time to t0 + 65s (> starvation_max_wait_s 60s)
    # The employee vehicle has been waiting 65s -> hard starvation override!
    t_starved = t0 + timedelta(seconds=65)
    sw, p, reason = should_switch_phase(state, config, "NORTH_SOUTH", t_starved, 65.0)
    assert sw is True
    assert p == "EAST_WEST"
    assert "Starvation" in reason
