import itertools
import logging
import math
from typing import Dict, Optional, List

from computer_player.computer_player_utility.move_around_hoop_blockage import MoveAroundHoopBlockage
from computer_player.computer_player_utility.interception_calculator import InterceptionCalculator
from computer_player.computer_player_utility.computer_player_utility import BeaterThrowDecider, MoveUtility, ThrowDirector
from core.entities import Player, PlayerRole, Vector2, VolleyBall
from core.game_logic.game_logic import GameLogic
from core.game_logic.utility_logic import UtilityLogic


class DiamondAttack:

    def __init__(self,
                logic: GameLogic,
                move_around_hoop_blockage: MoveAroundHoopBlockage, # of own team
                interception_calculator_opponent: InterceptionCalculator,
                attack_cpu_player_ids: List[str],
                attack_team: int,
                beater_throw_decider: BeaterThrowDecider,
                score_interception_max_dt_steps: int = 10,
                score_interception_max_distance_per_step: Optional[float] = None,
                score_interception_max_dt_per_step: Optional[int] = None,
                score_squared_max_distance: float = 64, # only consider scoring on hoops within this squared distance from the volleyball for efficiency, since if it's too far the interception score calculation won't be accurate and it's unlikely to be a good scoring opportunity
                scoring_threshold: float = 0.8,
                chaser_evade_beater_weight: float = 4,
                chaser_evade_chaser_keeper_weight: float = 2,
                chaser_evade_teamate_chaser_keeper_weight: float = 1,
                unloaded_beater_evade_loaded_opponent_beater_weight: float = -3, # if opponent beater is loaded, we want to be closer to them to try to get the ball from them, so negative weight for evade vector, but if they are unloaded then we want to be farther away from them to avoid getting hit, so positive weight for evade vector
                loaded_beater_evade_loaded_opponent_beater_weight: float = -2,
                loaded_beater_evade_unloaded_opponent_beater_weight: float = 2,
                positioning_boundary_buffer_distance: float = 2, # distance from boundary at which to start evading boundary
                passing_evade_vector_position_penalty_weight: float = 100,
                passing_threshold: float = 0.8, # minimum interception score (chance of not being intercepted) to attempt a pass
                passing_squared_max_distance: float = 400,
                logger: Optional[logging.Logger] = None
                ):
        self.logic = logic
        self.move_around_hoop_blockage = move_around_hoop_blockage
        self.interception_calculator_opponent = interception_calculator_opponent
        self.attack_cpu_player_ids = attack_cpu_player_ids
        self.attack_team = attack_team
        self.beater_throw_decider = beater_throw_decider
        self.score_interception_max_dt_steps = score_interception_max_dt_steps
        self.score_interception_max_distance_per_step = score_interception_max_distance_per_step
        self.score_interception_max_dt_per_step = score_interception_max_dt_per_step
        self.score_squared_max_distance = score_squared_max_distance
        self.scoring_threshold = scoring_threshold
        self.chaser_evade_beater_weight = chaser_evade_beater_weight
        self.chaser_evade_chaser_keeper_weight = chaser_evade_chaser_keeper_weight
        self.chaser_evade_teamate_chaser_keeper_weight = chaser_evade_teamate_chaser_keeper_weight
        self.unloaded_beater_evade_loaded_opponent_beater_weight = unloaded_beater_evade_loaded_opponent_beater_weight
        self.loaded_beater_evade_loaded_opponent_beater_weight = loaded_beater_evade_loaded_opponent_beater_weight
        self.loaded_beater_evade_unloaded_opponent_beater_weight = loaded_beater_evade_unloaded_opponent_beater_weight
        self.positioning_boundary_buffer_distance = positioning_boundary_buffer_distance
        self.passing_evade_vector_position_penalty_weight = passing_evade_vector_position_penalty_weight
        self.passing_threshold = passing_threshold
        self.passing_squared_max_distance = passing_squared_max_distance
        self.logger = logger or logging.getLogger("computer_player")

        self.attack_hoops = [hoop for hoop in self.logic.state.hoops.values() if hoop.team != attack_team]
        self.attacking_chaser_keeper_ids = []
        self.defending_chaser_keeper_ids = []
        self.attacking_beater_ids = []
        self.defending_beater_ids = []
        for player in self.logic.state.players.values():
            if player.role in [PlayerRole.CHASER, PlayerRole.KEEPER]:
                if player.team == attack_team and player.role:
                    self.attacking_chaser_keeper_ids.append(player.id)
                else:
                    self.defending_chaser_keeper_ids.append(player.id)
            elif player.role == PlayerRole.BEATER:
                if player.team == attack_team:
                    self.attacking_beater_ids.append(player.id)
                else:
                    self.defending_beater_ids.append(player.id)


    def move_to_volleyball(self,
                           volleyball: VolleyBall,
                           next_volleyball_holder_id: str,
                           intercepting_position: Optional[Vector2] = None
                           ):
            next_holder = self.logic.state.players[next_volleyball_holder_id]
            if intercepting_position is not None:
                next_holder.direction = Vector2(
                    intercepting_position.x - next_holder.position.x,
                    intercepting_position.y - next_holder.position.y
                )
            else:
                next_holder.direction = Vector2(
                    volleyball.position.x - next_holder.position.x,
                    volleyball.position.y - next_holder.position.y
                )

    def get_intercepting_scores_for_hoops(self, dt: float, volleyball: VolleyBall, volleyball_holder: Player):
        intercepting_scores_dict = {}
        for hoop in self.attack_hoops:
            volleyball_hoop_vector = Vector2(
                hoop.position.x - volleyball.position.x,
                hoop.position.y - volleyball.position.y
            )
            squared_volleyball_hoop_distance = volleyball_hoop_vector.x**2 + volleyball_hoop_vector.y**2
            if squared_volleyball_hoop_distance > self.score_squared_max_distance:
                continue
            copy_volleyball = volleyball.copy()
            mag_volleyball_hoop_vector = math.sqrt(squared_volleyball_hoop_distance)
            copy_volleyball.velocity.x = volleyball_holder.throw_velocity * volleyball_hoop_vector.x / mag_volleyball_hoop_vector
            copy_volleyball.velocity.y = volleyball_holder.throw_velocity * volleyball_hoop_vector.y / mag_volleyball_hoop_vector

            # intercepting_score, scores_info = self.interception_calculator_opponent(
        #      dt=dt,
        #      moving_entity=copy_volleyball,
        #      intercepting_player_ids=self.defending_chaser_keeper_ids,
        #      max_dt_steps=self.score_interception_max_dt_steps,
        #      target_position=hoop.position,
        #      only_first_intercepting=False,
        #      max_distance_per_step=self.score_interception_max_distance_per_step,
        #      max_dt_per_step=self.score_interception_max_dt_per_step
        # )
            beam_cosine_angle, beam_cosine_angle_player_id, _ = self.interception_calculator_opponent.beam_cosine_angle(
                moving_entity=copy_volleyball,
                intercepting_player_ids=self.defending_chaser_keeper_ids,
                target_position=hoop.position,
                moving_entity_target_vector=volleyball_hoop_vector)
            intercepting_score = self.interception_calculator_opponent.interception_score_from_beam_cosine_angle(
                beam_cosine_angle=beam_cosine_angle,
                beam_angle_player_id=beam_cosine_angle_player_id,
                mag_moving_entity_velocity=volleyball_holder.throw_velocity,
                # squared_moving_entity_target_distance=mag_volleyball_hoop_vector**2,
            )
            intercepting_scores_dict[hoop.id] = intercepting_score
            # self.logger.debug("Interception info per hoop %s: %s, %s", hoop.id, intercepting_score, scores_info)
        # self.logger.debug("intercepting_scores_dict %s", intercepting_scores_dict)
        return intercepting_scores_dict

    def score_attempt(self, dt: float, volleyball: VolleyBall, volleyball_holder: Player) -> bool:
        intercepting_scores_dict = self.get_intercepting_scores_for_hoops(dt, volleyball, volleyball_holder)
        # if no intercepting_scores, then probably to far away to score
        if len(intercepting_scores_dict) == 0:
            return False
        # get hoop with highest interception score (lowest chance of being intercepted)
        best_hoop_id = min(intercepting_scores_dict, key=intercepting_scores_dict.get)
        best_score = intercepting_scores_dict[best_hoop_id]
        if best_score > self.scoring_threshold:
            self.logger.info("Scoring on hoop %s with interception score %s", best_hoop_id, best_score)
            best_hoop = self.logic.state.hoops[best_hoop_id]
            volleyball_holder.direction = Vector2(
                best_hoop.position.x - volleyball_holder.position.x,
                best_hoop.position.y - volleyball_holder.position.y
            )
            self.logic.process_action_logic.process_throw_action(volleyball_holder.id)
            return True
        return False
    
    def player_positioning(self, player: Player, total_evade_vector: Vector2, move_vector: Optional[Vector2] = None):
        if move_vector is None:
            move_vector = Vector2(
                1 - 2 * self.attack_team, # 1 for team 0 attacking, -1 for team 1 attacking
                0
            )
        # check distance to loaded opponent beater and evade if too close
        
            # self.logger.debug("Evade vector for player %s from opponent: %s", player.id, evade_vector)
        move_vector.x += total_evade_vector.x
        move_vector.y += total_evade_vector.y
        move_vector = MoveUtility.adjust_move_vector_to_avoid_boundary(
            player.position,
            move_vector,
            boundary_x_min = self.logic.state.boundaries_x[0],
            boundary_x_max = self.logic.state.boundaries_x[1],
            boundary_y_min = self.logic.state.boundaries_y[0],
            boundary_y_max = self.logic.state.boundaries_y[1],
            buffer = self.positioning_boundary_buffer_distance
        )
        # if player.position.y < self.logic.state.boundaries_y[0] + self.positioning_boundary_buffer_distance:
        #     move_vector.y = max(0, move_vector.y) # don't move down if already at boundary
        # elif player.position.y > self.logic.state.boundaries_y[1] - self.positioning_boundary_buffer_distance:
        #     move_vector.y = min(0, move_vector.y) # don't move up if already at boundary
        # if player.position.x < self.logic.state.boundaries_x[0] + self.positioning_boundary_buffer_distance:
        #     move_vector.x = max(0, move_vector.x) # don't move left if already at boundary
        # elif player.position.x > self.logic.state.boundaries_x[1] - self.positioning_boundary_buffer_distance:
        #     move_vector.x = min(0, move_vector.x) # don't move right if already at boundary
        player.direction = Vector2(move_vector.x, move_vector.y)

    def move_chaser_keeper_hoops(self, players: List[Player]) -> Dict[str, Vector2]:
        """Assign defending chasers/keepers to attack hoops based on total proximity, so that we can consider them when evading and in interception score calculation. Solving an Assignment Problem but since there are so few players and hoops we can just do it with a brute force approach"""
        # self.logger.debug("Moving chaser/keeper hoops, N players: %s", len(players))
        move_vectors_dict = {}
        player_positions = [player.position for player in players]
        hoops = self.attack_hoops + [self.attack_hoops[1]] # add center hoop as additional "hoop"
        target_positions = [hoop.position for hoop in hoops] # add center hoop again as additional target
        best_permutation, _ = self.solve_assignment_problem(player_positions, target_positions)
        max_player_index = len(player_positions) - 1
        for i, player_index in enumerate(best_permutation):
            if player_index > max_player_index:
                continue
            player = players[player_index]
            if player.id in self.attack_cpu_player_ids:

                hoop = hoops[i]
                if player.role == PlayerRole.CHASER:
                    move_vector = self.move_around_hoop_blockage(player, hoop.position, add_hoop_blockage_x=player.radius)
                else:
                    move_vector = Vector2(
                        hoop.position.x - player.position.x,
                        hoop.position.y - player.position.y
                    )
                move_vector_mag = UtilityLogic._magnitude(move_vector)
                if move_vector_mag == 0:
                    move_vector = Vector2(0, 0)
                else:
                    move_vector = Vector2(
                        move_vector.x / move_vector_mag,
                        move_vector.y / move_vector_mag
                    )
                move_vectors_dict[player.id] = move_vector
        return move_vectors_dict
    
    def evade_vectors_chaser_keeper_calculation(self) -> Dict[str, Vector2]:
        evade_vectors_dict = {}
        for player_id in self.attacking_chaser_keeper_ids:
            player = self.logic.state.players[player_id]
            total_evade_vector = Vector2(0, 0)
            for other_player in self.logic.state.players.values():
                if other_player.team != self.attack_team:
                    if other_player.role == PlayerRole.BEATER and other_player.has_ball:
                        evade_vector = MoveUtility.evade(player.position, other_player.position, weight=self.chaser_evade_beater_weight)
                        total_evade_vector.x += evade_vector.x
                        total_evade_vector.y += evade_vector.y
                    elif other_player.role in [PlayerRole.CHASER, PlayerRole.KEEPER]: # if chaser or keeper, also check distance and evade if too close
                        evade_vector = MoveUtility.evade(player.position, other_player.position, weight=self.chaser_evade_chaser_keeper_weight)
                        total_evade_vector.x += evade_vector.x
                        total_evade_vector.y += evade_vector.y
                elif other_player.role in [PlayerRole.CHASER, PlayerRole.KEEPER] and other_player.id != player.id: # also evade teammates who are chasers or keepers to avoid clustering
                    evade_vector = MoveUtility.evade(player.position, other_player.position, weight=self.chaser_evade_teamate_chaser_keeper_weight)
                    total_evade_vector.x += evade_vector.x
                    total_evade_vector.y += evade_vector.y
            evade_vectors_dict[player.id] = total_evade_vector
        return evade_vectors_dict

    def player_passing(self,
                       volleyball: VolleyBall,
                       volleyball_holder: Player,
                       evade_vectors_dict: Dict[str, Vector2],
                       ):
        """
        Calculate position penalty for each teammate chaser/keeper based on:
            - their squared distance to the closest attack hoop (the closer the better, since they can receive the ball and have a better chance to score or draw opponents when closer to the hoops)
            - their total_evade_vector magnitude (the higher the more pressure on that player, so the less likely we want to pass to them)

        Sort teammates by lowest position penalty. If the lowest score is the volleyball_holder keep the ball. Otherwise, check with beam interception if passing to that teammate is an option.
        """
        if volleyball.is_dead:
            return # don't pass if ball is dead, just try to get it back to life
        # TODO Prevent passing through own hoops
        position_penalty_dict = {}
        for player_id in self.attacking_chaser_keeper_ids:
            player = self.logic.state.players[player_id]
            if player.is_knocked_out:
                continue
            if self.logic.state.squared_distances_ball_player_dicts[volleyball.id][player_id] > self.passing_squared_max_distance:
                continue
            closest_attack_hoop_squared_distance = min([
                UtilityLogic._squared_distance(player.position, hoop.position) for hoop in self.attack_hoops
            ])
            evade_vector = evade_vectors_dict.get(player.id, Vector2(0, 0))
            squared_mag_evade_vector = evade_vector.x**2 + evade_vector.y**2
            position_penalty = closest_attack_hoop_squared_distance + self.passing_evade_vector_position_penalty_weight * squared_mag_evade_vector
            position_penalty_dict[player.id] = position_penalty
            # self.logger.debug("Player %s position penalty: %s, closest_attack_hoop_squared_distance: %s, squared_mag_evade_vector: %s", player.id, position_penalty, closest_attack_hoop_squared_distance, squared_mag_evade_vector)
        sorted_position_penalty = sorted(position_penalty_dict.items(), key=lambda x: x[1])
        
        # loop through sorted position penalty and pass to the first teammate that has a good enough interception score, if there is no such teammate then keep the ball
        for player_id, position_penalty in sorted_position_penalty:
            best_player_id, best_position_penalty = sorted_position_penalty[0]
            if best_player_id == volleyball_holder.id:
                self.logger.debug("Best player to pass to is current holder %s with position penalty %s, so keeping the ball", best_player_id, best_position_penalty)
                return
            best_player = self.logic.state.players[best_player_id]
            throw_direction = ThrowDirector.get_throw_direction_moving_receiver(volleyball_holder, best_player)
            beam_cosine_angle, beam_cosine_angle_player_id, _ = self.interception_calculator_opponent.beam_cosine_angle(
                moving_entity=volleyball,
                intercepting_player_ids=self.defending_chaser_keeper_ids,
                target_position=best_player.position, # approximate with current position instead of predicted position
                moving_entity_target_vector=throw_direction
            )
            interception_score = self.interception_calculator_opponent.interception_score_from_beam_cosine_angle(
                beam_cosine_angle=beam_cosine_angle,
                beam_angle_player_id=beam_cosine_angle_player_id,
                mag_moving_entity_velocity=volleyball_holder.throw_velocity,
                # squared_moving_entity_target_distance=UtilityLogic._squared_distance(volleyball.position, best_player.position)
            )
            if interception_score > self.passing_threshold:
                self.logger.info("Passing from player %s to player %s with position penalty %s and interception score %s", volleyball_holder.id, best_player_id, best_position_penalty, interception_score)
                self.logic.process_action_logic.process_throw_action(volleyball_holder.id, throw_direction=throw_direction)
                return

    def solve_assignment_problem(self, player_positions: List[Vector2], target_positions: List[Vector2]):
        if len(player_positions) == 0 or len(target_positions) == 0:
            return [], float('inf')
        best_cost = float('inf')
        best_perm = None
        max_player_index = len(player_positions) - 1
        for perm in itertools.permutations(range(len(target_positions))):
            cost = 0
            for i, player_index in enumerate(perm):
                if player_index > max_player_index: # if there are more target positions than players, some target positions will not be assigned a player, which we can consider as assigned to a "dummy" player at the center of the field (so that we don't have to worry about unassigned target positions)
                    continue
                cost += UtilityLogic._squared_distance(player_positions[player_index], target_positions[i])
            if cost < best_cost:
                best_cost = cost
                best_perm = perm            
        return list(best_perm), float(best_cost)
    
    def beater_move_action(self, beater: Player, volleyball: VolleyBall):
        """
        Beaters making pressure similar to getting BC/ready go.

        Move to volleyball.

        If loaded, evade unloaded opponent beaters.

        Anti-evade towards loaded opponent beaters, the closer the more aggressive towards them.

        Different weights depending on if our beater is loaded.
        """
        move_vector = Vector2(
            volleyball.position.x - beater.position.x,
            volleyball.position.y - beater.position.y
        )
        evade_vectors = []
        if beater.has_ball:
            weight_loaded_opponent_beater = self.loaded_beater_evade_loaded_opponent_beater_weight
        else:
            weight_loaded_opponent_beater = self.unloaded_beater_evade_loaded_opponent_beater_weight
        for opponent_beater_id in self.defending_beater_ids:
            opponent_beater = self.logic.state.players[opponent_beater_id]
            if opponent_beater.is_knocked_out:
                continue
            if opponent_beater.has_ball:
                evade_vector = MoveUtility.evade(beater.position, opponent_beater.position, weight=weight_loaded_opponent_beater)
            elif beater.has_ball: 
                evade_vector = MoveUtility.evade(beater.position, opponent_beater.position, weight=self.loaded_beater_evade_unloaded_opponent_beater_weight)
            else: # unloaded opponent only matters if beater has ball
                continue
            evade_vectors.append(evade_vector)
        for evade_vector in evade_vectors:    
            move_vector.x += evade_vector.x
            move_vector.y += evade_vector.y
        beater.direction = move_vector


    def beater_throw_action(self, beater: Player, volleyball: VolleyBall):
        if not beater.has_ball:
            return
        for opponent_beater_id in self.defending_beater_ids:
            opponent_beater = self.logic.state.players[opponent_beater_id]
            if opponent_beater.is_knocked_out:
                continue
            if opponent_beater.has_ball:
                if self.beater_throw_decider.should_throw_at_loaded_beater(beater, opponent_beater):
                    throw_direction = ThrowDirector.get_throw_direction_moving_receiver(beater, opponent_beater)
                    self.logic.process_action_logic.process_throw_action(beater.id, throw_direction=throw_direction)
                    # throw at first egligble loaded opponent beater
                    break
            

    def __call__(self,
                dt: float,
                next_volleyball_holder_id: str,
                intercepting_position: Optional[Vector2] = None,
                assigned_beater_ids: List[str] = []
                ):
        volleyball = self.logic.state.volleyball
        attacking_chaser_keeper = [self.logic.state.players[player_id] for player_id in self.attacking_chaser_keeper_ids]
        not_knocked_out_chaser_keeper = [
            player for player in attacking_chaser_keeper if (
                not player.is_knocked_out and player.role in [PlayerRole.CHASER, PlayerRole.KEEPER]
            )]
        # if volleyball.holder_id is not None:
        #     self.get_intercepting_scores_for_hoops(dt, volleyball, self.logic.state.players[volleyball.holder_id])
        move_vector__chaser_dict = self.move_chaser_keeper_hoops(not_knocked_out_chaser_keeper)
        evade_vectors_chaser_dict = self.evade_vectors_chaser_keeper_calculation()
        # for debugging
        # if volleyball.holder_id is not None and volleyball.holder_id not in self.attack_cpu_player_ids:
        #     self.player_passing(volleyball=volleyball, volleyball_holder=self.logic.state.players[volleyball.holder_id], evade_vectors_dict=evade_vectors_dict)

        if next_volleyball_holder_id in self.attack_cpu_player_ids:
            if volleyball.holder_id is None:
                self.move_to_volleyball(volleyball, next_volleyball_holder_id, intercepting_position)
            else: # already hold of volleyball
                volleyball_holder = self.logic.state.players[volleyball.holder_id]
                self.player_positioning(volleyball_holder, evade_vectors_chaser_dict.get(volleyball_holder.id, Vector2(0, 0)), move_vector__chaser_dict.get(volleyball_holder.id, None)) # position volleyball holder to evade opponents while holding the ball
                tries_to_score = self.score_attempt(dt, volleyball, volleyball_holder)
                if not tries_to_score:
                    self.player_passing(volleyball=volleyball, volleyball_holder=volleyball_holder, evade_vectors_dict=evade_vectors_chaser_dict)
        # elif volleyball.holder_id is not None:
        #     self.get_intercepting_scores_for_hoops(dt, volleyball, self.logic.state.players[volleyball.holder_id])
        # if (# volleyball in own half
        #     volleyball.position.x < self.logic.state.boundaries_x[1] / 2 and self.attack_team == 0
        #     ) or (
        #     volleyball.position.x > self.logic.state.boundaries_x[1] / 2 and self.attack_team == 1
        # ):
        for player_id in self.attack_cpu_player_ids:
            if player_id != next_volleyball_holder_id: # dealing with volleyball holder before
                player = self.logic.state.players[player_id]
                if player.role in [PlayerRole.CHASER, PlayerRole.KEEPER]:
                    # not if knocked out, inbounding, or if keeper and volleyball is dead and in their possession (since in that case they should be trying to get the ball back to life instead of positioning for attack)
                    if not player.is_knocked_out and not player.inbounding and not (player.role == PlayerRole.KEEPER and volleyball.is_dead and volleyball.possession_team == player.team):
                        self.player_positioning(player, evade_vectors_chaser_dict.get(player.id, Vector2(0, 0)), move_vector__chaser_dict.get(player.id, None))
                elif player.role == PlayerRole.BEATER and player.id not in assigned_beater_ids:
                    self.beater_move_action(player, volleyball)
                    self.beater_throw_action(player, volleyball)

