from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional

from app.domain.config import JunctionConfig
from app.domain.effects import (
    DomainEffect,
    PublishUpdate,
    RecordAudit,
    SendControllerCommand,
)
from app.domain.events import expire_ghost_vehicles, process_sensor_event
from app.domain.inputs import (
    AdminCommand,
    ControllerAck,
    DeviceStatusUpdate,
    DomainInput,
    Recover,
    SensorEvent,
    Tick,
)
from app.domain.model import (
    CommandStatus,
    DeviceStatus,
    Direction,
    JunctionState,
    Mode,
    PendingCommand,
    Signal,
    StageKind,
    StageStatus,
)
from app.domain.safety import SafetyViolation, check_invariants
from app.domain.scheduler import select_best_candidate_phase, should_switch_phase
from app.domain.stages import (
    create_stage_commands,
    enter_all_red,
    enter_green,
    enter_yellow,
)


@dataclass
class EngineResult:
    state: JunctionState
    effects: list[DomainEffect] = field(default_factory=list)
    outcome: str = "PROCESSED"
    details: Optional[dict[str, Any]] = None


class TrafficEngine:
    """Pure domain reducer for junction traffic control."""

    def handle(
        self,
        state: JunctionState,
        config: JunctionConfig,
        domain_input: DomainInput,
        now: datetime,
    ) -> EngineResult:
        """
        Pure function: reduces state and produces side effects.
        All safety invariants are verified prior to returning.
        """
        effects: list[DomainEffect] = []
        outcome = "PROCESSED"
        details: dict[str, Any] = {}

        state.updated_at = now

        try:
            if isinstance(domain_input, Recover):
                outcome = self._handle_recover(state, config, domain_input, now, effects)
            elif isinstance(domain_input, ControllerAck):
                outcome = self._handle_controller_ack(state, config, domain_input, now, effects)
            elif isinstance(domain_input, SensorEvent):
                outcome, event_effects = process_sensor_event(state, config, domain_input, now)
                effects.extend(event_effects)
            elif isinstance(domain_input, Tick):
                outcome = self._handle_tick(state, config, domain_input, now, effects)
            elif isinstance(domain_input, DeviceStatusUpdate):
                outcome = self._handle_device_status(state, config, domain_input, now, effects)
            else:
                # Other inputs (AdminCommand) handled in Phase 3
                outcome = "UNHANDLED_INPUT"

            # Check invariants
            check_invariants(state, config)

        except SafetyViolation as sv:
            # Force DEGRADED fail-safe state
            state.mode = Mode.DEGRADED
            for d in Direction:
                state.desired_signals[d] = Signal.RED
            effects.append(
                RecordAudit(
                    junction_id=state.junction_id,
                    server_ts=now,
                    event_type="SAFETY_VIOLATION_TRIGGERED",
                    mode=Mode.DEGRADED.value,
                    message=f"Safety invariant violated: {str(sv)}. System forced into DEGRADED all RED.",
                )
            )
            # Send fail-safe ALL_RED commands
            dirs = list(Direction)
            cmds, cmd_effects = create_stage_commands(state, dirs, Signal.RED, now)
            for c in cmds:
                state.pending_commands[c.command_id] = c
            effects.extend(cmd_effects)
            outcome = "SAFETY_VIOLATION_FAILSAFE"

        # Increment state version on any state mutation
        state.version += 1
        effects.append(PublishUpdate(junction_id=state.junction_id))

        return EngineResult(state=state, effects=effects, outcome=outcome, details=details)

    def _handle_recover(
        self,
        state: JunctionState,
        config: JunctionConfig,
        input_cmd: Recover,
        now: datetime,
        effects: list[DomainEffect],
    ) -> str:
        # Mark all actual signals as UNKNOWN (never trust physical state on restart)
        for d in Direction:
            state.actual_signals[d] = Signal.UNKNOWN

        # Supersede any leftover pending commands
        for cmd_id, cmd in list(state.pending_commands.items()):
            state.pending_commands[cmd_id] = PendingCommand(
                command_id=cmd.command_id,
                junction_id=cmd.junction_id,
                direction=cmd.direction,
                requested_state=cmd.requested_state,
                stage=cmd.stage,
                attempts=cmd.attempts,
                sent_at=cmd.sent_at,
                status=CommandStatus.SUPERSEDED,
            )
            effects.append(
                RecordAudit(
                    junction_id=state.junction_id,
                    server_ts=now,
                    event_type="COMMAND_SUPERSEDED",
                    command_id=cmd_id,
                    mode=state.mode.value,
                    message="Command superseded due to restart recovery",
                )
            )
        state.pending_commands.clear()

        # Enter ALL_RED safe stage and issue fresh commands for all directions
        stage_effects = enter_all_red(
            state,
            config,
            now,
            reason="Restart recovery initiated: force safe ALL_RED re-sync",
            force_all_directions=True,
        )
        effects.extend(stage_effects)
        return "RECOVERED"

    def _handle_controller_ack(
        self,
        state: JunctionState,
        config: JunctionConfig,
        ack: ControllerAck,
        now: datetime,
        effects: list[DomainEffect],
    ) -> str:
        cmd = state.pending_commands.get(ack.command_id)

        if not cmd:
            # Late, duplicate, or unknown ACK
            state.actual_signals[ack.direction] = ack.reported_state
            effects.append(
                RecordAudit(
                    junction_id=state.junction_id,
                    server_ts=now,
                    event_type="CONTROLLER_ACK_ORPHAN",
                    direction=ack.direction,
                    new_state=ack.reported_state.value,
                    command_id=ack.command_id,
                    mode=state.mode.value,
                    message=f"Received ACK for unknown/superseded command {ack.command_id}; updated physical actual signal",
                )
            )
            return "DUPLICATE_OR_LATE_ACK"

        # Check for state match and success status
        if ack.status in ("SUCCESS", "ACK") and ack.reported_state == cmd.requested_state:
            # Command successfully ACKed
            state.actual_signals[ack.direction] = ack.reported_state
            del state.pending_commands[ack.command_id]

            effects.append(
                RecordAudit(
                    junction_id=state.junction_id,
                    server_ts=now,
                    event_type="COMMAND_ACKED",
                    direction=ack.direction,
                    new_state=ack.reported_state.value,
                    command_id=ack.command_id,
                    mode=state.mode.value,
                    message=f"Command {ack.command_id} confirmed by controller for {ack.direction.value} -> {ack.reported_state.value}",
                )
            )

            # Check if all pending commands for current stage have been confirmed
            stage_pending = [
                c for c in state.pending_commands.values()
                if c.status == CommandStatus.PENDING
            ]

            if not stage_pending and state.stage_status == StageStatus.AWAITING_ACK:
                state.stage_status = StageStatus.TIMING
                state.stage_timer_started_at = now
                if state.stage == StageKind.GREEN and state.active_phase:
                    state.phase_last_green_at[state.active_phase] = now

                effects.append(
                    RecordAudit(
                        junction_id=state.junction_id,
                        server_ts=now,
                        event_type="STAGE_TIMING_STARTED",
                        mode=state.mode.value,
                        message=f"All commands ACKed for stage {state.stage.value}; stage timer started",
                    )
                )

                # If junction was DEGRADED and all ALL_RED commands are confirmed, can recover
                if state.mode == Mode.DEGRADED:
                    all_red_confirmed = all(
                        state.actual_signals.get(d) == Signal.RED for d in Direction
                    )
                    if all_red_confirmed and state.controller_status != DeviceStatus.OFFLINE:
                        state.mode = Mode.AUTOMATIC
                        state.stage = StageKind.ALL_RED
                        state.stage_status = StageStatus.TIMING
                        state.stage_timer_started_at = now
                        effects.append(
                            RecordAudit(
                                junction_id=state.junction_id,
                                server_ts=now,
                                event_type="DEGRADED_RECOVERED",
                                mode=Mode.AUTOMATIC.value,
                                message="All physical signals confirmed RED; recovered from DEGRADED to AUTOMATIC",
                            )
                        )

            return "ACKED"
        else:
            # Mismatch or failure reported by controller
            effects.append(
                RecordAudit(
                    junction_id=state.junction_id,
                    server_ts=now,
                    event_type="COMMAND_NACK_OR_MISMATCH",
                    direction=ack.direction,
                    command_id=ack.command_id,
                    mode=state.mode.value,
                    message=f"Controller reported mismatch/failure for {ack.command_id}: expected {cmd.requested_state.value}, got {ack.reported_state.value} ({ack.status})",
                )
            )
            # Enter DEGRADED fail-safe state
            self._enter_degraded_failsafe(state, config, now, effects, f"ACK mismatch/failure on {ack.command_id}")
            return "NACK_OR_MISMATCH"

    def _handle_tick(
        self,
        state: JunctionState,
        config: JunctionConfig,
        tick: Tick,
        now: datetime,
        effects: list[DomainEffect],
    ) -> str:
        # Expire ghost vehicles
        ghost_effects = expire_ghost_vehicles(state, config, now)
        effects.extend(ghost_effects)

        # 1. Check ACK timeouts for any pending commands
        timed_out_cmds = []
        for cmd_id, cmd in list(state.pending_commands.items()):
            if cmd.status == CommandStatus.PENDING:
                elapsed_s = (now - cmd.sent_at).total_seconds()
                if elapsed_s >= config.timing.ack_timeout_s:
                    timed_out_cmds.append(cmd)

        for cmd in timed_out_cmds:
            if cmd.attempts < config.timing.ack_max_retries:
                # Retry with same command_id
                updated_cmd = PendingCommand(
                    command_id=cmd.command_id,
                    junction_id=cmd.junction_id,
                    direction=cmd.direction,
                    requested_state=cmd.requested_state,
                    stage=cmd.stage,
                    attempts=cmd.attempts + 1,
                    sent_at=now,
                    status=CommandStatus.PENDING,
                )
                state.pending_commands[cmd.command_id] = updated_cmd
                effects.append(
                    SendControllerCommand(
                        command_id=cmd.command_id,
                        junction_id=cmd.junction_id,
                        direction=cmd.direction,
                        requested_state=cmd.requested_state,
                        issued_at=now,
                    )
                )
                effects.append(
                    RecordAudit(
                        junction_id=state.junction_id,
                        server_ts=now,
                        event_type="COMMAND_RETRY",
                        direction=cmd.direction,
                        command_id=cmd.command_id,
                        mode=state.mode.value,
                        message=f"ACK timeout for {cmd.command_id}. Retrying attempt {updated_cmd.attempts}/{config.timing.ack_max_retries}",
                    )
                )
            else:
                # Retries exhausted -> DEGRADED fail-safe!
                self._enter_degraded_failsafe(
                    state,
                    config,
                    now,
                    effects,
                    f"Retries exhausted ({config.timing.ack_max_retries}) for command {cmd.command_id}",
                )
                return "COMMAND_TIMEOUT_DEGRADED"

        # 2. Advance stage if in TIMING status
        if state.stage_status == StageStatus.TIMING and state.stage_timer_started_at:
            elapsed = (now - state.stage_timer_started_at).total_seconds()

            if state.stage == StageKind.ALL_RED:
                if elapsed >= config.timing.all_red_s:
                    # Select next phase
                    next_phase = self._resolve_next_phase(state, config, now)
                    if next_phase:
                        # Safety check: all conflicting actual signals must be RED!
                        conflicting_dirs = []
                        for other_phase, dirs in config.phases.items():
                            if other_phase != next_phase:
                                conflicting_dirs.extend(dirs)

                        all_conflicting_actual_red = all(
                            state.actual_signals.get(d) == Signal.RED for d in conflicting_dirs
                        )

                        if all_conflicting_actual_red:
                            green_effects = enter_green(state, config, next_phase, now)
                            effects.extend(green_effects)
                            return f"ENTERED_GREEN_{next_phase}"
                        else:
                            effects.append(
                                RecordAudit(
                                    junction_id=state.junction_id,
                                    server_ts=now,
                                    event_type="STAGE_HOLD_SAFETY",
                                    mode=state.mode.value,
                                    message=f"Cannot enter GREEN({next_phase}): conflicting physical signals not confirmed RED: {state.actual_signals}",
                                )
                            )

            elif state.stage == StageKind.YELLOW:
                if elapsed >= config.timing.yellow_s:
                    all_red_effects = enter_all_red(state, config, now)
                    effects.extend(all_red_effects)
                    return "ENTERED_ALL_RED"

            elif state.stage == StageKind.GREEN and state.active_phase:
                if state.mode == Mode.AUTOMATIC:
                    should_switch, target_p, reason = should_switch_phase(
                        state, config, state.active_phase, now, elapsed
                    )
                    if should_switch:
                        state.target_phase = target_p
                        yellow_effects = enter_yellow(state, config, state.active_phase, now, reason=reason)
                        effects.extend(yellow_effects)
                        return "ENTERED_YELLOW"
                else:
                    if self._should_leave_green_fallback(state, config, now, elapsed):
                        yellow_effects = enter_yellow(state, config, state.active_phase, now)
                        effects.extend(yellow_effects)
                        return "ENTERED_YELLOW"

        return "TICK_PROCESSED"

    def _resolve_next_phase(
        self,
        state: JunctionState,
        config: JunctionConfig,
        now: datetime,
    ) -> Optional[str]:
        """Resolves target phase. Prioritizes explicit target, then scheduler ranking."""
        if state.target_phase and state.target_phase in config.phases:
            chosen = state.target_phase
            state.target_phase = None
            return chosen

        best = select_best_candidate_phase(state, config, None, now)
        if best:
            return best

        phases = list(config.phases.keys())
        if not phases:
            return None

        if not state.active_phase:
            return phases[0]

        curr_idx = phases.index(state.active_phase) if state.active_phase in phases else 0
        return phases[(curr_idx + 1) % len(phases)]

    def _should_leave_green_fallback(
        self,
        state: JunctionState,
        config: JunctionConfig,
        now: datetime,
        elapsed_s: float,
    ) -> bool:
        if elapsed_s < config.timing.green_min_s:
            return False
        if elapsed_s >= config.timing.green_max_s:
            return True
        return False

    def _handle_device_status(
        self,
        state: JunctionState,
        config: JunctionConfig,
        device_update: DeviceStatusUpdate,
        now: datetime,
        effects: list[DomainEffect],
    ) -> str:
        key = f"{device_update.component_type.lower()}_{device_update.identifier}"
        state.device_status[key] = device_update.status

        if device_update.component_type == "SIGNAL_CONTROLLER":
            state.controller_status = device_update.status
            if device_update.status == DeviceStatus.OFFLINE:
                self._enter_degraded_failsafe(state, config, now, effects, "Signal controller reported OFFLINE")
                return "CONTROLLER_OFFLINE_DEGRADED"
            elif device_update.status == DeviceStatus.ONLINE and state.mode == Mode.DEGRADED:
                # Trigger safe recovery
                return self._handle_recover(state, config, Recover(junction_id=state.junction_id, now=now), now, effects)

        effects.append(
            RecordAudit(
                junction_id=state.junction_id,
                server_ts=now,
                event_type="DEVICE_STATUS_CHANGED",
                mode=state.mode.value,
                message=f"Device {key} status changed to {device_update.status.value}",
            )
        )
        return "DEVICE_STATUS_UPDATED"

    def _enter_degraded_failsafe(
        self,
        state: JunctionState,
        config: JunctionConfig,
        now: datetime,
        effects: list[DomainEffect],
        reason: str,
    ) -> None:
        """Enters DEGRADED fail-safe mode, sets actual signals UNKNOWN, forces desired ALL_RED."""
        state.mode = Mode.DEGRADED
        state.stage = StageKind.ALL_RED
        state.stage_status = StageStatus.AWAITING_ACK
        state.active_phase = None
        state.target_phase = None
        state.stage_started_at = now
        state.stage_timer_started_at = None

        for d in Direction:
            state.desired_signals[d] = Signal.RED
            state.actual_signals[d] = Signal.UNKNOWN

        # Abandon pending commands
        state.pending_commands.clear()

        effects.append(
            RecordAudit(
                junction_id=state.junction_id,
                server_ts=now,
                event_type="MODE_CHANGED_DEGRADED",
                mode=Mode.DEGRADED.value,
                message=f"Forced DEGRADED mode: {reason}",
            )
        )

        cmds, cmd_effects = create_stage_commands(state, list(Direction), Signal.RED, now)
        for c in cmds:
            state.pending_commands[c.command_id] = c
        effects.extend(cmd_effects)
