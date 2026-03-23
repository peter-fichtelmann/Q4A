import logging
from dataclasses import dataclass
from functools import wraps
from time import perf_counter_ns
from typing import Optional
from core.game_state import GameState
from core.game_logic.basic_logic import BasicLogic
from core.game_logic.volleyball_logic import VolleyballLogic
from core.game_logic.dodgeball_logic import DodgeballLogic
from core.game_logic.physical_contact_logic import PhysicalContactLogic
from core.game_logic.boundary_logic import BoundaryLogic
from core.game_logic.penalty_logic import PenaltyLogic
from core.game_logic.process_action_logic import ProcessActionLogic
from core.game_logic.utility_logic import UtilityLogic

# Base logger for game logic subsystem
BASE_LOGGER = logging.getLogger('quadball.game_logic')

class GameLogic:
    """
    Implements the core game rules for quadball.
    This system is SERVER-AUTHORITATIVE, meaning the server runs this logic
    and clients trust its decisions.

    Attributes:
        state: Shared GameState instance used by all logic subsystems.
        penalty_logic: Rule enforcement for turnovers and infractions.
        basic_logic: Movement and ball physics updates.
        dodgeball_logic: Dodgeball interactions and third-dodgeball rules.
        volleyball_logic: Volleyball pickups, goals, and live/dead state.
        physical_contact_logic: Player collision resolution.
        boundary_logic: Boundary, hoop blockage, and inbounding rules.
        process_action_logic: Handles player action inputs (throw, tackle).
        utility_logic: Distance precomputation for efficient collision checks.
    """
    
    def __init__(
        self,
        game_state: GameState,
        log_level: int = logging.DEBUG,
        logger_name: Optional[str] = None,
    ):
        """
        Initialize the game logic system with a reference to the game state.
        
        Sets up distance tracking structures used for efficient collision detection
        and interaction checks between entities (players and balls).

        Attributes initialized:
            state: GameState reference for all rule systems.
            penalty_logic: PenaltyLogic instance created first for dependencies.
            basic_logic: BasicLogic instance for movement and collisions.
            dodgeball_logic: DodgeballLogic instance for dodgeball rules.
            volleyball_logic: VolleyballLogic instance for volleyball rules.
            physical_contact_logic: PhysicalContactLogic instance for player collisions.
            boundary_logic: BoundaryLogic instance for boundary enforcement.
            process_action_logic: ProcessActionLogic instance for player actions.
            utility_logic: UtilityLogic instance for distance precomputation.
        
        Args:
            game_state: The GameState instance that this system will manage
            log_level: Logging level (e.g., logging.DEBUG, logging.INFO, logging.WARNING, logging.ERROR)
            logger_name: Optional logger name. If omitted, an instance-specific
                logger name is generated.
        """
        self.state = game_state
        if logger_name is None:
            logger_name = f"quadball.game_logic.instance.{id(self):x}"
        self.logger = logging.getLogger(logger_name)
        self.set_log_level(log_level)
        
        # Initialize distance dictionaries for all entities
        for player in self.state.players.values():
            self.state.squared_distances_player_player_dicts[player.id] = {}
        for ball in self.state.balls.values():
            self.state.squared_distances_ball_ball_dicts[ball.id] = {}
            self.state.squared_distances_ball_player_dicts[ball.id] = {}
        # entities_list = list(list(self.state.players.values()) + list(self.state.balls.values()))
        # for entity in entities_list:
        #     self.state.squared_distances_dicts[entity.id] = {}

        # Create penalty_logic first since other classes depend on it
        self.penalty_logic = PenaltyLogic(self.state, logger=self.logger)
        
        # Inject dependencies only where needed
        self.basic_logic = BasicLogic(self.state, penalty_logic=self.penalty_logic, logger=self.logger)
        self.dodgeball_logic = DodgeballLogic(self.state, penalty_logic=self.penalty_logic, logger=self.logger)
        
        # Other classes have no cross-dependencies
        self.volleyball_logic = VolleyballLogic(self.state, logger=self.logger)
        self.physical_contact_logic = PhysicalContactLogic(self.state, logger=self.logger)
        self.boundary_logic = BoundaryLogic(self.state, logger=self.logger)
        self.process_action_logic = ProcessActionLogic(self.state, logger=self.logger)
        self.utility_logic = UtilityLogic(self.state)
        self._step_profiler = _GameLogicStepProfiler()
        # # compile static functions for initial warmup of numba
        # UtilityLogic._distance_numba(0.5, 0.5, 0.5, 0.5)
        # UtilityLogic._squared_distance_numba(0.5, 0.5, 0.5, 0.5)
        # UtilityLogic._magnitude_numba(0.5, 0.5)
        # UtilityLogic._square_sum(0.5, 0.5)

    def update(self, dt: float) -> None:
        """
        Update game logic each frame (SERVER-AUTHORITATIVE).
        
        This method executes the complete game state update in a carefully ordered sequence.
        
        Args:
            dt: Delta game time in seconds since last frame
        """
        # Update game time
        self.state.update_game_time(dt)
        
        self.basic_logic.update_player_velocities(dt)
        # Check player collisions and enforce tackle effects before updating positions and after updating player velocities
        self.physical_contact_logic._check_player_collisions()
        # after collisions before updating positions so setting velocity to 0 when tackling takes effect before position updates and after velocity updates
        self.physical_contact_logic._enforce_tackle()

        self.basic_logic.update_ball_velocities(dt)
        
        # Update player positions and ball positions
        self.basic_logic.update_positions(dt)
        self.basic_logic.check_keeper_special_powers() # e.g. dodgeball immunity, protected keeper
        # free way for volleyball inbounder
        self.boundary_logic._inbounding_free_way(dt)
        self.boundary_logic._making_alive_keeper_free_way(dt)
        self.boundary_logic._enforce_hoop_blockage() # after update positions because possibly resetting to previous position
        self.volleyball_logic.make_volleyball_alive()
        
        self.utility_logic._calculate_distances()
        self.basic_logic._check_ball_collisions() # after distance calculation

        self.volleyball_logic._check_volleyball_possessions()
        self.dodgeball_logic._check_dodgeball_interactions()

        self.volleyball_logic._check_goals()

        self.dodgeball_logic._check_third_dodgeball(dt)
        self.penalty_logic._check_delay_of_game(dt)
        
        # Check pitch boundaries
        self.boundary_logic._enforce_pitch_boundaries() # at least after free ways and position updates

    def copy(self, log_level = None) -> 'GameLogic':
        if log_level is None:
            log_level = self.logger.level
        return GameLogic(self.state.copy(), log_level=log_level)
    
    def set_log_level(self, log_level: int):
        # Configure logger level
        self.logger.setLevel(log_level)
        if not self.logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter('[%(levelname)s] %(name)s: %(message)s'))
            self.logger.addHandler(handler)
        self.logger.propagate = False

    def set_logger_level(self, log_level: int):
        # Backward-compatible alias
        self.set_log_level(log_level)

    def _build_step_profile_targets(self) -> list[tuple[str, object, str]]:
        """Return ordered step targets executed by update()."""
        return [
            ('state.update_game_time', self.state, 'update_game_time'),
            ('basic.update_player_velocities', self.basic_logic, 'update_player_velocities'),
            ('physical._check_player_collisions', self.physical_contact_logic, '_check_player_collisions'),
            ('physical._enforce_tackle', self.physical_contact_logic, '_enforce_tackle'),
            ('basic.update_ball_velocities', self.basic_logic, 'update_ball_velocities'),
            ('basic.update_positions', self.basic_logic, 'update_positions'),
            ('basic.check_keeper_special_powers', self.basic_logic, 'check_keeper_special_powers'),
            ('boundary._inbounding_free_way', self.boundary_logic, '_inbounding_free_way'),
            ('boundary._making_alive_keeper_free_way', self.boundary_logic, '_making_alive_keeper_free_way'),
            ('boundary._enforce_hoop_blockage', self.boundary_logic, '_enforce_hoop_blockage'),
            ('volleyball.make_volleyball_alive', self.volleyball_logic, 'make_volleyball_alive'),
            ('utility._calculate_distances', self.utility_logic, '_calculate_distances'),
            ('basic._check_ball_collisions', self.basic_logic, '_check_ball_collisions'),
            ('volleyball._check_volleyball_possessions', self.volleyball_logic, '_check_volleyball_possessions'),
            ('dodgeball._check_dodgeball_interactions', self.dodgeball_logic, '_check_dodgeball_interactions'),
            ('volleyball._check_goals', self.volleyball_logic, '_check_goals'),
            ('dodgeball._check_third_dodgeball', self.dodgeball_logic, '_check_third_dodgeball'),
            ('penalty._check_delay_of_game', self.penalty_logic, '_check_delay_of_game'),
            ('boundary._enforce_pitch_boundaries', self.boundary_logic, '_enforce_pitch_boundaries'),
        ]

    def enable_step_profiling(self, reset_stats: bool = True) -> None:
        if reset_stats:
            self._step_profiler.reset()
        self._step_profiler.attach(self._build_step_profile_targets())

    def disable_step_profiling(self) -> None:
        self._step_profiler.detach()

    def get_step_profile_report(self) -> list[dict[str, float | int | str]]:
        return self._step_profiler.report()

    def reset_step_profile(self) -> None:
        self._step_profiler.reset()
    



@dataclass
class _StepProfileStats:
    calls: int = 0
    total_ns: int = 0
    max_ns: int = 0

    def add(self, elapsed_ns: int) -> None:
        self.calls += 1
        self.total_ns += elapsed_ns
        if elapsed_ns > self.max_ns:
            self.max_ns = elapsed_ns


class _GameLogicStepProfiler:
    """Optional runtime profiler for selected GameLogic sub-steps."""

    def __init__(self):
        self.enabled: bool = False
        self.stats: dict[str, _StepProfileStats] = {}
        self._originals: dict[tuple[int, str], tuple[object, object]] = {}

    def reset(self) -> None:
        self.stats.clear()

    def attach(self, targets: list[tuple[str, object, str]]) -> None:
        if self.enabled:
            return

        for label, target_obj, method_name in targets:
            key = (id(target_obj), method_name)
            if key in self._originals:
                continue

            original_method = getattr(target_obj, method_name)
            self._originals[key] = (target_obj, original_method)
            stats = self.stats.setdefault(label, _StepProfileStats())

            @wraps(original_method)
            def wrapped(*args, _original=original_method, _stats=stats, **kwargs):
                start_ns = perf_counter_ns()
                try:
                    return _original(*args, **kwargs)
                finally:
                    _stats.add(perf_counter_ns() - start_ns)

            setattr(target_obj, method_name, wrapped)

        self.enabled = True

    def detach(self) -> None:
        if not self.enabled and not self._originals:
            return

        for (_, method_name), (target_obj, original_method) in list(self._originals.items()):
            setattr(target_obj, method_name, original_method)
        self._originals.clear()
        self.enabled = False

    def report(self) -> list[dict[str, float | int | str]]:
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
