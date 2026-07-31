import logging
from core.game_state import GameState
from core.entities import Player, FlagRunner, PlayerRole, Vector2
from core.game_logic.utility_logic import UtilityLogic


BASE_LOGGER = logging.getLogger('quadball.game_logic')

class FlagRunnerLogic:
    def __init__(self,
                 game_state: GameState,
                 logger: logging.Logger | None = None
                 ):
        """
        Initialize flag logic.

        Args:
            game_state: The active GameState instance. Avoidance tuning
                (seeker_avoidance_factor, boundary_avoidance_factor, boundary_epsilon)
                is read from the game state itself, not passed here.
            logger: Optional logger for logging events. If None, uses BASE_LOGGER.
        """
        self.state = game_state
        self.logger = logger or BASE_LOGGER

    def update_flag_runner_direction(self):
        """
        Update the direction of the flag runner if the game time is above the flag_runner_floor time threshold
        and there is a flag runner present in the game state.

        The following affect flag runner movement:
        - the midline x position (flag runner tries to stay as close as possibe to the midline)
        - quadratic distances to the seeker -> the closer the more the flag runner tries to avoid that seeker
        - quadratic distances to the boundaries of the field
        """
        if not self.state.flag_runner_on_pitch:
            return

        flag_runner = self.state.flag_runner
        midline_x_direction = self.state.midline_x - flag_runner.position.x
        midline_x_distance = abs(midline_x_direction)
        # limit to 1/-1 if midline_x_distance is greater than 1 to avoid too much influence
        if midline_x_distance > 1:
            midline_x_direction = 1 if midline_x_direction > 0 else -1

        seeker_avoid_direction = Vector2(0, 0)
        if self.state.seeker_on_pitch:
            for player in self.state.players.values():
                if player.role == PlayerRole.SEEKER:
                    if not player.is_knocked_out:
                        squared_distance = UtilityLogic._squared_distance(flag_runner.position, player.position)
                        if squared_distance > 0:
                            # The closer the seeker, the more the flag runner tries to avoid it
                            avoidance_strength = 1 / squared_distance * self.state.flag_runner_seeker_avoidance_factor
                            seeker_avoid_direction.x += (flag_runner.position.x - player.position.x) * avoidance_strength
                            seeker_avoid_direction.y += (flag_runner.position.y - player.position.y) * avoidance_strength

        # Avoid boundaries of the pitch
        boundary_epsilon = self.state.flag_runner_boundary_epsilon
        x_avoidance = 1 / ((flag_runner.position.x - self.state.boundaries_x[0])**2 + boundary_epsilon) - 1 / ((flag_runner.position.x - self.state.boundaries_x[1])**2 + boundary_epsilon)
        y_avoidance = 1 / ((flag_runner.position.y - self.state.boundaries_y[0])**2 + boundary_epsilon) - 1 / ((flag_runner.position.y - self.state.boundaries_y[1])**2 + boundary_epsilon)
        seeker_avoid_boundary_direction = Vector2(x_avoidance * self.state.flag_runner_boundary_avoidance_factor, y_avoidance * self.state.flag_runner_boundary_avoidance_factor)

        flag_runner.direction.x = midline_x_direction + seeker_avoid_direction.x + seeker_avoid_boundary_direction.x
        flag_runner.direction.y = seeker_avoid_direction.y + seeker_avoid_boundary_direction.y

    def update_flag_runner_velocity(self, dt: float) -> None:
        """
        Update the flag runner's velocity based on its current direction and movement parameters.

        Args:
            dt: Delta game time (game time since last frame) in seconds
        """
        if not self.state.flag_runner_on_pitch:
            return
        flag_runner = self.state.flag_runner
        mag_dir = UtilityLogic._magnitude(flag_runner.direction)
        if mag_dir > 1:
            flag_runner.direction.x = flag_runner.direction.x / mag_dir
            flag_runner.direction.y = flag_runner.direction.y / mag_dir
        elif mag_dir < flag_runner.min_dir:
            flag_runner.direction.x = 0
            flag_runner.direction.y = 0
        flag_runner.velocity.x = flag_runner.velocity.x + ( - flag_runner.deacceleration_rate * flag_runner.velocity.x + flag_runner.direction.x * flag_runner.acceleration) * dt
        flag_runner.velocity.y = flag_runner.velocity.y + ( - flag_runner.deacceleration_rate * flag_runner.velocity.y + flag_runner.direction.y * flag_runner.acceleration) * dt
        speed = UtilityLogic._magnitude(flag_runner.velocity)
        if speed > flag_runner.max_speed:
            scale = flag_runner.max_speed / speed
            flag_runner.velocity.x = flag_runner.velocity.x * scale
            flag_runner.velocity.y = flag_runner.velocity.y * scale
        elif (speed < flag_runner.min_speed) and (mag_dir < flag_runner.min_dir):
            flag_runner.velocity.x = 0
            flag_runner.velocity.y = 0

    def update_flag_runner_position(self, dt: float) -> None:
        """
        Update the flag runner's position based on its current velocity and the time delta.

        Args:
            dt: Delta game time (game time since last frame) in seconds
        """
        if not self.state.flag_runner_on_pitch:
            return
        flag_runner = self.state.flag_runner
        flag_runner.position.x = flag_runner.position.x + flag_runner.velocity.x * dt
        flag_runner.position.y = flag_runner.position.y + flag_runner.velocity.y * dt
        


        

        