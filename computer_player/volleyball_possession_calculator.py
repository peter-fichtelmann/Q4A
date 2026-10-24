from dataclasses import dataclass
from typing import Dict, Optional, Tuple

from core.entities import PlayerRole, Vector2
from core.game_logic.game_logic import GameLogic
from computer_player.computer_player_utility.interception_calculator import InterceptionCalculator


@dataclass
class VolleyballPossession:
    """
    Team in (expected) volleyball possession, the (expected) holder, and where a loose ball gets intercepted.

    For a loose volleyball, `contester_id` is the fastest player of the other team if it is close enough
    in time to race for the volleyball as well, with its own intercepting position.
    """
    team: Optional[int]
    player_id: Optional[str]
    intercepting_position: Optional[Vector2] = None
    contester_id: Optional[str] = None
    contester_intercepting_position: Optional[Vector2] = None


class VolleyballPossessionCalculator:
    """
    Determine which team is in possession of the volleyball and thus on attack.

    For a held, dead, inbounded or turned over volleyball this is given by the game state.
    For a loose volleyball, the chaser/keeper predicted to reach it first decides. To keep the
    formations from flipping back and forth during a pass, the predicted team only changes if the
    other team's fastest player is faster by `possession_switch_margin`. The other team's fastest
    player still contests the volleyball if it is at most `loose_ball_contest_margin` slower.
    """
    def __init__(self,
                 logic: GameLogic,
                 interception_calculator: InterceptionCalculator,
                 possession_switch_margin: float = 0.0, # game seconds the other team has to be faster to take over the predicted possession
                 loose_ball_contest_margin: Optional[float] = None, # game seconds; None: nobody contests
                 ):
        """Bind game logic and the interception model."""
        self.logic = logic
        self.interception_calculator = interception_calculator
        self.possession_switch_margin = possession_switch_margin
        self.loose_ball_contest_margin = loose_ball_contest_margin
        self._previous_team: Optional[int] = None

    def __call__(self, dt: float) -> VolleyballPossession:
        """Infer the attacking team, the expected next holder id, and an optional intercept point."""
        possession = self._possession()
        if possession.team is not None:
            self._previous_team = possession.team
        return possession

    def _possession(self) -> VolleyballPossession:
        """Possession from the game state, or predicted for a loose volleyball."""
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
        _, assigned_player_id, interception_info_dict = self.interception_calculator.line_interception(
            moving_entity=volleyball,
            intercepting_player_ids=[player.id for player in self.logic.state.players.values() if player.role in [PlayerRole.CHASER, PlayerRole.KEEPER]],
        )
        if assigned_player_id is not None:
            fastest = self._fastest_per_team(interception_info_dict)
            team = self.logic.state.players[assigned_player_id].team
            previous_team = self._previous_team
            if (previous_team is not None and previous_team != team and previous_team in fastest
                    and fastest[team][0] > fastest[previous_team][0] - self.possession_switch_margin):
                team = previous_team # not faster by the switch margin: keep the predicted possession
            interception_time, player_id = fastest[team]
            possession = VolleyballPossession(team, player_id, self._aim_position(player_id, interception_time))
            other_team = 1 - team
            if (self.loose_ball_contest_margin is not None and other_team in fastest
                    and fastest[other_team][0] <= interception_time + self.loose_ball_contest_margin):
                contest_time, contester_id = fastest[other_team]
                possession.contester_id = contester_id
                possession.contester_intercepting_position = self._aim_position(contester_id, contest_time)
            return possession
        # If no intercepting players, determine attacking team based on proximity to volleyball
        for other_id, distance in self.logic.state.squared_distances_ball_player.get(volleyball.id, []):
            player = self.logic.state.players[other_id]
            if not player.is_knocked_out:
                if player.role in [PlayerRole.CHASER, PlayerRole.KEEPER]:
                    return VolleyballPossession(player.team, player.id)
        # if all players are knocked out
        return VolleyballPossession(None, None)

    def _fastest_per_team(self, interception_info_dict: Dict[str, float]) -> Dict[int, Tuple[float, str]]:
        """Lowest interception time and player id per team (the first player wins ties, like line_interception)."""
        fastest = {}
        for player_id, interception_time in interception_info_dict.items():
            team = self.logic.state.players[player_id].team
            if team not in fastest or interception_time < fastest[team][0]:
                fastest[team] = (interception_time, player_id)
        return fastest

    def _aim_position(self, player_id: str, interception_time: float) -> Vector2:
        """Where `player_id` steers to intercept the volleyball at `interception_time`."""
        player = self.logic.state.players[player_id]
        return self.interception_calculator.get_aim_position(player, self.logic.state.volleyball, interception_time)
