from typing import List
from core.game_logic.game_logic import GameLogic
from core.entities import Hoop, Player, Ball, VolleyBall, DodgeBall, Vector2, PlayerRole, BallType

class HoopDefence:
    def __init__(self, logic, defence_player_ids: List[str], defence_cpu_player_ids: List[str], team: int):    
        self.logic = logic
        self.defence_player_ids = defence_player_ids
        self.defence_cpu_player_ids = defence_cpu_player_ids
        self.team = team

        self.keeper_zone_x = self.logic.state.keeper_zone_x_0 if team == self.logic.state.team_0 else self.logic.state.keeper_zone_x_1
        self.defence_hoops = [hoop for hoop in self.logic.state.hoops.values() if hoop.team == team]

    def __call__(self):
        volleyball = self.logic.state.get_volleyball()
        
        volleyball_hoop_distances = {
            hoop.id: (volleyball.position.x - hoop.position.x) ** 2 + (volleyball.position.y - hoop.position.y) ** 2
            for hoop in self.defence_hoops
        }   
        sorted_hoop_distances = sorted(volleyball_hoop_distances.items(), key=lambda item: item[1])
        closest_hoop_id, closest_hoop_distance = sorted_hoop_distances[0]
        closest_hoop = self.logic.state.hoops[closest_hoop_id]
        chaser_hoop_squared_distances = {hoop.id: {} for hoop in self.defence_hoops}

        for player_id in self.defence_player_ids:
            player = self.logic.state.get_player(player_id)
            if not player:
                continue
            if player.role == PlayerRole.KEEPER and player.id in self.defence_cpu_player_ids:
                self.keeper_action(player, volleyball, closest_hoop)
            elif player.role == PlayerRole.CHASER:
                # get positions of chasers to hoops
                if not player.is_knocked_out:
                    for hoop in self.defence_hoops:
                        chaser_hoop_squared_distances[hoop.id][player.id] = (player.position.x - hoop.position.x) ** 2 + (player.position.y - hoop.position.y) ** 2
        self.chasers_action(sorted_hoop_distances, chaser_hoop_squared_distances)

    def chasers_action(self, sorted_hoop_distances, chaser_hoop_squared_distances):
        # move chaser closest to hoop with closest distance volleyball first; then move next closest chaser to next closest hoop and so on, but only if they are not already directed towards a hoop by a closer chaser
        directed_chasers = []
        for hoop_id, _ in sorted_hoop_distances:
            sorted_chaser_distances = sorted(chaser_hoop_squared_distances[hoop_id].items(), key=lambda item: item[1])
            for chaser_id, _ in sorted_chaser_distances:
                if chaser_id not in directed_chasers:
                    chaser = self.logic.state.get_player(chaser_id)
                    hoop = self.logic.state.hoops[hoop_id]
                    directed_chasers.append(chaser_id)
                    if chaser_id in self.defence_cpu_player_ids:
                        # TODO: chasers move with volleyball movement (between hoop x +/-) and chasers acknowledge hoop blockage and move around it if volleyball less than hoop x
                        direction_to_hoop = Vector2(
                            hoop.position.x - chaser.position.x,
                            hoop.position.y - chaser.position.y
                        )
                        chaser.direction = direction_to_hoop
                    # print(f'[CPU Player] Moving chaser {chaser_id} towards hoop {hoop_id}')
                    break

    def _volleyball_player_hoop_blockage(self, volleyball: VolleyBall, player: Player):
        # hoop width: hoop.radius
        # hoop thickness: player.radius + ball.radius
        volleyball_player_vector = Vector2(
            volleyball.position.x - player.position.x,
            volleyball.position.y - player.position.y
        )
        hoop_blockage_x_1 = self.defence_hoops[0].position.x + volleyball.radius + player.radius
        hoop_blockage_x_2 = self.defence_hoops[0].position.x - volleyball.radius - player.radius
        hoop_blockage_y_dict = {}
        line_t_1 = (hoop_blockage_x_1 - player.position.x) / volleyball_player_vector.x if volleyball_player_vector.x != 0 else float('inf')
        line_t_2 = (hoop_blockage_x_2 - player.position.x) / volleyball_player_vector.x if volleyball_player_vector.x != 0 else float('inf')
        if 0 < line_t_1 and line_t_1 < 1:
            line_y_1 = player.position.y + volleyball_player_vector.y * line_t_1
        

        

    def _is_volleyball_in_keeper_zone(self, volleyball: VolleyBall) -> bool:
        if volleyball is not None:
            if self.team == self.logic.state.team_0:
                return volleyball.position.x < self.keeper_zone_x
            else:
                return volleyball.position.x > self.keeper_zone_x

    def keeper_action(self, player: Player, volleyball: VolleyBall, closest_hoop: Hoop):
        # TODO: keeper anticipates next volleyball position by velocitiy
        # if volleyball is in keeper zone, move towards the volleyball, else move towards the crossing point of volleyball-closest hoop and keeper zone line
        if self._is_volleyball_in_keeper_zone(volleyball):
            # Move towards the volleyball
            direction_to_ball = Vector2(
                volleyball.position.x - player.position.x,
                volleyball.position.y - player.position.y
            )
            player.direction = direction_to_ball
        else:
            # calculate crossing point of volleyball-closest hoop and keeper zone line
            closest_hoop_volleyball_vector = Vector2(
                closest_hoop.position.x - volleyball.position.x,
                closest_hoop.position.y - volleyball.position.y
            )
            crossing_point_x = self.keeper_zone_x
            crossing_point_y = volleyball.position.y + ((crossing_point_x - volleyball.position.x) / closest_hoop_volleyball_vector.x) * closest_hoop_volleyball_vector.y
            player.direction.x = crossing_point_x - player.position.x
            player.direction.y = crossing_point_y - player.position.y
            # print(f'[CPU Player] Volleyball is not in keeper zone, moving towards crossing point at ({crossing_point_x}, {crossing_point_y})')
        # always try to tackle if not throwing
        self.logic.process_action_logic.process_tackle_action(player.id)

            # print(f'[CPU Player] Volleyball is in keeper zone, moving towards the volleyball')