from abc import ABC, abstractmethod
from typing import List
from core.game_logic.game_logic import GameLogic
from core.entities import Player, Ball, VolleyBall, DodgeBall, Vector2, PlayerRole, BallType
import random

class ComputerPlayer(ABC):
    """
    Abstract base class for a computer player in a game. 
    It defines the interface for changing the direction and actions of the computer-controlled players.
    """
    def __init__(self, game_logic: GameLogic, cpu_player_ids: List[str]):
        self.logic = game_logic
        self.cpu_players = [self.logic.state.players[player_id] for player_id in cpu_player_ids]

    @abstractmethod
    def make_move(self):
        pass


class RandomComputerPlayer(ComputerPlayer):
    def __init__(self, game_logic: GameLogic, cpu_player_ids: List[str], throwing_probability: float = 0.1):
        super().__init__(game_logic, cpu_player_ids)
        self.throwing_probability = throwing_probability

    def make_move(self):
        # add random number between -1 and 1 to the x and y direction of each CPU player
        print(f'[CPU Player] Making move for {len(self.cpu_players)} CPU players')
        for player in self.cpu_players:
            player.direction.x += random.uniform(-1, 1)
            player.direction.y += random.uniform(-1, 1)
            throwing_decision = random.random() < self.throwing_probability
            if throwing_decision:
                self.logic.process_action_logic.process_throw_action(player.id)

            