from abc import ABC, abstractmethod
from dataclasses import dataclass
import logging
from time import perf_counter_ns
from typing import List
from core.game_logic.game_logic import GameLogic
from core.entities import PlayerRole
import random


@dataclass
class _StepProfileStats:
    """Aggregated timing stats for one profiled step name."""

    calls: int = 0
    total_ns: int = 0
    max_ns: int = 0

    def add(self, elapsed_ns: int) -> None:
        """Record one call duration in nanoseconds."""
        self.calls += 1
        self.total_ns += elapsed_ns
        if elapsed_ns > self.max_ns:
            self.max_ns = elapsed_ns


class _ComputerPlayerStepProfiler:
    """Low-overhead optional profiler for computer-player steps."""

    def __init__(self):
        """Initialize profiler state with profiling disabled."""
        self.enabled: bool = False
        self.stats: dict[str, _StepProfileStats] = {}

    def reset(self) -> None:
        """Clear all collected timing statistics."""
        self.stats.clear()

    def time_call(self, step_name: str, fn, *args, **kwargs):
        """Time a callable when enabled, otherwise run it directly."""
        if not self.enabled:
            return fn(*args, **kwargs)

        stats = self.stats.setdefault(step_name, _StepProfileStats())
        start_ns = perf_counter_ns()
        try:
            return fn(*args, **kwargs)
        finally:
            stats.add(perf_counter_ns() - start_ns)

    def report(self) -> list[dict[str, float | int | str]]:
        """Return sorted timing rows with call counts and timing summaries."""
        rows = []
        for step_name, stats in self.stats.items():
            avg_ms = (stats.total_ns / stats.calls / 1e6) if stats.calls else 0.0
            rows.append({
                'step': step_name,
                'calls': stats.calls,
                'avg_ms': avg_ms,
                'max_ms': stats.max_ns / 1e6,
                'total_ms': stats.total_ns / 1e6,
            })
        rows.sort(key=lambda item: float(item['total_ms']), reverse=True)
        return rows

class ComputerPlayer(ABC):
    """
    Base class for CPU-controlled team behavior.

    Subclasses implement `make_move` and set per-player directions/actions for one
    simulation step.
    """
    def __init__(self, game_logic: GameLogic, computer_player_log_level: int = logging.INFO):
        """Bind game logic. The controlled players are supplied per `make_move` call."""
        self.logic = game_logic
        # Filled by `_bind_cpu_players` at the start of every make_move. Which players
        # the CPU drives changes during a match (humans hand players back and forth),
        # so none of this may be resolved once at construction time.
        self.cpu_player_ids: List[str] = []
        self.cpu_player_id_set: set = set()
        self.cpu_players: List = []
        self.cpu_seekers: List = []
        self.logger = logging.getLogger("computer_player")
        self.logger.setLevel(computer_player_log_level)
        self._step_profiler = _ComputerPlayerStepProfiler()

    def _bind_cpu_players(self, cpu_player_ids: List[str]) -> None:
        """Resolve the player objects the CPU controls for this move.

        Seekers are kept apart from `cpu_players`: they are steered by the
        SeekerDirector, while `cpu_players` feeds the chaser/keeper/beater tactics.
        Unknown ids are skipped instead of raising.
        The held tackles of the previous and current players are released; the strategies set them again.
        """
        players = self.logic.state.players
        for player_id in self.cpu_player_id_set.union(cpu_player_ids):
            player = players.get(player_id)
            if player is not None:
                player.is_holding_tackle = False
        self.cpu_player_ids = cpu_player_ids
        self.cpu_player_id_set = set(cpu_player_ids)
        self.cpu_players = []
        self.cpu_seekers = []
        for player_id in cpu_player_ids:
            player = players.get(player_id)
            if player is None:
                continue
            if player.role == PlayerRole.SEEKER:
                self.cpu_seekers.append(player)
            else:
                self.cpu_players.append(player)

    def enable_step_profiling(self, reset_stats: bool = True) -> None:
        """Enable internal step profiling, optionally clearing prior stats."""
        if reset_stats:
            self._step_profiler.reset()
        self._step_profiler.enabled = True

    def disable_step_profiling(self) -> None:
        """Disable internal step profiling."""
        self._step_profiler.enabled = False

    def get_step_profile_report(self) -> list[dict[str, float | int | str]]:
        """Return profiling rows ordered by total time descending."""
        return self._step_profiler.report()

    def reset_step_profile(self) -> None:
        """Clear collected profiling data."""
        self._step_profiler.reset()

    def _profile_call(self, step_name: str, fn, *args, **kwargs):
        """Execute a callable through the step profiler wrapper."""
        return self._step_profiler.time_call(step_name, fn, *args, **kwargs)

    @abstractmethod
    def make_move(self, dt: float, cpu_player_ids: List[str]):
        """Compute CPU actions for one game tick of length `dt` for `cpu_player_ids`."""
        pass


class RandomComputerPlayer(ComputerPlayer):
    """Simple CPU that jitters movement and throws with fixed probability."""

    def __init__(self,
                 game_logic: GameLogic,
                 throwing_probability: float = 0.1,
                 computer_player_log_level: int = logging.INFO):
        """Create a random baseline controller."""
        super().__init__(game_logic, computer_player_log_level=computer_player_log_level)
        self.throwing_probability = throwing_probability

    def make_move(self, dt: float, cpu_player_ids: List[str]):
        """Apply random movement, occasional throws, and default tackle attempts."""
        self._bind_cpu_players(cpu_player_ids)
        # add random number between -1 and 1 to the x and y direction of each CPU player
        # print(f'[CPU Player] Making move for {len(self.cpu_players)} CPU players')
        for player in self.cpu_players:
            player.direction.x += random.uniform(-1, 1)
            player.direction.y += random.uniform(-1, 1)
            throwing_decision = random.random() < self.throwing_probability
            if throwing_decision:
                self._profile_call('random.process_throw_action', self.logic.process_action_logic.process_throw_action, player.id)
            # always try to tackle if not throwing
            player.is_holding_tackle = True

