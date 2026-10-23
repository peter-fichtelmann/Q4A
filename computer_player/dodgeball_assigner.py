import logging
from typing import List, Optional, Set

from core.entities import BallType, PlayerRole, Vector2
from core.game_logic.game_logic import GameLogic
from core.game_logic.utility_logic import UtilityLogic
from computer_player.computer_player_utility.interception_calculator import InterceptionCalculator
from computer_player.computer_player_utility.computer_player_utility import BeaterThrowDecider, ThrowDirector


class DodgeballAssigner:
    """
    Assign beaters of both teams to free dodgeballs and steer the assigned ones.

    Runs before the beater base strategies, which leave the assigned beaters alone.
    """
    def __init__(self,
                 logic: GameLogic,
                 interception_calculator: InterceptionCalculator,
                 beater_throw_decider: BeaterThrowDecider,
                 logger: Optional[logging.Logger] = None):
        """Bind game logic, interception model and throw policy."""
        self.logic = logic
        self.interception_calculator = interception_calculator
        self.beater_throw_decider = beater_throw_decider
        self.logger = logger or logging.getLogger("computer_player")
        self.beaters = [player for player in self.logic.state.players.values() if player.role == PlayerRole.BEATER]
        self.defence_hoops = {0: [], 1: []}
        for hoop in self.logic.state.hoops.values():
            self.defence_hoops[0 if hoop.team == 0 else 1].append(hoop)

    def __call__(self, attacking_team: Optional[int], steerable_id_set: Set[str]) -> List[str]:
        """
        Determine if any beater should attempt to get a dodgeball. Return list of beater ids assigned to get a dodgeball, and set their direction towards the assigned dodgeball.
        Only beaters in `steerable_id_set` are steered, but all beaters are considered for the assignment.

        We deal with different scenarios in the following order:
        1. If there is a third dodgeball team, assign beater players to get the dodgeball for that team. The other team is very likely in possesion of two dodgeballs.
        2. If there is no third dodgeball team, assign beater players to get any dead dodgeballs:
            a. Assignment based on interception:
               Only assign one beater per dodgeball in this step to avoid issues with one beater being assigned to multiple dodgeballs due to the same interception time.
               Dodgeballs are processed by lowest interception time; each takes the fastest not yet assigned beater.
            b. Assignment based on proximity:
                For any remaining unassigned dodgeballs, assign the closest beater to get the dodgeball based on proximity.
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
            dodgeballs = self.logic.state.dodgeballs
            for dodgeball in dodgeballs:
                if dodgeball.ball_type == BallType.DODGEBALL:
                    if dodgeball.possession_team is None:
                        # If there is a dead dodgeball which is not the third dodgeball, assign beater players to get the dodgeball
                        # does not matter which interception ratio calculator as beaters are not blocked by hoops
                        min_interception_time, _, interception_info_dict = self.interception_calculator.line_interception(
                            moving_entity=dodgeball,
                            intercepting_player_ids=[beater.id for beater in self.beaters],
                        )
                        sorted_info_dict = sorted(interception_info_dict.items(), key=lambda item: item[1]) # sort by interception time
                        # sorted info dict is a list of Tuples (player_id, interception time)
                        sorted_interception_per_dodgeball_dict[dodgeball.id] = sorted_info_dict
                        min_interception_time_dodgeball_dict[dodgeball.id] = min_interception_time
            assigned_dodgeball_ids = []
            sorted_dodgeball_ids = sorted(min_interception_time_dodgeball_dict.keys(), key=lambda dodgeball_id: min_interception_time_dodgeball_dict[dodgeball_id])
            for dodgeball_id in sorted_dodgeball_ids:
                if len(sorted_interception_per_dodgeball_dict[dodgeball_id]) > 0:
                    for beater_id, interception_time in sorted_interception_per_dodgeball_dict[dodgeball_id]:
                        if beater_id not in assigned_beater_ids:
                            beater = self.logic.state.players[beater_id]
                            dodgeball = self.logic.state.balls[dodgeball_id]
                            assigned_beater_ids.append(beater_id)
                            assigned_dodgeball_ids.append(dodgeball_id)
                            # move towards the dodgeball
                            if beater.id in steerable_id_set:
                                interception_position = self.interception_calculator.get_aim_position(beater, dodgeball, interception_time)
                                beater.direction = Vector2(
                                        interception_position.x - beater.position.x,
                                        interception_position.y - beater.position.y
                                    )
                            break
            # only dodgeballs whereas possesion is None (sorted dodgeball ids) and not assigned before
            unassigned_dodgeball_ids = [dodgeball_id for dodgeball_id in sorted_dodgeball_ids if dodgeball_id not in assigned_dodgeball_ids]
            if len(unassigned_dodgeball_ids) > 0:
                assigned_beater_ids = self._distance_based_beater_assignment(unassigned_dodgeball_ids, assigned_beater_ids, steerable_id_set)

            # check if assigned beater has ball to throw to teammate or back to hoops
            for beater_id in assigned_beater_ids:
                beater = self.logic.state.players[beater_id]
                if beater.has_ball and beater.id in steerable_id_set:
                    # check if in defence and volleyball holding chaser close, if so throw at volleyball holder and get the assigned ball
                    if beater.team != attacking_team:
                        volleyball = self.logic.state.volleyball
                        if volleyball.holder_id is not None:
                            volleyball_holder = self.logic.state.players[volleyball.holder_id]
                            if self.beater_throw_decider.should_throw_at_volleyball_holder(beater, volleyball_holder):
                                throw_direction = ThrowDirector.get_throw_direction_moving_receiver(beater, volleyball_holder)
                                self.logic.process_action_logic.process_throw_action(beater.id, throw_direction)
                                continue
                    # check for pass to beater buddy, else pass back to hoops
                    beater_buddy = [player for player in self.beaters if player.id != beater_id and player.team == beater.team][0]
                    self.logger.debug("Beater %s team %s. Beater buddy knocked out %s, beater buddy in assigned beater ids %s, beater buddy has ball %s", beater.id, beater.team, beater_buddy.is_knocked_out, beater_buddy.id in assigned_beater_ids, beater_buddy.has_ball)
                    if not (beater_buddy.is_knocked_out) and not (beater_buddy.id in assigned_beater_ids) and not (beater_buddy.has_ball):
                        # pass to teammate if they not knocked out, not assigned a dodgeball or already having a dodgeball
                        throw_direction = ThrowDirector.get_throw_direction_moving_receiver(beater, beater_buddy)
                        self.logic.process_action_logic.process_throw_action(beater.id, throw_direction)
                        # move beater buddy to throwing player (at the moment only for one dt step)
                        # never steer the buddy when a human controls them
                        if beater_buddy.id in steerable_id_set:
                            beater_buddy.direction = Vector2(
                                - throw_direction.x,
                                - throw_direction.y
                            )
                        assigned_beater_ids.append(beater_buddy.id)
                    else:
                        # pass back to central hoop
                        central_hoop = self.defence_hoops[beater.team][1]
                        throw_direction = Vector2(
                            central_hoop.position.x - beater.position.x,
                            central_hoop.position.y - beater.position.y
                        )
                        self.logic.process_action_logic.process_throw_action(beater.id, throw_direction)
        return assigned_beater_ids

    def _distance_based_beater_assignment(self, unassigned_dodgeball_ids: List[str], assigned_beater_ids: List[str], steerable_id_set: Set[str]):
        """Assign remaining free dodgeballs to the nearest available beaters."""
        # calculate distances to unassigned beaters for unassigned dodgeballs and assign closest beater to each unassigned dodgeball
        squared_distances_dict = {}
        for dodgeball_id in unassigned_dodgeball_ids:
            dodgeball = self.logic.state.balls[dodgeball_id]
            for beater in self.beaters:
                if not beater.is_knocked_out and beater.id not in assigned_beater_ids:
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
                if beater_id in steerable_id_set:
                    beater = self.logic.state.players[beater_id]
                    beater.direction = squared_distances_dict[(beater_id, dodgeball_id)][1]
        return assigned_beater_ids
