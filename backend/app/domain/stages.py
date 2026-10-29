from datetime import datetime, timezone
import uuid
from typing import Optional

from app.domain.config import JunctionConfig
from app.domain.effects import DomainEffect, RecordAudit, SendControllerCommand
from app.domain.model import (
    CommandStatus,
    Direction,
    JunctionState,
    Mode,
    PendingCommand,
    Signal,
    StageKind,
    StageStatus,
)


def make_command_id(junction_id: str, direction: Direction, now: datetime) -> str:
    ts = int(now.timestamp() * 1000)
    suffix = uuid.uuid4().hex[:6]
    return f"cmd_{junction_id}_{direction.value}_{ts}_{suffix}"


def create_stage_commands(
    state: JunctionState,
    directions: list[Direction],
    requested_state: Signal,
    now: datetime,
) -> tuple[list[PendingCommand], list[DomainEffect]]:
    """Creates commands for the specified directions and returns both pending commands and effects."""
    commands: list[PendingCommand] = []
    effects: list[DomainEffect] = []

    for d in directions:
        cmd_id = make_command_id(state.junction_id, d, now)
        cmd = PendingCommand(
            command_id=cmd_id,
            junction_id=state.junction_id,
            direction=d,
            requested_state=requested_state,
            stage=f"{state.stage.value}:{state.active_phase or 'ALL'}",
            attempts=1,
            sent_at=now,
            status=CommandStatus.PENDING,
        )
        commands.append(cmd)
        effects.append(
            SendControllerCommand(
                command_id=cmd_id,
                junction_id=state.junction_id,
                direction=d,
                requested_state=requested_state,
                issued_at=now,
            )
        )
        effects.append(
            RecordAudit(
                junction_id=state.junction_id,
                server_ts=now,
                event_type="COMMAND_ISSUED",
                direction=d,
                previous_state=state.actual_signals.get(d, Signal.UNKNOWN).value,
                new_state=requested_state.value,
                command_id=cmd_id,
                correlation_id=cmd_id,
                mode=state.mode.value,
                message=f"Issued command {cmd_id} for {d.value} -> {requested_state.value}",
            )
        )

    return commands, effects


def enter_all_red(
    state: JunctionState,
    config: JunctionConfig,
    now: datetime,
    reason: str = "Transition to ALL_RED",
    force_all_directions: bool = False,
) -> list[DomainEffect]:
    """Transitions the junction into ALL_RED stage."""
    prev_phase = state.active_phase
    state.stage = StageKind.ALL_RED
    state.stage_status = StageStatus.AWAITING_ACK
    state.active_phase = None
    state.stage_started_at = now
    state.stage_timer_started_at = None

    if force_all_directions:
        dirs_to_red = list(Direction)
    else:
        dirs_set = set()
        if prev_phase:
            dirs_set.update(config.directions_for_phase(prev_phase))
        for d in Direction:
            if state.desired_signals.get(d) != Signal.RED or state.actual_signals.get(d) != Signal.RED:
                dirs_set.add(d)
        dirs_to_red = list(dirs_set)

    # Set desired signals
    for d in Direction:
        state.desired_signals[d] = Signal.RED

    effects: list[DomainEffect] = []
    effects.append(
        RecordAudit(
            junction_id=state.junction_id,
            server_ts=now,
            event_type="STAGE_CHANGED",
            previous_state=None,
            new_state=StageKind.ALL_RED.value,
            mode=state.mode.value,
            message=reason,
        )
    )

    if dirs_to_red:
        cmds, cmd_effects = create_stage_commands(state, dirs_to_red, Signal.RED, now)
        for c in cmds:
            state.pending_commands[c.command_id] = c
        effects.extend(cmd_effects)
    else:
        # If all directions were already desired RED and actual RED, we can start timing immediately
        all_actual_red = all(
            state.actual_signals.get(d) == Signal.RED for d in Direction
        )
        if all_actual_red:
            state.stage_status = StageStatus.TIMING
            state.stage_timer_started_at = now

    return effects


def enter_yellow(
    state: JunctionState,
    config: JunctionConfig,
    phase: str,
    now: datetime,
    reason: str = "Transition to YELLOW",
) -> list[DomainEffect]:
    """Transitions the active phase into YELLOW stage."""
    state.stage = StageKind.YELLOW
    state.stage_status = StageStatus.AWAITING_ACK
    state.stage_started_at = now
    state.stage_timer_started_at = None

    phase_dirs = config.directions_for_phase(phase)
    for d in phase_dirs:
        state.desired_signals[d] = Signal.YELLOW

    effects: list[DomainEffect] = []
    effects.append(
        RecordAudit(
            junction_id=state.junction_id,
            server_ts=now,
            event_type="STAGE_CHANGED",
            previous_state=StageKind.GREEN.value,
            new_state=f"YELLOW({phase})",
            mode=state.mode.value,
            message=reason,
        )
    )

    cmds, cmd_effects = create_stage_commands(state, phase_dirs, Signal.YELLOW, now)
    for c in cmds:
        state.pending_commands[c.command_id] = c
    effects.extend(cmd_effects)

    return effects


def enter_green(
    state: JunctionState,
    config: JunctionConfig,
    phase: str,
    now: datetime,
    reason: str = "Transition to GREEN",
) -> list[DomainEffect]:
    """Transitions the target phase into GREEN stage."""
    state.stage = StageKind.GREEN
    state.stage_status = StageStatus.AWAITING_ACK
    state.active_phase = phase
    state.target_phase = None
    state.stage_started_at = now
    state.stage_timer_started_at = None

    phase_dirs = config.directions_for_phase(phase)
    for d in phase_dirs:
        state.desired_signals[d] = Signal.GREEN

    effects: list[DomainEffect] = []
    effects.append(
        RecordAudit(
            junction_id=state.junction_id,
            server_ts=now,
            event_type="STAGE_CHANGED",
            previous_state=StageKind.ALL_RED.value,
            new_state=f"GREEN({phase})",
            mode=state.mode.value,
            message=reason,
        )
    )

    cmds, cmd_effects = create_stage_commands(state, phase_dirs, Signal.GREEN, now)
    for c in cmds:
        state.pending_commands[c.command_id] = c
    effects.extend(cmd_effects)

    return effects
