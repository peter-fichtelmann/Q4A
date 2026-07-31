from core.game_state import GameState, PlayerRole

class SeekerDirector:
    """
    The SeekerDirector class is responsible for managing the behavior of the seeker player in the game.
    It determines the seeker's actions based on the current game state, including the positions of other players,
    the flag, and the overall game dynamics.
    """
    def __init__(self, state: GameState):
        self.state = state

    def update_seeker_direction(self) -> None:
        if self.state.seeker_on_pitch and self.state.flag_runner_on_pitch:
            for player in self.state.players.values():
                if player.role == PlayerRole.SEEKER:
                    if not player.is_knocked_out:
                        if self.state.flag_runner is not None:
                            # move towards the flag runner's position
                            player.direction.x = self.state.flag_runner.position.x - player.position.x
                            player.direction.y = self.state.flag_runner.position.y - player.position.y