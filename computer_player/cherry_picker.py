import logging
from typing import Optional

from core.entities import Player
from core.game_logic.game_logic import GameLogic
from core.game_logic.utility_logic import UtilityLogic
from computer_player.base_strategy import TeamRoster
from computer_player.computer_player_utility.computer_player_utility import BeaterThrowDecider


class CherryPicker:
    """
    Opportunity layer of the beater strategies: cherry picks.

    A cherry pick is a close-distance beat of an unprotected opponent chaser/keeper (not the volleyball
    holder, which the base strategies handle), after which the beater wants to recover the dodgeball
    right away. A loaded beater takes it when:
        - the target is within `cherry_pick_distance`, not immune and not already thrown at,
        - no loaded opponent beater is within `protection_radius` of the target or of the beater,
        - the beater is closer to the target (where the dodgeball rebounds) than every on-stick
          opponent beater by `recovery_margin`,
        - the scoring risk is low: the beater's team is on attack, or the volleyball is at least
          `own_hoop_safe_distance` from the team's closest own hoop,
        - it does not leave the team without a dodgeball while the opponents hold two.
    """
    def __init__(self,
                 logic: GameLogic,
                 beater_throw_decider: BeaterThrowDecider,
                 cherry_pick_distance: Optional[float] = None, # m; None: no cherry picks
                 protection_radius: float = 4.0,
                 recovery_margin: float = 1.0,
                 own_hoop_safe_distance: float = 15.0,
                 logger: Optional[logging.Logger] = None):
        """Store the cherry pick criteria."""
        self.logic = logic
        self.beater_throw_decider = beater_throw_decider
        self.squared_cherry_pick_distance = cherry_pick_distance ** 2 if cherry_pick_distance is not None else None
        self.squared_protection_radius = protection_radius ** 2
        self.recovery_margin = recovery_margin
        self.squared_own_hoop_safe_distance = own_hoop_safe_distance ** 2
        self.logger = logger or logging.getLogger("computer_player")

    def try_pick(self, beater: Player, roster: TeamRoster, on_attack: bool) -> bool:
        """Throw at the best cherry pick target of the loaded `beater` if there is one. Returns whether it threw."""
        if self.squared_cherry_pick_distance is None or not beater.has_ball or beater.is_knocked_out:
            return False
        state = self.logic.state
        volleyball = state.volleyball
        if not on_attack and volleyball is not None:
            closest_own_hoop = min(UtilityLogic._squared_distance(volleyball.position, hoop.position) for hoop in roster.own_hoops)
            if closest_own_hoop < self.squared_own_hoop_safe_distance:
                return False
        opponent_beaters = [state.players[player_id] for player_id in roster.opponent_beater_ids if not state.players[player_id].is_knocked_out]
        loaded_opponent_beaters = [player for player in opponent_beaters if player.has_ball]
        own_loaded = sum(1 for player_id in roster.beater_ids if state.players[player_id].has_ball)
        if own_loaded <= 1 and len(loaded_opponent_beaters) >= 2:
            return False # would give up bludger control
        if any(UtilityLogic._squared_distance(beater.position, other.position) < self.squared_protection_radius for other in loaded_opponent_beaters):
            return False
        best_target, best_squared_distance = None, None
        for target_id in roster.opponent_chaser_keeper_ids:
            target = state.players[target_id]
            if target.is_knocked_out or target.dodgeball_immunity or target.id == volleyball.holder_id:
                continue
            squared_distance = UtilityLogic._squared_distance(beater.position, target.position)
            if squared_distance > self.squared_cherry_pick_distance:
                continue
            if best_squared_distance is not None and squared_distance >= best_squared_distance:
                continue
            if self.beater_throw_decider.pending_throws.get(target.id) is not None:
                continue
            if any(UtilityLogic._squared_distance(target.position, other.position) < self.squared_protection_radius for other in loaded_opponent_beaters):
                continue
            # recover the rebound: closer to the target than every opponent beater by the margin
            beater_distance = squared_distance ** 0.5
            if any(UtilityLogic._squared_distance(target.position, other.position) ** 0.5 < beater_distance + self.recovery_margin for other in opponent_beaters):
                continue
            best_target, best_squared_distance = target, squared_distance
        if best_target is None:
            return False
        if self.beater_throw_decider.throw_at(self.logic.process_action_logic, beater, best_target):
            self.logger.info("Cherry pick by beater %s on %s %s", beater.id, best_target.role.value, best_target.id)
            return True
        return False
