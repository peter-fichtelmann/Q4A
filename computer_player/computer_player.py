from abc import ABC, abstractmethod
from typing import List, Tuple
from core.game_logic.game_logic import GameLogic
from core.entities import Player, Ball, VolleyBall, DodgeBall, Vector2, PlayerRole, BallType
from computer_player.hoop_defence import HoopDefence
from computer_player.diamond_attack import DiamondAttack
from computer_player.computer_player_utility import InterceptionRatioCalculator, MoveAroundHoopBlockage
import random

class ComputerPlayer(ABC):
    """
    Abstract base class for a computer player in a game. 
    It defines the interface for changing the direction and actions of the computer-controlled players.
    """
    def __init__(self, game_logic: GameLogic, cpu_player_ids: List[str]):
        self.logic = game_logic
        self.cpu_player_ids = cpu_player_ids
        self.cpu_players = [self.logic.state.players[player_id] for player_id in cpu_player_ids]

    @abstractmethod
    def make_move(self, dt: float):
        pass


class RandomComputerPlayer(ComputerPlayer):
    def __init__(self, game_logic: GameLogic, cpu_player_ids: List[str], throwing_probability: float = 0.1):
        super().__init__(game_logic, cpu_player_ids)
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
                 determine_attacking_team_max_dt_steps: int = 10
                 ):
        super().__init__(game_logic, cpu_player_ids)
        self.move_buffer_factor = move_buffer_factor
        self.determine_attacking_team_max_dt_steps = determine_attacking_team_max_dt_steps
        defence_hoops_0 = []
        defence_hoops_1 = []
        for hoop in self.logic.state.hoops.values():
            if hoop.team == 0:
                defence_hoops_0.append(hoop)
            else:
                defence_hoops_1.append(hoop)
        self.move_around_hoop_blockage_team_0 = MoveAroundHoopBlockage(defence_hoops=defence_hoops_0, move_buffer_factor=self.move_buffer_factor)
        self.move_around_hoop_blockage_team_1 = MoveAroundHoopBlockage(defence_hoops=defence_hoops_1, move_buffer_factor=self.move_buffer_factor)
        self.interception_ratio_calculator_team_0 = InterceptionRatioCalculator(
            logic=self.logic,
            max_dt_steps=self.determine_attacking_team_max_dt_steps,
            move_around_hoop_blockage=self.move_around_hoop_blockage_team_0,
            )
        self.interception_ratio_calculator_team_1 = InterceptionRatioCalculator(
            logic=self.logic,
            max_dt_steps=self.determine_attacking_team_max_dt_steps,
            move_around_hoop_blockage=self.move_around_hoop_blockage_team_1,
            )

    def make_move(self, dt: float):
        # self._hoop_defence([cpu_player.id for cpu_player in self.cpu_players if cpu_player.team == self.logic.state.team_0], self.logic.state.team_0)
        attacking_team, next_volleyball_holder_id, intercepting_position = self._determine_attacking_team(dt)
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
                move_buffer_factor=self.move_buffer_factor
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
                move_buffer_factor=self.move_buffer_factor
                )(dt)
        DiamondAttack(
            logic=self.logic,
            attack_cpu_player_ids=[cpu_player.id for cpu_player in self.cpu_players if cpu_player.team == attacking_team]
            )(
                dt=dt,
                next_volleyball_holder_id=next_volleyball_holder_id,
                intercepting_position=intercepting_position
            )
        # self._hoop_defence([cpu_player.id for cpu_player in self.cpu_players if cpu_player.team == self.logic.state.team_1], self.logic.state.team_1)

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
            potential_intercepting_players = [player.id for player in self.logic.state.players.values() if player.role in [PlayerRole.CHASER, PlayerRole.KEEPER]]
            _, step_ratio_dict_team_0 = self.interception_ratio_calculator_team_0(
                dt=dt,
                moving_entity=volleyball,
                intercepting_player_ids=potential_intercepting_players,
                target_position=None,
                only_first_intercepting=True
            )
            _, step_ratio_dict_team_1 = self.interception_ratio_calculator_team_1(
                dt=dt,
                moving_entity=volleyball,
                intercepting_player_ids=potential_intercepting_players,
                target_position=None,
                only_first_intercepting=True
            )
            step_ratio_dict = {**step_ratio_dict_team_0, **step_ratio_dict_team_1}
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
                print(f'Ball will be potentially intercepted by player {player_id} from position {player.position} in team {player.team} with intercepting details {step_ratio_dict[player_id]}')
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