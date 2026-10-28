import json
from datetime import datetime, timezone
from typing import Any, Optional

from sqlalchemy import delete, desc, select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.domain.config import JunctionConfig, TimingConfig
from app.domain.effects import DomainEffect, RecordAudit
from app.domain.model import (
    CommandStatus,
    DeviceStatus,
    Direction,
    EmergencyRecord,
    EmergencyStatus,
    JunctionState,
    Mode,
    PendingCommand,
    Signal,
    StageKind,
    StageStatus,
    VehicleRecord,
    VehicleStatus,
    VehicleType,
)
from app.infrastructure.db.tables import (
    AuditLogModel,
    EmergencyModel,
    JunctionModel,
    JunctionStateModel,
    PendingCommandModel,
    ProcessedEventModel,
    VehicleModel,
)


def _dt_to_str(dt: Optional[datetime]) -> Optional[str]:
    return dt.isoformat() if dt else None


def _str_to_dt(s: Optional[str]) -> Optional[datetime]:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except Exception:
        return None


class StaleStateError(Exception):
    """Raised when an optimistic concurrency version check fails."""
    pass


class JunctionRepository:
    def __init__(self, session_maker: async_sessionmaker[AsyncSession]):
        self.session_maker = session_maker

    async def save_junction(self, config: JunctionConfig) -> None:
        async with self.session_maker() as session:
            async with session.begin():
                config_data = {
                    "junction_id": config.junction_id,
                    "name": config.name,
                    "timing": config.timing.__dict__,
                    "phases": {k: [d.value for d in dirs] for k, dirs in config.phases.items()},
                }
                now_str = datetime.now(timezone.utc).isoformat()
                stmt = select(JunctionModel).where(JunctionModel.id == config.junction_id)
                res = await session.execute(stmt)
                existing = res.scalar_one_or_none()

                if existing:
                    existing.name = config.name
                    existing.config_json = json.dumps(config_data)
                else:
                    new_j = JunctionModel(
                        id=config.junction_id,
                        name=config.name,
                        config_json=json.dumps(config_data),
                        created_at=now_str,
                    )
                    session.add(new_j)

    async def get_junction_config(self, junction_id: str) -> Optional[JunctionConfig]:
        async with self.session_maker() as session:
            stmt = select(JunctionModel).where(JunctionModel.id == junction_id)
            res = await session.execute(stmt)
            model = res.scalar_one_or_none()
            if not model:
                return None

            data = json.loads(model.config_json)
            timing_dict = data.get("timing", {})
            timing = TimingConfig(**timing_dict)
            phases_raw = data.get("phases", {})
            phases = {k: [Direction(d) for d in dirs] for k, dirs in phases_raw.items()}

            return JunctionConfig(
                junction_id=model.id,
                name=model.name,
                timing=timing,
                phases=phases,
            )

    async def list_junctions(self) -> list[dict[str, Any]]:
        async with self.session_maker() as session:
            stmt = select(JunctionModel)
            res = await session.execute(stmt)
            models = res.scalars().all()
            result = []
            for m in models:
                data = json.loads(m.config_json)
                result.append({
                    "id": m.id,
                    "name": m.name,
                    "config": data,
                    "created_at": m.created_at,
                })
            return result

    async def load_junction_state(self, junction_id: str) -> Optional[JunctionState]:
        async with self.session_maker() as session:
            # 1. Load state row
            stmt = select(JunctionStateModel).where(JunctionStateModel.junction_id == junction_id)
            res = await session.execute(stmt)
            s_model = res.scalar_one_or_none()
            if not s_model:
                return None

            state = JunctionState(
                junction_id=s_model.junction_id,
                version=s_model.version,
                mode=Mode(s_model.mode),
                suspended_mode=Mode(s_model.suspended_mode) if s_model.suspended_mode else None,
                stage=StageKind(s_model.stage),
                stage_status=StageStatus(s_model.stage_status),
                active_phase=s_model.active_phase,
                target_phase=s_model.target_phase,
                stage_started_at=_str_to_dt(s_model.stage_started_at),
                stage_timer_started_at=_str_to_dt(s_model.stage_timer_started_at),
                desired_signals={Direction(d): Signal(s) for d, s in json.loads(s_model.desired_signals_json).items()},
                actual_signals={Direction(d): Signal(s) for d, s in json.loads(s_model.actual_signals_json).items()},
                controller_status=DeviceStatus(s_model.controller_status),
                device_status={k: DeviceStatus(v) for k, v in json.loads(s_model.device_status_json).items()},
                manual_owner=s_model.manual_owner,
                manual_direction=Direction(s_model.manual_direction) if s_model.manual_direction else None,
                manual_expires_at=_str_to_dt(s_model.manual_expires_at),
                phase_last_green_at={k: _str_to_dt(v) for k, v in json.loads(s_model.phase_last_green_json).items() if v},
                updated_at=_str_to_dt(s_model.updated_at),
            )

            # 2. Load vehicles
            v_stmt = select(VehicleModel).where(VehicleModel.junction_id == junction_id)
            v_res = await session.execute(v_stmt)
            for vm in v_res.scalars().all():
                state.vehicles[vm.vehicle_id] = VehicleRecord(
                    junction_id=vm.junction_id,
                    vehicle_id=vm.vehicle_id,
                    direction=Direction(vm.direction),
                    vehicle_type=VehicleType(vm.vehicle_type) if vm.vehicle_type else None,
                    status=VehicleStatus(vm.status),
                    received_at=_str_to_dt(vm.received_at),
                    sensor_ts=_str_to_dt(vm.sensor_ts),
                    last_sequence_no=vm.last_sequence_no,
                )

            # 3. Load processed events
            e_stmt = select(ProcessedEventModel.event_id).where(ProcessedEventModel.junction_id == junction_id)
            e_res = await session.execute(e_stmt)
            state.processed_event_ids = set(e_res.scalars().all())

            # 4. Load pending commands
            c_stmt = select(PendingCommandModel).where(
                PendingCommandModel.junction_id == junction_id,
                PendingCommandModel.status == CommandStatus.PENDING.value,
            )
            c_res = await session.execute(c_stmt)
            for cm in c_res.scalars().all():
                state.pending_commands[cm.command_id] = PendingCommand(
                    command_id=cm.command_id,
                    junction_id=cm.junction_id,
                    direction=Direction(cm.direction),
                    requested_state=Signal(cm.requested_state),
                    stage=cm.stage,
                    attempts=cm.attempts,
                    sent_at=_str_to_dt(cm.sent_at) or datetime.now(timezone.utc),
                    status=CommandStatus(cm.status),
                )

            # 5. Load emergencies
            em_stmt = select(EmergencyModel).where(
                EmergencyModel.junction_id == junction_id,
                EmergencyModel.status.in_([EmergencyStatus.ACTIVE.value, EmergencyStatus.SERVING.value]),
            ).order_by(EmergencyModel.id)
            em_res = await session.execute(em_stmt)
            for em in em_res.scalars().all():
                state.emergencies.append(
                    EmergencyRecord(
                        id=em.id,
                        junction_id=em.junction_id,
                        direction=Direction(em.direction),
                        vehicle_id=em.vehicle_id,
                        status=EmergencyStatus(em.status),
                        detected_at=_str_to_dt(em.detected_at) or datetime.now(timezone.utc),
                        last_seen_at=_str_to_dt(em.last_seen_at) or datetime.now(timezone.utc),
                        serving_since=_str_to_dt(em.serving_since),
                    )
                )

            return state

    async def save_actor_step(
        self,
        state: JunctionState,
        effects: list[DomainEffect],
        outcome: str,
        now: datetime,
    ) -> None:
        """
        Executes a single atomic transaction writing state with version check,
        vehicles, processed events, pending commands, emergencies, and audit logs.
        """
        async with self.session_maker() as session:
            async with session.begin():
                # 1. Update JunctionState with version check
                prev_version = state.version - 1

                stmt = select(JunctionStateModel).where(JunctionStateModel.junction_id == state.junction_id)
                res = await session.execute(stmt)
                current = res.scalar_one_or_none()

                desired_json = json.dumps({d.value: s.value for d, s in state.desired_signals.items()})
                actual_json = json.dumps({d.value: s.value for d, s in state.actual_signals.items()})
                dev_json = json.dumps({k: v.value for k, v in state.device_status.items()})
                phase_green_json = json.dumps({k: _dt_to_str(v) for k, v in state.phase_last_green_at.items()})
                now_str = _dt_to_str(now) or datetime.now(timezone.utc).isoformat()

                if current is None:
                    # Initial insert
                    new_state = JunctionStateModel(
                        junction_id=state.junction_id,
                        version=state.version,
                        mode=state.mode.value,
                        suspended_mode=state.suspended_mode.value if state.suspended_mode else None,
                        stage=state.stage.value,
                        stage_status=state.stage_status.value,
                        active_phase=state.active_phase,
                        target_phase=state.target_phase,
                        stage_started_at=_dt_to_str(state.stage_started_at),
                        stage_timer_started_at=_dt_to_str(state.stage_timer_started_at),
                        desired_signals_json=desired_json,
                        actual_signals_json=actual_json,
                        controller_status=state.controller_status.value,
                        device_status_json=dev_json,
                        manual_owner=state.manual_owner,
                        manual_direction=state.manual_direction.value if state.manual_direction else None,
                        manual_expires_at=_dt_to_str(state.manual_expires_at),
                        phase_last_green_json=phase_green_json,
                        updated_at=now_str,
                    )
                    session.add(new_state)
                else:
                    if current.version != prev_version and prev_version > 0:
                        raise StaleStateError(
                            f"Version mismatch for {state.junction_id}: DB has {current.version}, actor expected {prev_version}"
                        )
                    current.version = state.version
                    current.mode = state.mode.value
                    current.suspended_mode = state.suspended_mode.value if state.suspended_mode else None
                    current.stage = state.stage.value
                    current.stage_status = state.stage_status.value
                    current.active_phase = state.active_phase
                    current.target_phase = state.target_phase
                    current.stage_started_at = _dt_to_str(state.stage_started_at)
                    current.stage_timer_started_at = _dt_to_str(state.stage_timer_started_at)
                    current.desired_signals_json = desired_json
                    current.actual_signals_json = actual_json
                    current.controller_status = state.controller_status.value
                    current.device_status_json = dev_json
                    current.manual_owner = state.manual_owner
                    current.manual_direction = state.manual_direction.value if state.manual_direction else None
                    current.manual_expires_at = _dt_to_str(state.manual_expires_at)
                    current.phase_last_green_json = phase_green_json
                    current.updated_at = now_str

                # 2. Persist Vehicles
                for v in state.vehicles.values():
                    v_stmt = select(VehicleModel).where(
                        VehicleModel.junction_id == state.junction_id,
                        VehicleModel.vehicle_id == v.vehicle_id,
                    )
                    v_res = await session.execute(v_stmt)
                    v_existing = v_res.scalar_one_or_none()
                    if v_existing:
                        v_existing.direction = v.direction.value
                        v_existing.vehicle_type = v.vehicle_type.value if v.vehicle_type else None
                        v_existing.status = v.status.value
                        v_existing.received_at = _dt_to_str(v.received_at)
                        v_existing.sensor_ts = _dt_to_str(v.sensor_ts)
                        v_existing.last_sequence_no = v.last_sequence_no
                    else:
                        new_vm = VehicleModel(
                            junction_id=state.junction_id,
                            vehicle_id=v.vehicle_id,
                            direction=v.direction.value,
                            vehicle_type=v.vehicle_type.value if v.vehicle_type else None,
                            status=v.status.value,
                            received_at=_dt_to_str(v.received_at),
                            sensor_ts=_dt_to_str(v.sensor_ts),
                            last_sequence_no=v.last_sequence_no,
                        )
                        session.add(new_vm)

                # 3. Persist Processed Events
                for ev_id in state.processed_event_ids:
                    pe_stmt = select(ProcessedEventModel).where(
                        ProcessedEventModel.junction_id == state.junction_id,
                        ProcessedEventModel.event_id == ev_id,
                    )
                    pe_res = await session.execute(pe_stmt)
                    if not pe_res.scalar_one_or_none():
                        session.add(
                            ProcessedEventModel(
                                junction_id=state.junction_id,
                                event_id=ev_id,
                                kind="SENSOR",
                                outcome=outcome,
                                received_at=now_str,
                            )
                        )

                # 4. Persist Pending Commands
                for cmd in state.pending_commands.values():
                    cmd_stmt = select(PendingCommandModel).where(PendingCommandModel.command_id == cmd.command_id)
                    cmd_res = await session.execute(cmd_stmt)
                    existing_cmd = cmd_res.scalar_one_or_none()
                    if existing_cmd:
                        existing_cmd.attempts = cmd.attempts
                        existing_cmd.status = cmd.status.value
                    else:
                        session.add(
                            PendingCommandModel(
                                command_id=cmd.command_id,
                                junction_id=state.junction_id,
                                direction=cmd.direction.value,
                                requested_state=cmd.requested_state.value,
                                stage=cmd.stage,
                                attempts=cmd.attempts,
                                sent_at=_dt_to_str(cmd.sent_at),
                                status=cmd.status.value,
                            )
                        )

                # 5. Persist Emergencies
                for em in state.emergencies:
                    if em.id:
                        em_stmt = select(EmergencyModel).where(EmergencyModel.id == em.id)
                        em_res = await session.execute(em_stmt)
                        existing_em = em_res.scalar_one_or_none()
                        if existing_em:
                            existing_em.status = em.status.value
                            existing_em.last_seen_at = _dt_to_str(em.last_seen_at)
                            existing_em.serving_since = _dt_to_str(em.serving_since)
                            continue

                    new_em = EmergencyModel(
                        junction_id=state.junction_id,
                        direction=em.direction.value,
                        vehicle_id=em.vehicle_id,
                        status=em.status.value,
                        detected_at=_dt_to_str(em.detected_at),
                        last_seen_at=_dt_to_str(em.last_seen_at),
                        serving_since=_dt_to_str(em.serving_since),
                    )
                    session.add(new_em)

                # 6. Persist Audit Logs
                for eff in effects:
                    if isinstance(eff, RecordAudit):
                        session.add(
                            AuditLogModel(
                                junction_id=eff.junction_id,
                                server_ts=_dt_to_str(eff.server_ts) or now_str,
                                sensor_ts=_dt_to_str(eff.sensor_ts),
                                event_type=eff.event_type,
                                direction=eff.direction.value if eff.direction else None,
                                previous_state=eff.previous_state,
                                new_state=eff.new_state,
                                command_id=eff.command_id,
                                correlation_id=eff.correlation_id,
                                mode=eff.mode,
                                message=eff.message,
                                details_json=json.dumps(eff.details) if eff.details else None,
                            )
                        )

    async def get_audit_history(
        self,
        junction_id: str,
        limit: int = 50,
        before_id: Optional[int] = None,
        event_type: Optional[str] = None,
    ) -> list[dict[str, Any]]:
        async with self.session_maker() as session:
            stmt = select(AuditLogModel).where(AuditLogModel.junction_id == junction_id)
            if before_id:
                stmt = stmt.where(AuditLogModel.id < before_id)
            if event_type:
                stmt = stmt.where(AuditLogModel.event_type == event_type)
            stmt = stmt.order_by(AuditLogModel.id.desc()).limit(limit)

            res = await session.execute(stmt)
            logs = res.scalars().all()
            return [
                {
                    "id": l.id,
                    "junction_id": l.junction_id,
                    "server_ts": l.server_ts,
                    "sensor_ts": l.sensor_ts,
                    "event_type": l.event_type,
                    "direction": l.direction,
                    "previous_state": l.previous_state,
                    "new_state": l.new_state,
                    "command_id": l.command_id,
                    "correlation_id": l.correlation_id,
                    "mode": l.mode,
                    "message": l.message,
                    "details": json.loads(l.details_json) if l.details_json else None,
                }
                for l in logs
            ]
