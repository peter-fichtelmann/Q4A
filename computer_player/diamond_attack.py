import itertools
import logging
from typing import Dict, Optional, List

from computer_player.computer_player_utility import InterceptionRatioCalculator, MoveAroundHoopBlockage
from core.entities import Player, PlayerRole, Vector2, VolleyBall
from core.game_logic.game_logic import GameLogic
from core.game_logic.utility_logic import UtilityLogic


class DiamondAttack:

    def __init__(self,
                logic: GameLogic,
                move_around_hoop_blockage: MoveAroundHoopBlockage,
                interception_ratio_calculator: InterceptionRatioCalculator,
                attack_cpu_player_ids: List[str],
                attack_team: int,
                score_interception_max_dt_steps: int = 10,
                score_interception_max_distance_per_step: Optional[float] = None,
                score_interception_max_dt_per_step: Optional[int] = None,
                scoring_threshold: float = 0.8,
                evade_beater_importance: float = 4,
                evade_chaser_keeper_importance: float = 2,
                evade_teamate_chaser_keeper_importance: float = 1,
                positioning_boundary_buffer_distance: float = 2, # distance from boundary at which to start evading boundary
                logger: Optional[logging.Logger] = None
                ):
        self.logic = logic
        self.move_around_hoop_blockage = move_around_hoop_blockage
        self.interception_ratio_calculator = interception_ratio_calculator
        self.attack_cpu_player_ids = attack_cpu_player_ids
        self.attack_team = attack_team
        self.score_interception_max_dt_steps = score_interception_max_dt_steps
        self.score_interception_max_distance_per_step = score_interception_max_distance_per_step
        self.score_interception_max_dt_per_step = score_interception_max_dt_per_step

        self.scoring_threshold = scoring_threshold
        self.evade_beater_importance = evade_beater_importance
        self.evade_chaser_keeper_importance = evade_chaser_keeper_importance
        self.evade_teamate_chaser_keeper_importance = evade_teamate_chaser_keeper_importance
        self.positioning_boundary_buffer_distance = positioning_boundary_buffer_distance
        self.logger = logger or logging.getLogger("computer_player")

        self.attack_hoops = [hoop for hoop in self.logic.state.hoops.values() if hoop.team != attack_team]
        self.attacking_chaser_keeper_ids = [player.id for player in self.logic.state.players.values() if player.team == attack_team and player.role in [PlayerRole.CHASER, PlayerRole.KEEPER]]
        self.defending_chaser_keeper_ids = [player.id for player in self.logic.state.players.values() if player.team != attack_team and player.role in [PlayerRole.CHASER, PlayerRole.KEEPER]]

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
            copy_volleyball = volleyball.copy()
            volleyball_hoop_vector = Vector2(
                hoop.position.x - copy_volleyball.position.x,
                hoop.position.y - copy_volleyball.position.y
            )
            mag_volleyball_hoop_vector = (volleyball_hoop_vector.x**2 + volleyball_hoop_vector.y**2) ** 0.5
            if mag_volleyball_hoop_vector == 0:
                continue
            copy_volleyball.velocity = Vector2(
                volleyball_holder.throw_velocity * volleyball_hoop_vector.x / mag_volleyball_hoop_vector,
                volleyball_holder.throw_velocity * volleyball_hoop_vector.y / mag_volleyball_hoop_vector
            )
            intercepting_score, scores_info = self.interception_ratio_calculator(
                 dt=dt,
                 moving_entity=copy_volleyball,
                 intercepting_player_ids=self.defending_chaser_keeper_ids,
                 max_dt_steps=self.score_interception_max_dt_steps,
                 target_position=hoop.position,
                 only_first_intercepting=False,
                 max_distance_per_step=self.score_interception_max_distance_per_step,
                 max_dt_per_step=self.score_interception_max_dt_per_step
            )
            intercepting_scores_dict[hoop.id] = intercepting_score
            # self.logger.debug("Interception info per hoop %s: %s, %s", hoop.id, intercepting_score, scores_info)
        self.logger.debug("intercepting_scores_dict %s", intercepting_scores_dict)
        return intercepting_scores_dict

    def score_attempt(self, dt: float, volleyball: VolleyBall, volleyball_holder: Player):
        intercepting_scores_dict = self.get_intercepting_scores_for_hoops(dt, volleyball, volleyball_holder)
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

    def evade_player(self, player: Player, opponent: Player, importance: float = 1.0) -> Vector2:
        """Evade player, e.g. chaser or loaded beater. Return evade vector"""
        player_to_opponent_vector = Vector2(
            opponent.position.x - player.position.x,
            opponent.position.y - player.position.y
        )
        squared_mag_player_to_opponent_vector = UtilityLogic._squared_sum(player_to_opponent_vector.x, player_to_opponent_vector.y)
        if squared_mag_player_to_opponent_vector == 0:
            return Vector2(0, 0)
        evade_vector = Vector2(
            -player_to_opponent_vector.x * importance / squared_mag_player_to_opponent_vector, # norm to one and then divide by distance to opponent to get stronger evasion when closer
            -player_to_opponent_vector.y * importance / squared_mag_player_to_opponent_vector
        )
        return evade_vector
    
    def player_positioning(self, player: Player, move_vector: Optional[Vector2] = None):
        if move_vector is None:
            move_vector = Vector2(
                1 - 2 * self.attack_team, # 1 for team 0 attacking, -1 for team 1 attacking
                0
            )
        # check distance to loaded opponent beater and evade if too close
        evade_vectors = []
        for other_player in self.logic.state.players.values():
            if other_player.team != self.attack_team:
                if other_player.role == PlayerRole.BEATER and other_player.has_ball:
                    evade_vector = self.evade_player(player, other_player, importance=self.evade_beater_importance)
                    evade_vectors.append(evade_vector)
                elif other_player.role in [PlayerRole.CHASER, PlayerRole.KEEPER]: # if chaser or keeper, also check distance and evade if too close
                    evade_vector = self.evade_player(player, other_player, importance=self.evade_chaser_keeper_importance)
                    evade_vectors.append(evade_vector)
            elif other_player.role in [PlayerRole.CHASER, PlayerRole.KEEPER] and other_player.id != player.id: # also evade teammates who are chasers or keepers to avoid clustering
                evade_vector = self.evade_player(player, other_player, importance=self.evade_teamate_chaser_keeper_importance)
                evade_vectors.append(evade_vector)
        for evade_vector in evade_vectors:
            self.logger.debug("Evade vector for player %s from opponent: %s", player.id, evade_vector)
            move_vector.x += evade_vector.x
            move_vector.y += evade_vector.y
        if player.position.y < self.logic.state.boundaries_y[0] + self.positioning_boundary_buffer_distance:
            move_vector.y = max(0, move_vector.y) # don't move down if already at boundary
        elif player.position.y > self.logic.state.boundaries_y[1] - self.positioning_boundary_buffer_distance:
            move_vector.y = min(0, move_vector.y) # don't move up if already at boundary
        if player.position.x < self.logic.state.boundaries_x[0] + self.positioning_boundary_buffer_distance:
            move_vector.x = max(0, move_vector.x) # don't move left if already at boundary
        elif player.position.x > self.logic.state.boundaries_x[1] - self.positioning_boundary_buffer_distance:
            move_vector.x = min(0, move_vector.x) # don't move right if already at boundary
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

    def __call__(self,
                dt: float,
                next_volleyball_holder_id: str,
                intercepting_position: Optional[Vector2] = None
                ):
        volleyball = self.logic.state.get_volleyball()
        attacking_chaser_keeper = [self.logic.state.players[player_id] for player_id in self.attacking_chaser_keeper_ids]
        not_knocked_out_chaser_keeper = [
            player for player in attacking_chaser_keeper if (
                not player.is_knocked_out and player.role in [PlayerRole.CHASER, PlayerRole.KEEPER]
            )]
        move_vector_dict = self.move_chaser_keeper_hoops(not_knocked_out_chaser_keeper)
        if next_volleyball_holder_id in self.attack_cpu_player_ids:
            if volleyball.holder_id is None:
                self.move_to_volleyball(volleyball, next_volleyball_holder_id, intercepting_position)
            else: # already hold of volleyball
                volleyball_holder = self.logic.state.players[volleyball.holder_id]
                self.player_positioning(volleyball_holder, move_vector_dict.get(volleyball_holder.id, None)) # position volleyball holder to evade opponents while holding the ball
                self.score_attempt(dt, volleyball, volleyball_holder)
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
                self.player_positioning(player, move_vector_dict.get(player.id, None))

