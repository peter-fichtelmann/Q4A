from abc import ABC, abstractmethod
import logging
from typing import List, Tuple
from core.game_logic.game_logic import GameLogic
from core.entities import Player, Ball, VolleyBall, DodgeBall, Vector2, PlayerRole, BallType
from computer_player.hoop_defence import HoopDefence
from computer_player.diamond_attack import DiamondAttack
from computer_player.computer_player_utility import InterceptionRatioCalculator, MoveAroundHoopBlockage
import random

from core.game_logic.utility_logic import UtilityLogic

class ComputerPlayer(ABC):
    """
    Abstract base class for a computer player in a game. 
    It defines the interface for changing the direction and actions of the computer-controlled players.
    """
    def __init__(self, game_logic: GameLogic, cpu_player_ids: List[str], computer_player_log_level: int = logging.INFO):
        self.logic = game_logic
        self.cpu_player_ids = cpu_player_ids
        self.cpu_players = [self.logic.state.players[player_id] for player_id in cpu_player_ids]
        self.logger = logging.getLogger("computer_player")
        self.logger.setLevel(computer_player_log_level)

    @abstractmethod
    def make_move(self, dt: float):
        pass


class RandomComputerPlayer(ComputerPlayer):
    def __init__(self,
                 game_logic: GameLogic,
                 cpu_player_ids: List[str],
                 throwing_probability: float = 0.1,
                 computer_player_log_level: int = logging.INFO):
        super().__init__(game_logic, cpu_player_ids, computer_player_log_level=computer_player_log_level)
        self.throwing_probability = throwing_probability

    def make_move(self, dt: float):
        # add random number between -1 and 1 to the x and y direction of each CPU player
        # print(f'[CPU Player] Making move for {len(self.cpu_players)} CPU players')
        for player in self.cpu_players:
            player.direction.x += random.uniform(-1, 1)
            player.direction.y += random.uniform(-1, 1)
            throwing_decision = random.random() < self.throwing_probability
            if throwing_decision:
                self.logic.process_action_logic.process_throw_action(player.id)
            # always try to tackle if not throwing
            self.logic.process_action_logic.process_tackle_action(player.id)

            
class RuleBasedComputerPlayer(ComputerPlayer):
    def __init__(self,
                 game_logic: GameLogic,
                 cpu_player_ids: List[str],
                 move_buffer_factor: float = 1.2,
                 determine_attacking_team_max_dt_steps: int = 10,
                 determine_attacking_team_max_distance_per_step: float = None,
                 determine_attacking_team_max_dt_per_step: int = None,
                 score_interception_max_dt_steps: int = 10,
                 score_interception_max_distance_per_step: float = 0.5,
                 score_interception_max_dt_per_step: int = 0.25,
                 scoring_threshold: float = 0.8,
                 evade_beater_importance: float = 4,
                 evade_chaser_keeper_importance: float = 2,
                 evade_teamate_chaser_keeper_importance: float = 1,
                 positioning_boundary_buffer_distance: float = 2,
                 simulation_game_logic_log_level: int = None,
                 computer_player_log_level: int = logging.INFO
                 ):
        super().__init__(game_logic, cpu_player_ids, computer_player_log_level=computer_player_log_level)
        self.move_buffer_factor = move_buffer_factor
        self.determine_attacking_team_max_dt_steps = determine_attacking_team_max_dt_steps
        self.determine_attacking_team_max_distance_per_step = determine_attacking_team_max_distance_per_step
        self.determine_attacking_team_max_dt_per_step = determine_attacking_team_max_dt_per_step
        self.scoring_threshold = scoring_threshold
        self.evade_beater_importance = evade_beater_importance
        self.evade_chaser_keeper_importance = evade_chaser_keeper_importance
        self.evade_teamate_chaser_keeper_importance = evade_teamate_chaser_keeper_importance
        self.positioning_boundary_buffer_distance = positioning_boundary_buffer_distance

        self.score_interception_max_dt_steps = score_interception_max_dt_steps
        self.score_interception_max_distance_per_step = score_interception_max_distance_per_step
        self.score_interception_max_dt_per_step = score_interception_max_dt_per_step

        self.beaters = [player for player in self.logic.state.players.values() if player.role == PlayerRole.BEATER]

        defence_hoops_0 = []
        defence_hoops_1 = []
        for hoop in self.logic.state.hoops.values():
            if hoop.team == 0:
                defence_hoops_0.append(hoop)
            else:
                defence_hoops_1.append(hoop)
        volleyball_radius = self.logic.state.get_volleyball().radius if self.logic.state.get_volleyball() is not None else 0
        self.move_around_hoop_blockage_team_0 = MoveAroundHoopBlockage(
            defence_hoops=defence_hoops_0,
            move_buffer_factor=self.move_buffer_factor,
            volleyball_radius=volleyball_radius,
            logger=self.logger
            )
        self.move_around_hoop_blockage_team_1 = MoveAroundHoopBlockage(
            defence_hoops=defence_hoops_1,
            move_buffer_factor=self.move_buffer_factor,
            volleyball_radius=volleyball_radius,
            logger=self.logger
            )
        self.interception_ratio_calculator_team_0 = InterceptionRatioCalculator(
            logic=self.logic,
            move_around_hoop_blockage=self.move_around_hoop_blockage_team_0,
            log_level=simulation_game_logic_log_level,
            logger=self.logger
            )
        self.interception_ratio_calculator_team_1 = InterceptionRatioCalculator(
            logic=self.logic,
            move_around_hoop_blockage=self.move_around_hoop_blockage_team_1,
            log_level=simulation_game_logic_log_level,
            logger=self.logger
            )

    def make_move(self, dt: float):
        # self._hoop_defence([cpu_player.id for cpu_player in self.cpu_players if cpu_player.team == self.logic.state.team_0], self.logic.state.team_0)
        attacking_team, next_volleyball_holder_id, intercepting_position = self._determine_attacking_team(dt)
        self._determine_beater_ball_getting(dt)
        if attacking_team is None:
            # both teams in attacking mode
            pass
        elif attacking_team == self.logic.state.team_0:
            # team 0 attacking, team 1 defending
            defence_cpu_player_ids = [cpu_player.id for cpu_player in self.cpu_players if cpu_player.team == self.logic.state.team_1]
            defence_player_ids = [player.id for player in self.logic.state.players.values() if player.team == self.logic.state.team_1]
            HoopDefence(
                logic = self.logic,
                defence_cpu_player_ids=defence_cpu_player_ids,
                defence_player_ids=defence_player_ids,
                team=self.logic.state.team_1,
                move_around_hoop_blockage=self.move_around_hoop_blockage_team_1,
                )(dt)
        else:
            # team 1 attacking, team 0 defending
            defence_cpu_player_ids = [cpu_player.id for cpu_player in self.cpu_players if cpu_player.team == self.logic.state.team_0]
            defence_player_ids = [player.id for player in self.logic.state.players.values() if player.team == self.logic.state.team_0]
            HoopDefence(
                logic = self.logic,
                defence_cpu_player_ids=defence_cpu_player_ids,
                defence_player_ids=defence_player_ids,
                team=self.logic.state.team_0,
                move_around_hoop_blockage=self.move_around_hoop_blockage_team_0,
                )(dt)
        DiamondAttack(
            logic=self.logic,
            move_around_hoop_blockage=self.move_around_hoop_blockage_team_0 if attacking_team == 0 else self.move_around_hoop_blockage_team_1,
            interception_ratio_calculator_opponent=self.interception_ratio_calculator_team_1 if attacking_team == 0 else self.interception_ratio_calculator_team_0, # inverse because we need hoop blockage of opponent team
            attack_cpu_player_ids=[cpu_player.id for cpu_player in self.cpu_players if cpu_player.team == attacking_team],
            attack_team=attacking_team,
            score_interception_max_dt_steps=self.score_interception_max_dt_steps,
            score_interception_max_distance_per_step=self.score_interception_max_distance_per_step,
            score_interception_max_dt_per_step=self.score_interception_max_dt_per_step,
            scoring_threshold=self.scoring_threshold,
            evade_beater_importance=self.evade_beater_importance,
            evade_chaser_keeper_importance=self.evade_chaser_keeper_importance,
            evade_teamate_chaser_keeper_importance=self.evade_teamate_chaser_keeper_importance,
            positioning_boundary_buffer_distance=self.positioning_boundary_buffer_distance,
            logger=self.logger
             )(
                dt=dt,
                next_volleyball_holder_id=next_volleyball_holder_id,
                intercepting_position=intercepting_position,
            )
        # self._hoop_defence([cpu_player.id for cpu_player in self.cpu_players if cpu_player.team == self.logic.state.team_1], self.logic.state.team_1)

    def _determine_beater_ball_getting(self, dt: float):
        """Determine if any beater should attempt to get a dodgeball."""
        third_dodgeball_team = self.logic.state.third_dodgeball_team
        if third_dodgeball_team is not None:
            # If there is a third dodgeball team, assign beater players to get the dodgeball
            self.logger.debug(f"Third dodgeball on team {third_dodgeball_team}, determining beater assignment to get the dodgeball")
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
                self.logger.debug(f"Beater {beater.id} assigned to get third dodgeball for team {third_dodgeball_team}")
                    # move towards the dodgeball
                if beater.id in self.cpu_player_ids:
                    beater.direction = squared_distance_and_direction_to_dodgeball_dict[beater.id][1]
   



    def _determine_attacking_team(self, dt: float) -> Tuple[int, str, Vector2]:
        """Return the attacking team and player id of the chaser/keeper assigned to the volleyball"""
        volleyball  = self.logic.state.get_volleyball()
        if volleyball.turnover_to_player is not None:
            player = self.logic.state.players[volleyball.turnover_to_player]
            return player.team, player.id, None
        if volleyball.inbounder is not None:
            player = self.logic.state.players[volleyball.inbounder]
            return player.team, player.id, None
        if volleyball.holder_id is not None:
            return volleyball.possession_team, volleyball.holder_id, None
        else:
            # elif volleyball.velocity.x > 0 or volleyball.velocity.y > 0:
            potential_intercepting_players_0 = [player.id for player in self.logic.state.players.values() if player.role in [PlayerRole.CHASER, PlayerRole.KEEPER] and player.team == 0]
            potential_intercepting_players_1 = [player.id for player in self.logic.state.players.values() if player.role in [PlayerRole.CHASER, PlayerRole.KEEPER] and player.team == 1]
            # need to consider two cases due to different move_hoop_blockage
            _, step_ratio_dict_team_0 = self.interception_ratio_calculator_team_0(
                dt=dt,
                moving_entity=volleyball,
                intercepting_player_ids=potential_intercepting_players_0,
                target_position=None,
                only_first_intercepting=True,
                max_dt_steps=self.determine_attacking_team_max_dt_steps,
                max_distance_per_step=self.determine_attacking_team_max_distance_per_step,
                max_dt_per_step=self.determine_attacking_team_max_dt_per_step

            )
            _, step_ratio_dict_team_1 = self.interception_ratio_calculator_team_1(
                dt=dt,
                moving_entity=volleyball,
                intercepting_player_ids=potential_intercepting_players_1,
                target_position=None,
                only_first_intercepting=True,
                max_dt_steps=self.determine_attacking_team_max_dt_steps,
                max_distance_per_step=self.determine_attacking_team_max_distance_per_step,
                max_dt_per_step=self.determine_attacking_team_max_dt_per_step
            )
            step_ratio_dict = {**step_ratio_dict_team_0, **step_ratio_dict_team_1}
            step_ratio_dict = {}
            if len(step_ratio_dict) > 0:
                if len(step_ratio_dict) > 1:
                    # get player with lowest step in step_ratio_dict[player_id] = (step, step_ratio)
                    min_step = float('inf')
                    min_player_id = None
                    for player_id, (step, step_ratio, _) in step_ratio_dict.items():
                        if step < min_step:
                            min_step = step
                            min_player_id = player_id
                    player_id = min_player_id

                else:
                    player_id = list(step_ratio_dict.keys())[0]
                player = self.logic.state.players[player_id]               
                intercepting_position = step_ratio_dict[player_id][2]
                self.logger.debug(
                    "Ball potentially intercepted by player %s from position %s in team %s with details %s",
                    player_id,
                    player.position,
                    player.team,
                    step_ratio_dict[player_id],
                )
                return player.team, player_id, intercepting_position
            # If no intercepting players, determine attacking team based on proximity to volleyball
            for other_id, distance in self.logic.state.squared_distances.get(volleyball.id, []):
                if other_id in self.logic.state.players.keys():
                    player = self.logic.state.players[other_id]
                    if not player.is_knocked_out:
                        if player.role in [PlayerRole.CHASER, PlayerRole.KEEPER]:
                            return player.team, player.id, None
            # if all players are knocked out
            return None, None, None