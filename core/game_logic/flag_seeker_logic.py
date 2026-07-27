import logging
from core.game_state import GameState
from core.entities import Player, FlagRunner

BASE_LOGGER = logging.getLogger('quadball.game_logic')

class FlagSeekerLogic:
    def __init__(self, game_state: GameState, logger: logging.Logger | None = None):
        """
        Initialize flag seeker logic.

        Args:
            game_state: The active GameState instance.
            logger: Optional logger for logging events. If None, uses BASE_LOGGER.
        """
        self.state = game_state
        self.logger = logger or BASE_LOGGER

    def move_flag_runner(self):
        """
        Move the flag runner if the game time is above the flag_runner_floor time threshold.
        """
        if not self.state.game_time > self.state.flag_runner_floor_seconds:
            self.logger.debug("Game time below flag runner floor; flag runner cannot move.")
            return  # Flag runner cannot move yet

        if self.state.flag_runner is None:
            self.logger.warning("No flag runner present in the game state.")
            return  # No flag runner to move