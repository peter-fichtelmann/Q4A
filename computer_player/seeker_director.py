from core.entities import Vector2
from core.game_state import GameState, PlayerRole

class SeekerDirector:
    """
    The SeekerDirector class is responsible for managing the behavior of the seeker player in the game.
    It determines the seeker's actions based on the current game state, including the positions of other players,
    the flag, and the overall game dynamics.
    """
    def __init__(self, state: GameState):
        self.state = state

    def update_seeker_direction(self, dt: float) -> None:
        if self.state.seeker_on_pitch and self.state.flag_runner_on_pitch:
            for player in self.state.players.values():
                if player.role == PlayerRole.SEEKER:
                    if not player.is_knocked_out:
                        if self.state.flag_runner is not None:
                            # move towards the flag runner's nextposition
                            next_flag_runner_position = Vector2(
                                self.state.flag_runner.position.x + self.state.flag_runner.velocity.x * dt,
                                self.state.flag_runner.position.y + self.state.flag_runner.velocity.y * dt
                            )
                            player.direction.x = next_flag_runner_position.x - player.position.x
                            player.direction.y = next_flag_runner_position.y - player.position.y