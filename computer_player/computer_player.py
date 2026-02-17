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
        self.cpu_player_ids = cpu_player_ids
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
    def __init__(self, game_logic: GameLogic, cpu_player_ids: List[str]):
        super().__init__(game_logic, cpu_player_ids)

    def make_move(self):
        self._hoop_defence([cpu_player.id for cpu_player in self.cpu_players if cpu_player.team == self.logic.state.team_0], self.logic.state.team_0)
        # self._hoop_defence([cpu_player.id for cpu_player in self.cpu_players if cpu_player.team == self.logic.state.team_1], self.logic.state.team_1)

    def _hoop_defence(self, defending_player_ids: List[str], team: int):
        volleyball = self.logic.state.get_volleyball()
        if volleyball is not None:
            if team == self.logic.state.team_0:
                keeper_zone_x = self.logic.state.keeper_zone_x_0
                is_volleyball_in_keeper_zone = volleyball.position.x < keeper_zone_x
            else:
                keeper_zone_x = self.logic.state.keeper_zone_x_1
                is_volleyball_in_keeper_zone = volleyball.position.x > keeper_zone_x
        volleyball_hoop_distances = {
            hoop_id: (volleyball.position.x - hoop.position.x) ** 2 + (volleyball.position.y - hoop.position.y) ** 2
            for hoop_id, hoop in self.logic.state.hoops.items() if hoop.team == team
        }
        sorted_hoop_distances = sorted(volleyball_hoop_distances.items(), key=lambda item: item[1])
        closest_hoop_id, closest_hoop_distance = sorted_hoop_distances[0]
        closest_hoop = self.logic.state.hoops[closest_hoop_id]
        chaser_hoop_squared_distances = {hoop.id: {} for hoop in self.logic.state.hoops.values() if hoop.team == team}

        for player_id in defending_player_ids:
            player = self.logic.state.get_player(player_id)
            if not player:
                continue
            if player.role == PlayerRole.KEEPER and player.id in self.cpu_player_ids:
                # if volleyball is in keeper zone, move towards the volleyball, else move towards the crossing point of volleyball-closest hoop and keeper zone line
                if is_volleyball_in_keeper_zone:
                    # Move towards the volleyball
                    direction_to_ball = Vector2(
                        volleyball.position.x - player.position.x,
                        volleyball.position.y - player.position.y
                    )
                    player.direction = direction_to_ball
                    # print(f'[CPU Player] Volleyball is in keeper zone, moving towards the volleyball')
                else:
                    # calculate crossing point of volleyball-closest hoop and keeper zone line
                    closest_hoop_volleyball_vector = Vector2(
                        closest_hoop.position.x - volleyball.position.x,
                        closest_hoop.position.y - volleyball.position.y
                    )
                    crossing_point_x = keeper_zone_x
                    crossing_point_y = volleyball.position.y + ((crossing_point_x - volleyball.position.x) / closest_hoop_volleyball_vector.x) * closest_hoop_volleyball_vector.y
                    player.direction.x = crossing_point_x - player.position.x
                    player.direction.y = crossing_point_y - player.position.y
                    # print(f'[CPU Player] Volleyball is not in keeper zone, moving towards crossing point at ({crossing_point_x}, {crossing_point_y})')
                # always try to tackle if not throwing
                self.logic.process_action_logic.process_tackle_action(player.id)
            if player.role == PlayerRole.CHASER:
                if not player.is_knocked_out:
                    for hoop in self.logic.state.hoops.values():
                        if hoop.team == team:
                            chaser_hoop_squared_distances[hoop.id][player.id] = (player.position.x - hoop.position.x) ** 2 + (player.position.y - hoop.position.y) ** 2
        # move chaser closest to hoop with closest distance volleyball first; then move next closest chaser to next closest hoop and so on, but only if they are not already directed towards a hoop by a closer chaser
        directed_chasers = []
        for hoop_id, _ in sorted_hoop_distances:
            sorted_chaser_distances = sorted(chaser_hoop_squared_distances[hoop_id].items(), key=lambda item: item[1])
            for chaser_id, _ in sorted_chaser_distances:
                if chaser_id not in directed_chasers:
                    chaser = self.logic.state.get_player(chaser_id)
                    hoop = self.logic.state.hoops[hoop_id]
                    direction_to_hoop = Vector2(
                        hoop.position.x - chaser.position.x,
                        hoop.position.y - chaser.position.y
                    )
                    chaser.direction = direction_to_hoop
                    directed_chasers.append(chaser_id)
                    # print(f'[CPU Player] Moving chaser {chaser_id} towards hoop {hoop_id}')
                    break
        # TODO: chasers move with volleyball movement (between hoop x +/-) and chasers acknowledge hoop blockage and move around it if volleyball less than hoop x