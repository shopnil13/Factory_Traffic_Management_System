from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, Depends, Query, Response, status

from app.api.errors import AppAPIException
from app.api.schemas import AdminCommandSchema, JunctionCreateSchema
from app.application.registry import registry
from app.application.runtime import JunctionRuntime
from app.domain.config import JunctionConfig, TimingConfig
from app.domain.inputs import AdminCommand
from app.domain.model import Direction
from app.infrastructure.controller.simulator import simulator_controller
from app.infrastructure.db.repositories import JunctionRepository
from app.infrastructure.db.session import create_engine_and_session
from app.infrastructure.sse import sse_broadcaster

router = APIRouter(prefix="/api/junctions", tags=["Junctions"])

# Dependency for repository
_, session_maker = create_engine_and_session()
default_repo = JunctionRepository(session_maker)


@router.get("")
async def list_junctions():
    junctions = await default_repo.list_junctions()
    summary = []
    for j in junctions:
        j_id = j["id"]
        rt = registry.get(j_id)
        status_data = rt.get_status_snapshot() if rt else {}
        summary.append({
            **j,
            "status": status_data,
        })
    return summary


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_junction(data: JunctionCreateSchema):
    existing = registry.get(data.junction_id)
    if existing:
        raise AppAPIException(
            status_code=409,
            code="JUNCTION_EXISTS",
            message=f"Junction with id '{data.junction_id}' already exists",
        )

    timing = TimingConfig(**data.timing) if data.timing else TimingConfig()
    config = JunctionConfig(
        junction_id=data.junction_id,
        name=data.name,
        timing=timing,
        phases=data.phases if data.phases else {
            "NORTH_SOUTH": [Direction.NORTH, Direction.SOUTH],
            "EAST_WEST": [Direction.EAST, Direction.WEST],
        },
    )
    await default_repo.save_junction(config)

    # Start runtime actor
    runtime = JunctionRuntime(
        config=config,
        repository=default_repo,
        controller_port=simulator_controller,
        event_publisher=sse_broadcaster,
    )
    await runtime.start()
    registry.register(runtime)

    return {
        "junction_id": config.junction_id,
        "name": config.name,
        "status": runtime.get_status_snapshot(),
    }


@router.get("/{junction_id}")
async def get_junction(junction_id: str):
    rt = registry.get(junction_id)
    if not rt:
        config = await default_repo.get_junction_config(junction_id)
        if not config:
            raise AppAPIException(status_code=404, code="JUNCTION_NOT_FOUND", message=f"Junction '{junction_id}' not found")
        return {"junction_id": config.junction_id, "name": config.name, "config": config.__dict__}
    return {
        "junction_id": rt.config.junction_id,
        "name": rt.config.name,
        "config": {
            "junction_id": rt.config.junction_id,
            "name": rt.config.name,
            "timing": rt.config.timing.__dict__,
            "phases": {k: [d.value for d in dirs] for k, dirs in rt.config.phases.items()},
        },
        "status": rt.get_status_snapshot(),
    }


@router.get("/{junction_id}/status")
async def get_junction_status(junction_id: str):
    rt = registry.get(junction_id)
    if not rt:
        raise AppAPIException(status_code=404, code="JUNCTION_NOT_FOUND", message=f"Junction '{junction_id}' not found")
    return rt.get_status_snapshot()


@router.get("/{junction_id}/history")
async def get_junction_history(
    junction_id: str,
    limit: int = Query(default=50, le=200),
    before_id: Optional[int] = Query(default=None),
    event_type: Optional[str] = Query(default=None),
):
    rt = registry.get(junction_id)
    if not rt and not await default_repo.get_junction_config(junction_id):
        raise AppAPIException(status_code=404, code="JUNCTION_NOT_FOUND", message=f"Junction '{junction_id}' not found")

    logs = await default_repo.get_audit_history(junction_id, limit=limit, before_id=before_id, event_type=event_type)
    return logs


@router.post("/{junction_id}/commands", status_code=status.HTTP_202_ACCEPTED)
async def post_command(junction_id: str, command: AdminCommandSchema, response: Response):
    rt = registry.get(junction_id)
    if not rt:
        raise AppAPIException(status_code=404, code="JUNCTION_NOT_FOUND", message=f"Junction '{junction_id}' not found")

    cmd = AdminCommand(
        command_type=command.command_type,
        junction_id=junction_id,
        direction=command.direction,
        requested_by=command.requested_by or "admin",
        received_at=datetime.now(timezone.utc),
    )
    result = await rt.submit(cmd)

    if result.outcome == "MANUAL_LOCKED":
        raise AppAPIException(
            status_code=409,
            code="MANUAL_LOCKED",
            message=f"Manual control is locked by another operator ('{rt.state.manual_owner}')",
            details={"owner": rt.state.manual_owner, "expires_at": rt.state.manual_expires_at.isoformat() if rt.state.manual_expires_at else None},
        )
    elif result.outcome == "EMERGENCY_ACTIVE":
        raise AppAPIException(
            status_code=409,
            code="EMERGENCY_ACTIVE",
            message="Cannot take manual control: emergency vehicle preemption is active",
        )
    elif result.outcome == "JUNCTION_DEGRADED":
        raise AppAPIException(
            status_code=409,
            code="JUNCTION_DEGRADED",
            message="Cannot take manual control: junction is in fail-safe DEGRADED mode",
        )

    return {
        "outcome": result.outcome,
        "planned_sequence": result.details.get("planned_sequence") if result.details else [],
        "status": rt.get_status_snapshot(),
    }
