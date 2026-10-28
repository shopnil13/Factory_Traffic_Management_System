import asyncio
from datetime import datetime, timezone
import logging
from typing import Any, Callable, Optional

from app.application.ports import ControllerCommand, ControllerPort, ControllerUnavailable
from app.domain.inputs import ControllerAck
from app.domain.model import Signal

logger = logging.getLogger(__name__)


class SimulatorController(ControllerPort):
    def __init__(self, ack_dispatcher: Optional[Callable[[ControllerAck], Any]] = None):
        self.mode = "NORMAL"  # "NORMAL" | "DELAYED" | "DROP" | "OFFLINE" | "WRONG_STATE"
        self.delay_ms: int = 50
        self.auto_ack: bool = True
        self.ack_dispatcher = ack_dispatcher
        self.sent_commands: list[ControllerCommand] = []

    def set_dispatcher(self, dispatcher: Callable[[ControllerAck], Any]) -> None:
        self.ack_dispatcher = dispatcher

    def set_mode(
        self,
        mode: str,
        delay_ms: Optional[int] = None,
        auto_ack: Optional[bool] = None,
    ) -> dict[str, Any]:
        self.mode = mode.upper()
        if delay_ms is not None:
            self.delay_ms = delay_ms
        if auto_ack is not None:
            self.auto_ack = auto_ack
        return {
            "mode": self.mode,
            "delay_ms": self.delay_ms,
            "auto_ack": self.auto_ack,
        }

    async def send(self, command: ControllerCommand) -> None:
        self.sent_commands.append(command)

        if self.mode == "OFFLINE":
            raise ControllerUnavailable("Simulated hardware controller is OFFLINE")

        if self.mode == "DROP":
            logger.info("Simulator in DROP mode: command %s dropped without ACK", command.command_id)
            return

        if not self.auto_ack:
            logger.info("Simulator auto_ack is disabled: waiting for manual ACK for %s", command.command_id)
            return

        delay_s = (self.delay_ms / 1000.0) if self.mode == "DELAYED" else 0.05
        asyncio.create_task(self._schedule_ack(command, delay_s))

    async def _schedule_ack(self, command: ControllerCommand, delay_s: float) -> None:
        try:
            if delay_s > 0:
                await asyncio.sleep(delay_s)

            reported_state = command.requested_state
            status = "SUCCESS"

            if self.mode == "WRONG_STATE":
                # Report mismatching state
                reported_state = Signal.RED if command.requested_state != Signal.RED else Signal.YELLOW
                status = "FAILED"

            ack = ControllerAck(
                command_id=command.command_id,
                junction_id=command.junction_id,
                direction=command.direction,
                reported_state=reported_state,
                status=status,
                received_at=datetime.now(timezone.utc),
            )

            if self.ack_dispatcher:
                res = self.ack_dispatcher(ack)
                if asyncio.iscoroutine(res):
                    await res
        except Exception as e:
            logger.error("Simulator failed to dispatch ACK for %s: %s", command.command_id, e)


simulator_controller = SimulatorController()
