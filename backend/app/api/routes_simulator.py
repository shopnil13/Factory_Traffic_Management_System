from fastapi import APIRouter
from app.api.schemas import SimulatorConfigSchema
from app.infrastructure.controller.simulator import simulator_controller

router = APIRouter(prefix="/api/simulator", tags=["Simulator"])


@router.get("/controller")
async def get_simulator_status():
    return {
        "mode": simulator_controller.mode,
        "delay_ms": simulator_controller.delay_ms,
        "auto_ack": simulator_controller.auto_ack,
        "sent_commands_count": len(simulator_controller.sent_commands),
    }


@router.post("/controller")
async def configure_simulator(config: SimulatorConfigSchema):
    res = simulator_controller.set_mode(
        mode=config.mode,
        delay_ms=config.delay_ms,
        auto_ack=config.auto_ack,
    )
    return res
