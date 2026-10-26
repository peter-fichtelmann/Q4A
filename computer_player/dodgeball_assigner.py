import logging
import math
from typing import List, Optional, Set

from config import Config
from core.entities import BallType, PlayerRole, Vector2
from core.game_logic.game_logic import GameLogic
from core.game_logic.utility_logic import UtilityLogic
from computer_player.computer_player_utility.interception_calculator import InterceptionCalculator
from computer_player.computer_player_utility.kinematics import decay_table


class DodgeballAssigner:
    """
    Assign beaters of both teams to free dodgeballs and steer the assigned ones.

    Runs before the beater base strategies, which leave the assigned beaters alone.

    Missed throws (`missed_throw_lane_margin`): a thrown dodgeball that no opponent is in the way of
    anymore cannot beat. Beaters of the throwing team may pick it up while it is still live, so it is
    free for them right away instead of only once it is slow enough to be dead. An opponent is in the
    way if it is closer to the dodgeball's remaining path (until it is dead) than its radius + the
    dodgeball radius + this margin, now or moved on with its velocity until the dodgeball passes it.
    """
    def __init__(self,
                 logic: GameLogic,
                 interception_calculator: InterceptionCalculator,
                 missed_throw_lane_margin: Optional[float] = None, # m; None: missed throws are only fetched once dead
                 logger: Optional[logging.Logger] = None):
        """Bind game logic and the interception model."""
        self.logic = logic
        self.interception_calculator = interception_calculator
        self.missed_throw_lane_margin = missed_throw_lane_margin
        self.logger = logger or logging.getLogger("computer_player")
        self.beaters = [player for player in self.logic.state.players.values() if player.role == PlayerRole.BEATER]

    def __call__(self, steerable_id_set: Set[str]) -> List[str]:
        """
        Determine if any beater should attempt to get a dodgeball. Return list of beater ids assigned to get a dodgeball, and set their direction towards the assigned dodgeball.
        Only beaters in `steerable_id_set` are steered. For the third dodgeball all beaters of its team are considered;
        a free dodgeball goes to the fastest CPU steered beater without a dodgeball, while all beaters compete in the timing.

        We deal with different scenarios in the following order:
        1. If there is a third dodgeball team, assign beater players to get the dodgeball for that team. The other team is very likely in possesion of two dodgeballs.
        2. If there is no third dodgeball team, assign beater players to get any dead dodgeballs:
            a. Assignment based on interception:
               Only assign one beater per dodgeball in this step to avoid issues with one beater being assigned to multiple dodgeballs due to the same interception time.
               Dodgeballs are processed by lowest interception time; each takes the fastest not yet assigned eligible beater
               (knocked out beaters start from their centre hoop).
            b. Assignment based on proximity:
                For any remaining unassigned dodgeballs, assign the closest eligible beater to get the dodgeball based on proximity.
        A beater never throws its own dodgeball away to fetch another one.
        """
        assigned_beater_ids = []
        third_dodgeball_team = self.logic.state.third_dodgeball_team
        if third_dodgeball_team is not None:
            # TODO implement the rare case when control beater missed throw and wants to run to get thrown dodgeball back/oppenent tries to get this one
            # If there is a third dodgeball team, assign beater players to get the dodgeball
            self.logger.debug(
                "Third dodgeball on team %s, determining beater assignment to get the dodgeball",
                third_dodgeball_team,
            )
            third_dodgeball = self.logic.state.balls[self.logic.state.third_dodgeball]
            squared_distance_and_direction_to_dodgeball_dict = {}
            for beater in self.beaters:
                if beater.team == third_dodgeball_team and not beater.is_knocked_out:
                    direction_to_dodgeball = Vector2(
                            third_dodgeball.position.x - beater.position.x,
                            third_dodgeball.position.y - beater.position.y
                        )
                    squared_distance_to_dodgeball = UtilityLogic._squared_sum(direction_to_dodgeball.x, direction_to_dodgeball.y)
                    squared_distance_and_direction_to_dodgeball_dict[beater.id] = (squared_distance_to_dodgeball, direction_to_dodgeball)
            if len(squared_distance_and_direction_to_dodgeball_dict) > 0:
                # assign beater with lowest squared distance to dodgeball to get the dodgeball
                beater_id = min(squared_distance_and_direction_to_dodgeball_dict.keys(), key=lambda k: squared_distance_and_direction_to_dodgeball_dict[k][0])
                beater = self.logic.state.players[beater_id]
                self.logger.debug("Beater %s assigned to get third dodgeball for team %s", beater.id, third_dodgeball_team)
                assigned_beater_ids.append(beater_id)
                    # move towards the dodgeball
                if beater.id in steerable_id_set:
                    beater.direction = squared_distance_and_direction_to_dodgeball_dict[beater.id][1]
                    # claim for immunity and free way (no-op if already claiming or not allowed)
                    self.logic.process_action_logic.process_claiming(beater.id)
        else: # no third dodgeball, so no team already has two dodgeballs in possesion
            sorted_interception_per_dodgeball_dict = {}
            min_interception_time_dodgeball_dict = {}
            live_dodgeball_ids = set() # missed throws, which only the throwing team may fetch
            dodgeballs = self.logic.state.dodgeballs
            for dodgeball in dodgeballs:
                if dodgeball.ball_type == BallType.DODGEBALL:
                    if dodgeball.possession_team is None:
                        competing_beaters = self.beaters
                    elif dodgeball.holder_id is None and self._missed_throw(dodgeball):
                        # only the throwing team can touch a live dodgeball without being beaten
                        competing_beaters = [beater for beater in self.beaters if beater.team == dodgeball.possession_team]
                        live_dodgeball_ids.add(dodgeball.id)
                    else:
                        competing_beaters = None
                    if competing_beaters is not None:
                        # If there is a dead dodgeball which is not the third dodgeball, assign beater players to get the dodgeball
                        # does not matter which interception ratio calculator as beaters are not blocked by hoops
                        # all beaters compete, knocked out ones starting from their centre hoop
                        min_interception_time, _, interception_info_dict = self.interception_calculator.line_interception(
                            moving_entity=dodgeball,
                            intercepting_player_ids=[beater.id for beater in competing_beaters],
                        )
                        sorted_info_dict = sorted(interception_info_dict.items(), key=lambda item: item[1]) # sort by interception time
                        # sorted info dict is a list of Tuples (player_id, interception time)
                        sorted_interception_per_dodgeball_dict[dodgeball.id] = sorted_info_dict
                        min_interception_time_dodgeball_dict[dodgeball.id] = min_interception_time
            assigned_dodgeball_ids = []
            sorted_dodgeball_ids = sorted(min_interception_time_dodgeball_dict.keys(), key=lambda dodgeball_id: min_interception_time_dodgeball_dict[dodgeball_id])
            for dodgeball_id in sorted_dodgeball_ids:
                for beater_id, interception_time in sorted_interception_per_dodgeball_dict[dodgeball_id]:
                    # the fastest eligible beater gets the dodgeball; a faster human or loaded beater does not block it
                    if beater_id not in assigned_beater_ids and self._is_eligible(beater_id, steerable_id_set):
                        beater = self.logic.state.players[beater_id]
                        dodgeball = self.logic.state.balls[dodgeball_id]
                        assigned_beater_ids.append(beater_id)
                        assigned_dodgeball_ids.append(dodgeball_id)
                        # move towards the dodgeball
                        interception_position = self.interception_calculator.get_aim_position(beater, dodgeball, interception_time)
                        beater.direction = Vector2(
                                interception_position.x - beater.position.x,
                                interception_position.y - beater.position.y
                            )
                        break
            # only dodgeballs whereas possesion is None (sorted dodgeball ids) and not assigned before
            unassigned_dodgeball_ids = [dodgeball_id for dodgeball_id in sorted_dodgeball_ids
                                        if dodgeball_id not in assigned_dodgeball_ids and dodgeball_id not in live_dodgeball_ids]
            if len(unassigned_dodgeball_ids) > 0:
                assigned_beater_ids = self._distance_based_beater_assignment(unassigned_dodgeball_ids, assigned_beater_ids, steerable_id_set)
        return assigned_beater_ids

    def _missed_throw(self, dodgeball) -> bool:
        """Whether no opponent of the throwing team is in the way of the live thrown `dodgeball` until it is dead."""
        if self.missed_throw_lane_margin is None:
            return False
        state = self.logic.state
        speed = math.hypot(dodgeball.velocity.x, dodgeball.velocity.y)
        if speed <= Config.DODGEBALL_DEAD_VELOCITY_THRESHOLD:
            return False # dead within the next tick anyway
        table = decay_table(dodgeball.deacceleration_rate)
        # distance travelled until the speed drops to the dead threshold: c * (v - v_dead)
        remaining = table.c * (speed - Config.DODGEBALL_DEAD_VELOCITY_THRESHOLD) if table.c is not None else float('inf')
        ux, uy = dodgeball.velocity.x / speed, dodgeball.velocity.y / speed
        for player in state.players.values():
            if player.team == dodgeball.possession_team or player.is_knocked_out:
                continue
            if player.role == PlayerRole.SEEKER and not state.seeker_on_pitch:
                continue
            reach = player.radius + dodgeball.radius + self.missed_throw_lane_margin
            dx = player.position.x - dodgeball.position.x
            dy = player.position.y - dodgeball.position.y
            along = dx * ux + dy * uy
            if self._in_lane(dx, dy, ux, uy, reach, remaining):
                return False
            if along > 0:
                # where the opponent is when the dodgeball passes it (constant speeds)
                time = along / speed
                if self._in_lane(dx + player.velocity.x * time, dy + player.velocity.y * time, ux, uy, reach, remaining):
                    return False
        return True

    @staticmethod
    def _in_lane(dx: float, dy: float, ux: float, uy: float, reach: float, length: float) -> bool:
        """Whether the offset (dx, dy) from the dodgeball is within `reach` of its path of `length` along (ux, uy)."""
        along = dx * ux + dy * uy
        return -reach <= along <= length + reach and abs(dx * uy - dy * ux) < reach

    def _is_eligible(self, beater_id: str, steerable_id_set: Set[str]) -> bool:
        """A free dodgeball goes to a CPU steered beater without a dodgeball (knocked out ones included)."""
        return beater_id in steerable_id_set and not self.logic.state.players[beater_id].has_ball

    def _distance_based_beater_assignment(self, unassigned_dodgeball_ids: List[str], assigned_beater_ids: List[str], steerable_id_set: Set[str]):
        """Assign remaining free dodgeballs to the nearest available beaters."""
        # calculate distances to unassigned beaters for unassigned dodgeballs and assign closest beater to each unassigned dodgeball
        squared_distances_dict = {}
        for dodgeball_id in unassigned_dodgeball_ids:
            dodgeball = self.logic.state.balls[dodgeball_id]
            for beater in self.beaters:
                if not beater.is_knocked_out and beater.id not in assigned_beater_ids and self._is_eligible(beater.id, steerable_id_set):
                    direction_to_dodgeball = Vector2(
                            dodgeball.position.x - beater.position.x,
                            dodgeball.position.y - beater.position.y
                        )
                    squared_distance_to_dodgeball = UtilityLogic._squared_sum(direction_to_dodgeball.x, direction_to_dodgeball.y)
                    squared_distances_dict[(beater.id, dodgeball_id)] = (squared_distance_to_dodgeball, direction_to_dodgeball)
        sorted_squared_distances = sorted(squared_distances_dict.keys(), key=lambda k: squared_distances_dict[k][0])
        for beater_id, dodgeball_id in sorted_squared_distances:
            if beater_id not in assigned_beater_ids and dodgeball_id in unassigned_dodgeball_ids:
                assigned_beater_ids.append(beater_id)
                unassigned_dodgeball_ids.remove(dodgeball_id)
                # move towards the dodgeball
                beater = self.logic.state.players[beater_id]
                beater.direction = squared_distances_dict[(beater_id, dodgeball_id)][1]
        return assigned_beater_ids
