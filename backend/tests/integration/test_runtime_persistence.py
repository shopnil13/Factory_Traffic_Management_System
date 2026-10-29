import asyncio
from datetime import datetime, timezone
import os
import tempfile
import pytest

from app.application.ports import ControllerCommand
from app.application.runtime import JunctionRuntime
from app.domain.config import JunctionConfig, TimingConfig
from app.domain.inputs import ControllerAck, SensorEvent
from app.domain.model import Direction, Signal, StageKind, StageStatus, VehicleType
from app.infrastructure.db.repositories import JunctionRepository
from app.infrastructure.db.session import create_engine_and_session, init_db


class DummyController:
    def __init__(self):
        self.sent_commands: list[ControllerCommand] = []

    async def send(self, command: ControllerCommand) -> None:
        self.sent_commands.append(command)


class DummyPublisher:
    def __init__(self):
        self.published: list[tuple[str, str, dict]] = []

    async def publish(self, junction_id: str, event_type: str, data: dict) -> None:
        self.published.append((junction_id, event_type, data))


@pytest.fixture
async def temp_db():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    db_url = f"sqlite+aiosqlite:///{path}"
    engine, session_maker = create_engine_and_session(db_url)
    await init_db(engine)
    repo = JunctionRepository(session_maker)
    try:
        yield repo, db_url
    finally:
        await engine.dispose()
        if os.path.exists(path):
            try:
                os.remove(path)
            except Exception:
                pass


@pytest.mark.asyncio
async def test_actor_lifecycle_and_persistence(temp_db):
    repo, _ = temp_db
    config = JunctionConfig(junction_id="J1", name="Junction 1", timing=TimingConfig.demo_profile())
    await repo.save_junction(config)

    controller = DummyController()
    publisher = DummyPublisher()
    runtime = JunctionRuntime(config, repo, controller, publisher)

    await runtime.start()

    # Verify recovery initiated on start: stage ALL_RED AWAITING_ACK
    assert runtime.state is not None
    assert runtime.state.stage == StageKind.ALL_RED
    assert runtime.state.stage_status == StageStatus.AWAITING_ACK
    assert len(controller.sent_commands) == 4

    # Post vehicle arrival
    t = datetime.now(timezone.utc)
    ev = SensorEvent(
        event_id="ev-test-1",
        junction_id="J1",
        event_type="VEHICLE_ARRIVED",
        direction=Direction.NORTH,
        vehicle_id="TRUCK-99",
        vehicle_type=VehicleType.TRUCK,
        sequence_no=1,
        sensor_timestamp=t,
        received_at=t,
    )
    res = await runtime.submit(ev)
    assert res.outcome == "ACCEPTED"
    assert runtime.state.get_queue_counts()[Direction.NORTH] == 1

    # Verify audit history from DB
    history = await repo.get_audit_history("J1", limit=10)
    assert len(history) > 0
    event_types = [h["event_type"] for h in history]
    assert "VEHICLE_ARRIVED" in event_types

    await runtime.stop()


@pytest.mark.asyncio
async def test_restart_recovery_on_same_db(temp_db):
    repo, db_url = temp_db
    config = JunctionConfig(junction_id="J1", name="Junction 1", timing=TimingConfig.demo_profile())
    await repo.save_junction(config)

    # First instance
    ctrl1 = DummyController()
    pub1 = DummyPublisher()
    rt1 = JunctionRuntime(config, repo, ctrl1, pub1)
    await rt1.start()

    # Arrive vehicle
    t = datetime.now(timezone.utc)
    await rt1.submit(
        SensorEvent(
            event_id="e-persist",
            junction_id="J1",
            event_type="VEHICLE_ARRIVED",
            direction=Direction.EAST,
            vehicle_id="CAR-PERSIST",
            vehicle_type=VehicleType.EMPLOYEE_VEHICLE,
            sequence_no=1,
            sensor_timestamp=t,
            received_at=t,
        )
    )
    assert rt1.state.get_queue_counts()[Direction.EAST] == 1

    # Stop instance 1
    await rt1.stop()

    # Create new instance pointing to same repo/DB
    ctrl2 = DummyController()
    pub2 = DummyPublisher()
    rt2 = JunctionRuntime(config, repo, ctrl2, pub2)
    await rt2.start()

    # Invariants after restart:
    # 1. Queues and vehicles survive
    assert rt2.state.get_queue_counts()[Direction.EAST] == 1
    # 2. Physical actual signals are marked UNKNOWN
    for d in Direction:
        assert rt2.state.actual_signals[d] == Signal.UNKNOWN
    # 3. Stage is ALL_RED AWAITING_ACK with re-sync commands dispatched
    assert rt2.state.stage == StageKind.ALL_RED
    assert rt2.state.stage_status == StageStatus.AWAITING_ACK

    await rt2.stop()


@pytest.mark.asyncio
async def test_concurrent_spec_scenario_asyncio_gather(temp_db):
    repo, _ = temp_db
    config = JunctionConfig(junction_id="J1", name="Junction 1", timing=TimingConfig.demo_profile())
    await repo.save_junction(config)

    controller = DummyController()
    publisher = DummyPublisher()
    runtime = JunctionRuntime(config, repo, controller, publisher)
    await runtime.start()

    t = datetime.now(timezone.utc)
    # Spec 15.9: truck arrival, emergency arrival, duplicate emergency, manual request via asyncio.gather
    ev_truck = SensorEvent(
        event_id="concurrent-ev-1",
        junction_id="J1",
        event_type="VEHICLE_ARRIVED",
        direction=Direction.NORTH,
        vehicle_id="TRUCK-CONCURRENT",
        vehicle_type=VehicleType.TRUCK,
        sequence_no=1,
        sensor_timestamp=t,
        received_at=t,
    )
    ev_emergency = SensorEvent(
        event_id="concurrent-ev-2",
        junction_id="J1",
        event_type="VEHICLE_ARRIVED",
        direction=Direction.EAST,
        vehicle_id="AMBULANCE-01",
        vehicle_type=VehicleType.EMERGENCY,
        sequence_no=2,
        sensor_timestamp=t,
        received_at=t,
    )
    ev_emergency_dup = SensorEvent(
        event_id="concurrent-ev-2",  # exact duplicate
        junction_id="J1",
        event_type="VEHICLE_ARRIVED",
        direction=Direction.EAST,
        vehicle_id="AMBULANCE-01",
        vehicle_type=VehicleType.EMERGENCY,
        sequence_no=2,
        sensor_timestamp=t,
        received_at=t,
    )
    from app.domain.inputs import AdminCommand
    from app.domain.model import Mode
    cmd_manual = AdminCommand(
        command_type="MANUAL_GREEN_REQUEST",
        junction_id="J1",
        direction=Direction.WEST,
        requested_by="admin_alice",
        received_at=t,
    )

    results = await asyncio.gather(
        runtime.submit(ev_truck),
        runtime.submit(ev_emergency),
        runtime.submit(ev_emergency_dup),
        runtime.submit(cmd_manual),
    )

    # Assert invariants hold
    from app.domain.safety import check_invariants
    check_invariants(runtime.state, config)

    # Exactly one duplicate outcome
    outcomes = [r.outcome for r in results]
    assert "DUPLICATE" in outcomes

    # Exactly one emergency record in memory
    assert len(runtime.state.emergencies) == 1
    assert runtime.state.emergencies[0].vehicle_id == "AMBULANCE-01"

    # Emergency overrides manual: junction is in EMERGENCY mode
    assert runtime.state.mode == Mode.EMERGENCY

    # In DB: exactly one emergency row exists
    from app.infrastructure.db.tables import EmergencyModel
    from sqlalchemy import select
    async with repo.session_maker() as session:
        res = await session.execute(select(EmergencyModel).where(EmergencyModel.junction_id == "J1"))
        em_rows = res.scalars().all()
        assert len(em_rows) == 1
        assert em_rows[0].vehicle_id == "AMBULANCE-01"

    await runtime.stop()
