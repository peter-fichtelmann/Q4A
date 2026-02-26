import logging
from core.game_state import GameState
from core.game_logic.basic_logic import BasicLogic
from core.game_logic.volleyball_logic import VolleyballLogic
from core.game_logic.dodgeball_logic import DodgeballLogic
from core.game_logic.physical_contact_logic import PhysicalContactLogic
from core.game_logic.boundary_logic import BoundaryLogic
from core.game_logic.penalty_logic import PenaltyLogic
from core.game_logic.process_action_logic import ProcessActionLogic
from core.game_logic.utility_logic import UtilityLogic

# Configure logger for game logic subsystem
logger = logging.getLogger('quadball.game_logic')

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
    
    def __init__(self, game_state: GameState, log_level: int = logging.DEBUG):
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
        """
        self.state = game_state
        


        # Initialize distance dictionaries for all entities
        entities_list = list(list(self.state.players.values()) + list(self.state.balls.values()))
        for entity in entities_list:
            self.state.squared_distances_dicts[entity.id] = {}

        # Create penalty_logic first since other classes depend on it
        self.penalty_logic = PenaltyLogic(self.state)
        
        # Inject dependencies only where needed
        self.basic_logic = BasicLogic(self.state, penalty_logic=self.penalty_logic)
        self.dodgeball_logic = DodgeballLogic(self.state, penalty_logic=self.penalty_logic)
        
        # Other classes have no cross-dependencies
        self.volleyball_logic = VolleyballLogic(self.state)
        self.physical_contact_logic = PhysicalContactLogic(self.state)
        self.boundary_logic = BoundaryLogic(self.state)
        self.process_action_logic = ProcessActionLogic(self.state)
        self.utility_logic = UtilityLogic(self.state)
        # # compile static functions for initial warmup of numba
        # UtilityLogic._distance_numba(0.5, 0.5, 0.5, 0.5)
        # UtilityLogic._squared_distance_numba(0.5, 0.5, 0.5, 0.5)
        # UtilityLogic._magnitude_numba(0.5, 0.5)
        # UtilityLogic._square_sum(0.5, 0.5)

    def copy(self, log_level = None) -> 'GameLogic':
        if log_level is None:
            log_level = logger.level
        return GameLogic(self.state.copy(), log_level=log_level)
    
    def set_logger_level(self, log_level: int):
        # Configure logger level
        logger.setLevel(log_level)
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter('[%(levelname)s] %(message)s'))
            logger.addHandler(handler)
    
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