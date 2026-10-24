import logging
import math
from typing import Dict, List, Optional

from core.entities import Player, PlayerRole, Vector2
from core.game_logic.game_logic import GameLogic
from core.game_logic.utility_logic import UtilityLogic
from computer_player.base_strategy import BaseStrategy, StepContext
from computer_player.computer_player_utility.computer_player_utility import BeaterThrowDecider


class BeaterSeekerFocus(BaseStrategy):
    """
    Beater strategy for the seeker game, for the beaters the orchestrator gives a seeker focus.

    Priority is the seeker game:
        - a loaded beater beats a loaded opponent beater within `loaded_beater_threat_distance`
          of the own seeker, then the opponent seeker if it is within `opponent_seeker_threat_distance`
          of the flag runner, both if within `throw_distance` of the beater,
        - it stands `guard_distance` from the own seeker, towards the closest loaded opponent beater
          (otherwise towards the opponent seeker).
    Opportunity outside the focus: an opponent volleyball holder in range is beaten as by the
    hoop defence (BeaterThrowDecider.should_throw_at_volleyball_holder).

    Focus beaters are the `seeker_focus_beaters` beaters of a team closest to its own seeker when the
    seekers enter, kept while they are on stick (`select`).
    """
    def __init__(self,
                 logic: GameLogic,
                 beater_throw_decider: BeaterThrowDecider,
                 seeker_focus_beaters: int = 0, # per team; 0: no seeker focus
                 guard_distance: float = 2.0, # m
                 throw_distance: float = 5.0, # m
                 loaded_beater_threat_distance: float = 8.0, # m
                 opponent_seeker_threat_distance: float = 4.0, # m
                 logger: Optional[logging.Logger] = None):
        """Store the focus parameters."""
        super().__init__(logic, logger)
        self.beater_throw_decider = beater_throw_decider
        self.seeker_focus_beaters = seeker_focus_beaters
        self.guard_distance = guard_distance
        self.squared_throw_distance = throw_distance**2
        self.squared_loaded_beater_threat_distance = loaded_beater_threat_distance**2
        self.squared_opponent_seeker_threat_distance = opponent_seeker_threat_distance**2
        self._focus_ids: Dict[int, List[str]] = {0: [], 1: []}

    def _seeker(self, team: int) -> Optional[Player]:
        """The team's seeker on stick, if any."""
        for player in self.logic.state.players.values():
            if player.team == team and player.role == PlayerRole.SEEKER and not player.is_knocked_out:
                return player
        return None

    def select(self, team: int) -> List[str]:
        """Ids of the team's seeker focus beaters in this step (empty before the seekers enter)."""
        state = self.logic.state
        seeker = self._seeker(team)
        if self.seeker_focus_beaters <= 0 or not state.seeker_on_pitch or seeker is None:
            self._focus_ids[team] = []
            return []
        beaters = [player for player in state.players.values() if player.team == team and player.role == PlayerRole.BEATER]
        kept = [player_id for player_id in self._focus_ids[team] if not state.players[player_id].is_knocked_out]
        candidates = sorted(
            (beater for beater in beaters if beater.id not in kept and not beater.is_knocked_out),
            key=lambda beater: UtilityLogic._squared_distance(beater.position, seeker.position),
        )
        self._focus_ids[team] = (kept + [beater.id for beater in candidates])[:self.seeker_focus_beaters]
        return self._focus_ids[team]

    def __call__(self,
                 ctx: StepContext,
                 team: int,
                 controlled_ids: List[str],
                 assigned_beater_ids: List[str]):
        """Guard the own seeker and beat seeker threats with the focus beaters in `controlled_ids`."""
        state = self.logic.state
        seeker = self._seeker(team)
        if seeker is None:
            return
        opponent_seeker = self._seeker(1 - team)
        flag_runner = state.flag_runner
        loaded_opponent_beaters = [
            player for player in state.players.values()
            if player.team != team and player.role == PlayerRole.BEATER and player.has_ball and not player.is_knocked_out
        ]
        for beater_id in controlled_ids:
            beater = state.players[beater_id]
            if beater.is_knocked_out or beater_id in assigned_beater_ids:
                continue
            threat = min(loaded_opponent_beaters, key=lambda other: UtilityLogic._squared_distance(other.position, seeker.position), default=None)
            self._guard(beater, seeker, threat if threat is not None else opponent_seeker)
            if beater.has_ball:
                self._throw(beater, team, seeker, opponent_seeker, flag_runner, loaded_opponent_beaters)

    def _guard(self, beater: Player, seeker: Player, threat: Optional[Player]) -> None:
        """Steer to `guard_distance` from the own seeker towards the threat."""
        if threat is None:
            target = seeker.position
        else:
            dx, dy = threat.position.x - seeker.position.x, threat.position.y - seeker.position.y
            distance = math.hypot(dx, dy)
            fraction = min(1.0, self.guard_distance / distance) if distance > 0 else 0.0
            target = Vector2(seeker.position.x + dx * fraction, seeker.position.y + dy * fraction)
        beater.direction = Vector2(target.x - beater.position.x, target.y - beater.position.y)

    def _throw(self, beater: Player, team: int, seeker: Player, opponent_seeker: Optional[Player], flag_runner, loaded_opponent_beaters: List[Player]) -> None:
        """Beat the first seeker threat in range, else an opponent volleyball holder in range."""
        decider = self.beater_throw_decider
        process_action_logic = self.logic.process_action_logic
        for other in sorted(loaded_opponent_beaters, key=lambda other: UtilityLogic._squared_distance(other.position, seeker.position)):
            if (UtilityLogic._squared_distance(other.position, seeker.position) <= self.squared_loaded_beater_threat_distance
                    and UtilityLogic._squared_distance(other.position, beater.position) <= self.squared_throw_distance
                    and other.id not in decider.pending_throws):
                if decider.throw_at(process_action_logic, beater, other):
                    return
        if (opponent_seeker is not None and flag_runner is not None and not opponent_seeker.dodgeball_immunity
                and opponent_seeker.id not in decider.pending_throws
                and UtilityLogic._squared_distance(opponent_seeker.position, flag_runner.position) <= self.squared_opponent_seeker_threat_distance
                and UtilityLogic._squared_distance(opponent_seeker.position, beater.position) <= self.squared_throw_distance):
            if decider.throw_at(process_action_logic, beater, opponent_seeker):
                self.logger.info("Seeker focus beater %s beats opponent seeker %s", beater.id, opponent_seeker.id)
                return
        volleyball = self.logic.state.volleyball
        if volleyball is not None and volleyball.holder_id is not None:
            holder = self.logic.state.players[volleyball.holder_id]
            if holder.team != team and decider.should_throw_at_volleyball_holder(beater, holder):
                decider.throw_at(process_action_logic, beater, holder)
