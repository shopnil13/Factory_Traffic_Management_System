from datetime import datetime
from sqlalchemy import Column, DateTime, ForeignKey, Index, Integer, String, Text
from app.infrastructure.db.session import Base


class JunctionModel(Base):
    __tablename__ = "junctions"

    id = Column(String, primary_key=True)
    name = Column(String, nullable=False)
    config_json = Column(Text, nullable=False)
    created_at = Column(String, nullable=False)


class JunctionStateModel(Base):
    __tablename__ = "junction_state"

    junction_id = Column(String, ForeignKey("junctions.id"), primary_key=True)
    version = Column(Integer, nullable=False, default=1)
    mode = Column(String, nullable=False)
    suspended_mode = Column(String, nullable=True)
    stage = Column(String, nullable=False)
    stage_status = Column(String, nullable=False)
    active_phase = Column(String, nullable=True)
    target_phase = Column(String, nullable=True)
    stage_started_at = Column(String, nullable=True)
    stage_timer_started_at = Column(String, nullable=True)
    desired_signals_json = Column(Text, nullable=False)
    actual_signals_json = Column(Text, nullable=False)
    controller_status = Column(String, nullable=False)
    device_status_json = Column(Text, nullable=False)
    manual_owner = Column(String, nullable=True)
    manual_direction = Column(String, nullable=True)
    manual_expires_at = Column(String, nullable=True)
    phase_last_green_json = Column(Text, nullable=False)
    updated_at = Column(String, nullable=False)


class VehicleModel(Base):
    __tablename__ = "vehicles"

    junction_id = Column(String, primary_key=True)
    vehicle_id = Column(String, primary_key=True)
    direction = Column(String, nullable=False)
    vehicle_type = Column(String, nullable=True)
    status = Column(String, nullable=False)
    received_at = Column(String, nullable=True)
    sensor_ts = Column(String, nullable=True)
    last_sequence_no = Column(Integer, nullable=False, default=0)


class ProcessedEventModel(Base):
    __tablename__ = "processed_events"

    junction_id = Column(String, primary_key=True)
    event_id = Column(String, primary_key=True)
    kind = Column(String, nullable=False)
    outcome = Column(String, nullable=False)
    received_at = Column(String, nullable=False)


class PendingCommandModel(Base):
    __tablename__ = "pending_commands"

    command_id = Column(String, primary_key=True)
    junction_id = Column(String, nullable=False)
    direction = Column(String, nullable=False)
    requested_state = Column(String, nullable=False)
    stage = Column(String, nullable=False)
    attempts = Column(Integer, nullable=False, default=1)
    sent_at = Column(String, nullable=True)
    status = Column(String, nullable=False)


class EmergencyModel(Base):
    __tablename__ = "emergencies"

    id = Column(Integer, primary_key=True, autoincrement=True)
    junction_id = Column(String, nullable=False)
    direction = Column(String, nullable=False)
    vehicle_id = Column(String, nullable=False)
    status = Column(String, nullable=False)
    detected_at = Column(String, nullable=False)
    last_seen_at = Column(String, nullable=False)
    serving_since = Column(String, nullable=True)


class AuditLogModel(Base):
    __tablename__ = "audit_log"

    id = Column(Integer, primary_key=True, autoincrement=True)
    junction_id = Column(String, nullable=False, index=True)
    server_ts = Column(String, nullable=False)
    sensor_ts = Column(String, nullable=True)
    event_type = Column(String, nullable=False)
    direction = Column(String, nullable=True)
    previous_state = Column(String, nullable=True)
    new_state = Column(String, nullable=True)
    command_id = Column(String, nullable=True)
    correlation_id = Column(String, nullable=True)
    mode = Column(String, nullable=True)
    message = Column(Text, nullable=False)
    details_json = Column(Text, nullable=True)


Index("ix_audit_junction_id_id", AuditLogModel.junction_id, AuditLogModel.id.desc())
