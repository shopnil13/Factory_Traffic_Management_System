from datetime import datetime, timezone
from fastapi import APIRouter, Response, status

from app.api.errors import AppAPIException
from app.api.schemas import ControllerAckSchema, DeviceStatusSchema, SensorEventSchema
from app.application.registry import registry
from app.domain.inputs import ControllerAck, DeviceStatusUpdate, SensorEvent

router = APIRouter(prefix="/api", tags=["Events"])


@router.post("/sensor-events")
async def post_sensor_event(event: SensorEventSchema, response: Response):
    rt = registry.get(event.junction_id)
    if not rt:
        raise AppAPIException(
            status_code=404,
            code="JUNCTION_NOT_FOUND",
            message=f"Junction '{event.junction_id}' not found",
        )

    now = datetime.now(timezone.utc)
    domain_event = SensorEvent(
        event_id=event.event_id,
        junction_id=event.junction_id,
        event_type=event.event_type,
        direction=event.direction,
        vehicle_id=event.vehicle_id,
        vehicle_type=event.vehicle_type,
        sequence_no=event.sequence_no,
        sensor_timestamp=event.timestamp,
        received_at=now,
    )

    result = await rt.submit(domain_event)

    if result.outcome == "ACCEPTED":
        response.status_code = status.HTTP_201_CREATED
    else:
        # Idempotent: 200 OK for DUPLICATE, IGNORED_STALE, IGNORED_OUT_OF_ORDER, REJECTED_CLOCK_SKEW
        response.status_code = status.HTTP_200_OK

    return {
        "event_id": event.event_id,
        "outcome": result.outcome,
        "queue_counts": {d.value: c for d, c in rt.state.get_queue_counts().items()},
    }


@router.post("/controller-events")
async def post_controller_event(ack: ControllerAckSchema):
    rt = registry.get(ack.junction_id)
    if not rt:
        raise AppAPIException(
            status_code=404,
            code="JUNCTION_NOT_FOUND",
            message=f"Junction '{ack.junction_id}' not found",
        )

    now = datetime.now(timezone.utc)
    domain_ack = ControllerAck(
        command_id=ack.command_id,
        junction_id=ack.junction_id,
        direction=ack.direction,
        reported_state=ack.reported_state,
        status=ack.status or "SUCCESS",
        received_at=now,
    )
    result = await rt.submit(domain_ack)
    return {
        "command_id": ack.command_id,
        "outcome": result.outcome,
        "actual_signals": {d.value: s.value for d, s in rt.state.actual_signals.items()},
    }


@router.post("/device-status")
async def post_device_status(data: DeviceStatusSchema):
    rt = registry.get(data.junction_id)
    if not rt:
        raise AppAPIException(
            status_code=404,
            code="JUNCTION_NOT_FOUND",
            message=f"Junction '{data.junction_id}' not found",
        )

    now = datetime.now(timezone.utc)
    domain_update = DeviceStatusUpdate(
        junction_id=data.junction_id,
        component_type=data.component_type,
        identifier=data.identifier,
        status=data.status,
        reported_at=now,
    )
    result = await rt.submit(domain_update)
    return {
        "outcome": result.outcome,
        "controller_status": rt.state.controller_status.value,
        "mode": rt.state.mode.value,
    }
