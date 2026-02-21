from abc import ABC, abstractmethod
from typing import List
from core.game_logic.game_logic import GameLogic
from core.entities import Player, Ball, VolleyBall, DodgeBall, Vector2, PlayerRole, BallType
from computer_player.hoop_defence import HoopDefence
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
    def __init__(self, game_logic: GameLogic, cpu_player_ids: List[str], move_buffer_factor: float = 1.2):
        super().__init__(game_logic, cpu_player_ids)
        self.move_buffer_factor = move_buffer_factor

    def make_move(self, dt: float):
        # self._hoop_defence([cpu_player.id for cpu_player in self.cpu_players if cpu_player.team == self.logic.state.team_0], self.logic.state.team_0)
        cpu_player_ids_defence = [cpu_player.id for cpu_player in self.cpu_players if cpu_player.team == self.logic.state.team_1]
        defence_player_ids = [player.id for player in self.logic.state.players.values() if player.team == self.logic.state.team_1]
        HoopDefence(
            logic = self.logic,
            defence_cpu_player_ids=cpu_player_ids_defence,
            defence_player_ids=defence_player_ids,
            team=self.logic.state.team_1,
            move_buffer_factor=self.move_buffer_factor
            )(dt)
        # self._hoop_defence([cpu_player.id for cpu_player in self.cpu_players if cpu_player.team == self.logic.state.team_1], self.logic.state.team_1)

