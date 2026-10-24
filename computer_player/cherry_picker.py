import logging
from typing import Dict, Optional, Tuple

from core.entities import Player, Vector2
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

    Following: a target that meets these criteria within `follow_distance` but is not yet close
    enough is chased for at most `follow_duration` game seconds, throwing once it is within
    `cherry_pick_distance`. A beater that gives up on a target does not follow it again for
    `follow_duration`.

    With `include_seekers`, the opponent seeker is a target as well while the seekers are on pitch.

    Protecting the carrier (`protect_carrier_distance`): on attack, an opponent chaser/keeper within
    that distance of the own volleyball holder is a target with priority, followed and beaten the
    same way. Freeing the carrier matters more than the rebound, so only the bludger control
    criterion applies to it.
    """
    def __init__(self,
                 logic: GameLogic,
                 beater_throw_decider: BeaterThrowDecider,
                 cherry_pick_distance: Optional[float] = None, # m; None: no cherry picks
                 follow_distance: Optional[float] = None, # m; None: no following
                 follow_duration: float = 4.5, # game seconds
                 protection_radius: float = 4.0,
                 recovery_margin: float = 1.0,
                 own_hoop_safe_distance: float = 15.0,
                 include_seekers: bool = False,
                 protect_carrier_distance: Optional[float] = None, # m; None: no carrier protection
                 logger: Optional[logging.Logger] = None):
        """Store the cherry pick criteria."""
        self.logic = logic
        self.beater_throw_decider = beater_throw_decider
        self.squared_cherry_pick_distance = cherry_pick_distance ** 2 if cherry_pick_distance is not None else None
        self.squared_follow_distance = follow_distance ** 2 if follow_distance is not None else None
        self.follow_duration = follow_duration
        self.squared_protection_radius = protection_radius ** 2
        self.recovery_margin = recovery_margin
        self.squared_own_hoop_safe_distance = own_hoop_safe_distance ** 2
        self.include_seekers = include_seekers
        self.squared_protect_carrier_distance = protect_carrier_distance ** 2 if protect_carrier_distance is not None else None
        self.logger = logger or logging.getLogger("computer_player")
        self._follows: Dict[str, Tuple[str, float]] = {} # beater id -> (target id, start game time)
        self._follow_blocked_until: Dict[Tuple[str, str], float] = {} # (beater id, target id) -> game time

    def try_pick(self, beater: Player, roster: TeamRoster, on_attack: bool) -> bool:
        """
        Throw at the best cherry pick (or carrier protection) target of the loaded `beater`, or follow one
        that is not close enough yet. Returns whether the beater threw or is following (its direction is then set).
        """
        if self.squared_cherry_pick_distance is None:
            return False
        if not beater.has_ball or beater.is_knocked_out or not self._bludger_control_kept(roster):
            self._stop_following(beater)
            return False
        cherry_allowed = self._cherry_pick_allowed(beater, roster, on_attack)
        carrier_threats = self._carrier_threats(roster) if on_attack else {}
        if not cherry_allowed and not carrier_threats:
            self._stop_following(beater)
            return False
        state = self.logic.state
        opponent_beaters = [state.players[player_id] for player_id in roster.opponent_beater_ids if not state.players[player_id].is_knocked_out]
        loaded_opponent_beaters = [player for player in opponent_beaters if player.has_ball]
        squared_reach = max(self.squared_cherry_pick_distance, self.squared_follow_distance or 0.0)

        def valid(candidate: Player) -> Optional[float]:
            if candidate.id in carrier_threats:
                return self._squared_protect_distance(beater, candidate, squared_reach)
            if cherry_allowed:
                return self._squared_valid_distance(beater, candidate, opponent_beaters, loaded_opponent_beaters, squared_reach)
            return None

        target = None
        follow = self._follows.get(beater.id)
        if follow is not None:
            target_id, start_time = follow
            candidate = state.players[target_id]
            if state.game_time - start_time <= self.follow_duration and valid(candidate) is not None:
                target = candidate
            else:
                self._stop_following(beater)
        if target is None:
            target_ids = roster.opponent_chaser_keeper_ids
            if self.include_seekers and state.seeker_on_pitch:
                target_ids = target_ids + roster.opponent_seeker_ids
            best_key = None
            for target_id in target_ids:
                candidate = state.players[target_id]
                if state.game_time < self._follow_blocked_until.get((beater.id, target_id), float('-inf')):
                    continue
                squared_distance = valid(candidate)
                if squared_distance is None:
                    continue
                # carrier threats first, the one closest to the carrier; then the closest cherry pick
                key = (0, carrier_threats[target_id]) if target_id in carrier_threats else (1, squared_distance)
                if best_key is None or key < best_key:
                    target, best_key = candidate, key
            if target is None:
                return False

        if UtilityLogic._squared_distance(beater.position, target.position) <= self.squared_cherry_pick_distance:
            if self.beater_throw_decider.throw_at(self.logic.process_action_logic, beater, target):
                if target.id in carrier_threats:
                    self.logger.info("Beater %s protects carrier %s by beating %s", beater.id, state.volleyball.holder_id, target.id)
                else:
                    self.logger.info("Cherry pick by beater %s on %s %s", beater.id, target.role.value, target.id)
                self._follows.pop(beater.id, None)
                return True
            return False
        # follow: steer at where the target will be when the beater gets there
        if beater.id not in self._follows:
            self._follows[beater.id] = (target.id, state.game_time)
            self.logger.debug("Beater %s follows %s %s for a cherry pick", beater.id, target.role.value, target.id)
        distance = UtilityLogic._squared_distance(beater.position, target.position) ** 0.5
        lead_time = distance / beater.max_speed if beater.max_speed > 0 else 0.0
        beater.direction = Vector2(
            target.position.x + target.velocity.x * lead_time - beater.position.x,
            target.position.y + target.velocity.y * lead_time - beater.position.y,
        )
        return True

    def _bludger_control_kept(self, roster: TeamRoster) -> bool:
        """Throwing does not leave the team without a dodgeball while the opponents hold two."""
        state = self.logic.state
        loaded_opponents = sum(
            1 for player_id in roster.opponent_beater_ids
            if not state.players[player_id].is_knocked_out and state.players[player_id].has_ball
        )
        own_loaded = sum(1 for player_id in roster.beater_ids if state.players[player_id].has_ball)
        return not (own_loaded <= 1 and loaded_opponents >= 2)

    def _cherry_pick_allowed(self, beater: Player, roster: TeamRoster, on_attack: bool) -> bool:
        """Low scoring risk and no loaded opponent beater close to the beater."""
        state = self.logic.state
        volleyball = state.volleyball
        if not on_attack and volleyball is not None:
            closest_own_hoop = min(UtilityLogic._squared_distance(volleyball.position, hoop.position) for hoop in roster.own_hoops)
            if closest_own_hoop < self.squared_own_hoop_safe_distance:
                return False
        loaded_opponent_beaters = [
            state.players[player_id] for player_id in roster.opponent_beater_ids
            if not state.players[player_id].is_knocked_out and state.players[player_id].has_ball
        ]
        return not any(UtilityLogic._squared_distance(beater.position, other.position) < self.squared_protection_radius for other in loaded_opponent_beaters)

    def _carrier_threats(self, roster: TeamRoster) -> Dict[str, float]:
        """Opponent chasers/keepers within the protection distance of the own volleyball holder -> squared distance to it."""
        if self.squared_protect_carrier_distance is None:
            return {}
        state = self.logic.state
        holder_id = state.volleyball.holder_id if state.volleyball is not None else None
        holder = state.players.get(holder_id) if holder_id is not None else None
        if holder is None or holder.team != roster.team:
            return {}
        threats = {}
        for opponent_id in roster.opponent_chaser_keeper_ids:
            opponent = state.players[opponent_id]
            if opponent.is_knocked_out:
                continue
            squared_distance = UtilityLogic._squared_distance(opponent.position, holder.position)
            if squared_distance <= self.squared_protect_carrier_distance:
                threats[opponent_id] = squared_distance
        return threats

    def _squared_protect_distance(self, beater: Player, target: Player, squared_reach: float) -> Optional[float]:
        """Squared distance to the carrier threat `target` if it can be beaten (not immune, not thrown at, in reach), else None."""
        if target.is_knocked_out or target.dodgeball_immunity or self.beater_throw_decider.pending_throws.get(target.id) is not None:
            return None
        squared_distance = UtilityLogic._squared_distance(beater.position, target.position)
        return squared_distance if squared_distance <= squared_reach else None

    def _squared_valid_distance(self, beater: Player, target: Player, opponent_beaters, loaded_opponent_beaters, squared_reach: float) -> Optional[float]:
        """Squared distance to `target` if it is a valid cherry pick target within `squared_reach`, else None."""
        volleyball = self.logic.state.volleyball
        if target.is_knocked_out or target.dodgeball_immunity or (volleyball is not None and target.id == volleyball.holder_id):
            return None
        squared_distance = UtilityLogic._squared_distance(beater.position, target.position)
        if squared_distance > squared_reach:
            return None
        if self.beater_throw_decider.pending_throws.get(target.id) is not None:
            return None
        if any(UtilityLogic._squared_distance(target.position, other.position) < self.squared_protection_radius for other in loaded_opponent_beaters):
            return None
        # recover the rebound: closer to the target than every opponent beater by the margin
        beater_distance = squared_distance ** 0.5
        if any(UtilityLogic._squared_distance(target.position, other.position) ** 0.5 < beater_distance + self.recovery_margin for other in opponent_beaters):
            return None
        return squared_distance

    def _stop_following(self, beater: Player) -> None:
        """Give up the current follow of `beater`; it does not follow that target again for `follow_duration`."""
        follow = self._follows.pop(beater.id, None)
        if follow is not None:
            self._follow_blocked_until[(beater.id, follow[0])] = self.logic.state.game_time + self.follow_duration
