from dataclasses import dataclass, field
from app.domain.model import Direction


@dataclass(frozen=True)
class TimingConfig:
    green_max_s: int = 30
    green_min_s: int = 10
    yellow_s: int = 5
    all_red_s: int = 2
    ack_timeout_s: int = 5
    ack_max_retries: int = 2
    eval_interval_s: int = 1
    manual_lease_s: int = 300
    emergency_max_hold_s: int = 60
    emergency_stale_s: int = 120
    vehicle_ttl_s: int = 900
    starvation_max_wait_s: int = 90

    @classmethod
    def demo_profile(cls) -> "TimingConfig":
        return cls(
            green_max_s=12,
            green_min_s=4,
            yellow_s=3,
            all_red_s=1,
            ack_timeout_s=3,
            ack_max_retries=2,
            eval_interval_s=1,
            manual_lease_s=60,
            emergency_max_hold_s=20,
            emergency_stale_s=30,
            vehicle_ttl_s=120,
            starvation_max_wait_s=30,
        )


@dataclass(frozen=True)
class JunctionConfig:
    junction_id: str
    name: str
    timing: TimingConfig = field(default_factory=TimingConfig)
    phases: dict[str, list[Direction]] = field(
        default_factory=lambda: {
            "NORTH_SOUTH": [Direction.NORTH, Direction.SOUTH],
            "EAST_WEST": [Direction.EAST, Direction.WEST],
        }
    )

    def phase_for_direction(self, direction: Direction) -> str | None:
        for phase_name, directions in self.phases.items():
            if direction in directions:
                return phase_name
        return None

    def conflicting_phases(self, phase_name: str) -> list[str]:
        return [p for p in self.phases.keys() if p != phase_name]

    def conflicting_directions(self, direction: Direction) -> list[Direction]:
        my_phase = self.phase_for_direction(direction)
        if not my_phase:
            return []
        conflicts: list[Direction] = []
        for p, dirs in self.phases.items():
            if p != my_phase:
                conflicts.extend(dirs)
        return conflicts

    def directions_for_phase(self, phase_name: str) -> list[Direction]:
        return list(self.phases.get(phase_name, []))
