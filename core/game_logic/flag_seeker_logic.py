import logging
from core.game_state import GameState
from core.entities import Player, FlagRunner, PlayerRole, Vector2
from core.game_logic.utility_logic import UtilityLogic


BASE_LOGGER = logging.getLogger('quadball.game_logic')

class FlagSeekerLogic:
    def __init__(self,
                 game_state: GameState,
                 seeker_avoidance_factor: float = 1.0,
                 logger: logging.Logger | None = None
                 ):
        """
        Initialize flag seeker logic.

        Args:
            game_state: The active GameState instance.
            seeker_avoidance_factor: A factor to control how strongly the flag runner avoids seekers.
            logger: Optional logger for logging events. If None, uses BASE_LOGGER.
        """
        self.state = game_state
        self.seeker_avoidance_factor = seeker_avoidance_factor
        self.logger = logger or BASE_LOGGER

    def move_flag_runner(self):
        """
        Move the flag runner if the game time is above the flag_runner_floor time threshold
        and there is a flag runner present in the game state.

        The following affect flag runner movement:
        - the midline x position (flag runner tries to stay as close as possibe to the midline)
        - quadratic distances to the seeker -> the closer the more the flag runner tries to avoid that seeker
        - quadratic distances to the boundaries of the field
        """
        if not self.state.game_time > self.state.flag_runner_floor_seconds:
            self.logger.debug("Game time below flag runner floor; flag runner cannot move.")
            return  # Flag runner cannot move yet

        flag_runner = self.state.flag_runner
        if flag_runner is None:
            self.logger.warning("No flag runner present in the game state.")
            return  # No flag runner to move

        midline_x_direction = self.state.midline_x - flag_runner.position.x
        midline_x_distance = abs(midline_x_direction)
        # limit to 1/-1 if midline_x_distance is greater than 1 to avoid too much influence
        if midline_x_distance > 1:
            midline_x_direction = 1 if midline_x_direction > 0 else -1

        seeker_avoid_direction = Vector2(0, 0)
        for player in self.state.players.values():
            if player.role == PlayerRole.SEEKER:
                squared_distance = UtilityLogic._squared_distance(flag_runner.position, player.position)
                if squared_distance > 0:
                    # The closer the seeker, the more the flag runner tries to avoid it
                    avoidance_strength = 1 / squared_distance * self.seeker_avoidance_factor
                    seeker_avoid_direction.x += (flag_runner.position.x - player.position.x) * avoidance_strength
                    seeker_avoid_direction.y += (flag_runner.position.y - player.position.y) * avoidance_strength

        seeker_avoid_boundary_direction = Vector2(0, 0)
        # Avoid boundaries of the pitch

        

        