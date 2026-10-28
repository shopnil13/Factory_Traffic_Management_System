import asyncio
from datetime import datetime, timezone
import logging
from typing import Any, Optional

from app.application.ports import ControllerCommand, ControllerPort, ControllerUnavailable, EventPublisher
from app.domain.config import JunctionConfig
from app.domain.effects import PublishUpdate, RecordAudit, SendControllerCommand
from app.domain.engine import EngineResult, TrafficEngine
from app.domain.inputs import DomainInput, Recover, Tick
from app.domain.model import DeviceStatus, Direction, JunctionState, Mode, Signal, StageKind
from app.infrastructure.db.repositories import JunctionRepository

logger = logging.getLogger(__name__)


class JunctionRuntime:
    """
    Per-junction actor: owns an asyncio mailbox and single worker task.
    All inputs for the junction are serialized and executed deterministically.
    """

    def __init__(
        self,
        config: JunctionConfig,
        repository: JunctionRepository,
        controller_port: ControllerPort,
        event_publisher: EventPublisher,
        engine: Optional[TrafficEngine] = None,
    ):
        self.config = config
        self.repository = repository
        self.controller = controller_port
        self.publisher = event_publisher
        self.engine = engine or TrafficEngine()

        self.junction_id = config.junction_id
        self.mailbox: asyncio.Queue[tuple[DomainInput, asyncio.Future[EngineResult]]] = asyncio.Queue(maxsize=1000)
        self.state: Optional[JunctionState] = None

        self._worker_task: Optional[asyncio.Task] = None
        self._tick_task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        """Starts worker actor, performs restart recovery if state exists, and starts ticker."""
        if self._running:
            return
        self._running = True

        # 1. Load or initialize state from repository
        loaded_state = await self.repository.load_junction_state(self.junction_id)
        now = datetime.now(timezone.utc)

        if loaded_state:
            self.state = loaded_state
            logger.info("Loaded persisted state for junction %s (version %d)", self.junction_id, self.state.version)
        else:
            self.state = JunctionState(junction_id=self.junction_id)
            logger.info("Initialized fresh state for junction %s", self.junction_id)

        # 2. Start worker loop
        self._worker_task = asyncio.create_task(self._run_worker(), name=f"actor_{self.junction_id}")

        # 3. Trigger restart recovery (Recover input)
        rec_future: asyncio.Future[EngineResult] = asyncio.get_running_loop().create_future()
        await self.mailbox.put((Recover(junction_id=self.junction_id, now=now), rec_future))
        await rec_future

        # 4. Start periodic ticker
        self._tick_task = asyncio.create_task(self._run_ticker(), name=f"ticker_{self.junction_id}")

    async def stop(self) -> None:
        """Gracefully stops ticker and worker."""
        self._running = False
        if self._tick_task:
            self._tick_task.cancel()
            try:
                await self._tick_task
            except asyncio.CancelledError:
                pass
        if self._worker_task:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass

    async def submit(self, domain_input: DomainInput) -> EngineResult:
        """Enqueues input to actor mailbox and awaits the result future."""
        if not self._running:
            raise RuntimeError(f"Actor for junction {self.junction_id} is not running")

        loop = asyncio.get_running_loop()
        future: asyncio.Future[EngineResult] = loop.create_future()
        try:
            self.mailbox.put_nowait((domain_input, future))
        except asyncio.QueueFull:
            raise RuntimeError("Actor mailbox is full; backpressure triggered")

        return await future

    async def _run_worker(self) -> None:
        while self._running:
            try:
                domain_input, future = await self.mailbox.get()
            except asyncio.CancelledError:
                break

            now = datetime.now(timezone.utc)

            try:
                # 1. Reducer step (pure domain)
                result = self.engine.handle(self.state, self.config, domain_input, now)
                self.state = result.state

                # 2. Atomic DB transaction commit
                await self.repository.save_actor_step(
                    state=self.state,
                    effects=result.effects,
                    outcome=result.outcome,
                    now=now,
                )

                # 3. Execute external side effects
                for eff in result.effects:
                    if isinstance(eff, SendControllerCommand):
                        asyncio.create_task(self._dispatch_controller_command(eff))
                    elif isinstance(eff, PublishUpdate):
                        asyncio.create_task(self._publish_snapshot())

                # 4. Resolve caller future
                if not future.done():
                    future.set_result(result)

            except Exception as e:
                logger.exception("Error in junction actor step for %s: %s", self.junction_id, str(e))
                if not future.done():
                    future.set_exception(e)
            finally:
                self.mailbox.task_done()

    async def _run_ticker(self) -> None:
        interval = max(0.5, float(self.config.timing.eval_interval_s))
        while self._running:
            try:
                await asyncio.sleep(interval)
                now = datetime.now(timezone.utc)
                if not self.mailbox.full():
                    tick_future = asyncio.get_running_loop().create_future()
                    await self.mailbox.put((Tick(now=now), tick_future))
                    # don't wait on tick future to avoid blocking ticker
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Error in ticker loop for %s: %s", self.junction_id, e)

    async def _dispatch_controller_command(self, cmd_effect: SendControllerCommand) -> None:
        cmd = ControllerCommand(
            command_id=cmd_effect.command_id,
            junction_id=cmd_effect.junction_id,
            direction=cmd_effect.direction,
            requested_state=cmd_effect.requested_state,
            issued_at=cmd_effect.issued_at,
        )
        try:
            await self.controller.send(cmd)
        except ControllerUnavailable:
            logger.warning("Controller unavailable when sending command %s", cmd.command_id)

    async def _publish_snapshot(self) -> None:
        if not self.state:
            return
        snapshot = self.get_status_snapshot()
        await self.publisher.publish(self.junction_id, "junction_updated", snapshot)

    def get_status_snapshot(self) -> dict[str, Any]:
        """Builds public status snapshot for REST API and SSE stream."""
        if not self.state:
            return {}
        s = self.state
        queues = s.get_queue_counts()
        return {
            "junction_id": s.junction_id,
            "version": s.version,
            "mode": s.mode.value,
            "suspended_mode": s.suspended_mode.value if s.suspended_mode else None,
            "stage": s.stage.value,
            "stage_status": s.stage_status.value,
            "active_phase": s.active_phase,
            "target_phase": s.target_phase,
            "stage_started_at": s.stage_started_at.isoformat() if s.stage_started_at else None,
            "stage_timer_started_at": s.stage_timer_started_at.isoformat() if s.stage_timer_started_at else None,
            "desired_signals": {d.value: sig.value for d, sig in s.desired_signals.items()},
            "actual_signals": {d.value: sig.value for d, sig in s.actual_signals.items()},
            "queues": {d.value: count for d, count in queues.items()},
            "controller_status": s.controller_status.value,
            "device_status": {k: v.value for k, v in s.device_status.items()},
            "manual": {
                "owner": s.manual_owner,
                "direction": s.manual_direction.value if s.manual_direction else None,
                "expires_at": s.manual_expires_at.isoformat() if s.manual_expires_at else None,
            },
            "active_emergencies": [
                {
                    "id": em.id,
                    "direction": em.direction.value,
                    "vehicle_id": em.vehicle_id,
                    "status": em.status.value,
                    "detected_at": em.detected_at.isoformat(),
                }
                for em in s.emergencies
                if em.status.value in ("ACTIVE", "SERVING")
            ],
            "pending_commands": [
                {
                    "command_id": c.command_id,
                    "direction": c.direction.value,
                    "requested_state": c.requested_state.value,
                    "attempts": c.attempts,
                    "sent_at": c.sent_at.isoformat(),
                }
                for c in s.pending_commands.values()
            ],
            "updated_at": s.updated_at.isoformat() if s.updated_at else None,
        }
