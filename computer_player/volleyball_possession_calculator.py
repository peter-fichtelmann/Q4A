from dataclasses import dataclass
from typing import Optional

from core.entities import PlayerRole, Vector2
from core.game_logic.game_logic import GameLogic
from computer_player.computer_player_utility.interception_calculator import InterceptionCalculator


@dataclass
class VolleyballPossession:
    """Team in (expected) volleyball possession, the (expected) holder, and where a loose ball gets intercepted."""
    team: Optional[int]
    player_id: Optional[str]
    intercepting_position: Optional[Vector2] = None


class VolleyballPossessionCalculator:
    """
    Determine which team is in possession of the volleyball and thus on attack.

    For a held, dead, inbounded or turned over volleyball this is given by the game state.
    For a loose volleyball, the chaser/keeper predicted to reach it first decides.
    """
    def __init__(self, logic: GameLogic, interception_calculator: InterceptionCalculator):
        """Bind game logic and the interception model."""
        self.logic = logic
        self.interception_calculator = interception_calculator

    def __call__(self, dt: float) -> VolleyballPossession:
        """Infer the attacking team, the expected next holder id, and an optional intercept point."""
        volleyball = self.logic.state.volleyball
        if volleyball.turnover_to_player is not None:
            player = self.logic.state.players[volleyball.turnover_to_player]
            return VolleyballPossession(player.team, player.id)
        if volleyball.inbounder is not None:
            player = self.logic.state.players[volleyball.inbounder]
            return VolleyballPossession(player.team, player.id)
        if volleyball.holder_id is not None:
            return VolleyballPossession(volleyball.possession_team, volleyball.holder_id)
        if volleyball.is_dead:
            volleyball_holder_id = None
            # get keeper who might get control of dead volleyball
            for player in self.logic.state.players.values():
                if player.has_ball == volleyball.id:
                    volleyball_holder_id = player.id
                    break
            return VolleyballPossession(volleyball.possession_team, volleyball_holder_id)
        lowest_interception_time, assigned_player_id, _ = self.interception_calculator.line_interception(
            moving_entity=volleyball,
            intercepting_player_ids=[player.id for player in self.logic.state.players.values() if player.role in [PlayerRole.CHASER, PlayerRole.KEEPER]],
        )
        if assigned_player_id is not None:
            assigned_player = self.logic.state.players[assigned_player_id]
            interception_position = self.interception_calculator.get_aim_position(assigned_player, volleyball, lowest_interception_time)
            return VolleyballPossession(assigned_player.team, assigned_player_id, interception_position)
        # If no intercepting players, determine attacking team based on proximity to volleyball
        for other_id, distance in self.logic.state.squared_distances_ball_player.get(volleyball.id, []):
            player = self.logic.state.players[other_id]
            if not player.is_knocked_out:
                if player.role in [PlayerRole.CHASER, PlayerRole.KEEPER]:
                    return VolleyballPossession(player.team, player.id)
        # if all players are knocked out
        return VolleyballPossession(None, None)
