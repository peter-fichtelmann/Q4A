from typing import List
from core.game_logic.game_logic import GameLogic
from core.entities import Hoop, Player, Ball, VolleyBall, DodgeBall, Vector2, PlayerRole, BallType
from computer_player.computer_player_utility import MoveAroundHoopBlockage
import random
import math

class HoopDefence:
    def __init__(self, logic, defence_player_ids: List[str], defence_cpu_player_ids: List[str], team: int, move_buffer_factor: float = 1.2, numerical_tol: float = 1e-2):    
        self.logic = logic
        self.defence_player_ids = defence_player_ids
        self.defence_cpu_player_ids = defence_cpu_player_ids
        self.team = team
        self.move_buffer_factor = move_buffer_factor
        self.tol = numerical_tol

        self.keeper_zone_x = self.logic.state.keeper_zone_x_0 if team == self.logic.state.team_0 else self.logic.state.keeper_zone_x_1
        self.defence_hoops = [hoop for hoop in self.logic.state.hoops.values() if hoop.team == team]
        self.move_around_hoop_blockage = MoveAroundHoopBlockage(self.defence_hoops, move_buffer_factor=self.move_buffer_factor, tol=self.tol)

    def __call__(self, dt: float):
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
        self.chasers_action(sorted_hoop_distances, chaser_hoop_squared_distances, volleyball, dt)

    def chasers_action(self, sorted_hoop_distances, chaser_hoop_squared_distances, volleyball: VolleyBall, dt: float):
        # move chaser closest to hoop with closest distance volleyball first; then move next closest chaser to next closest hoop and so on, but only if they are not already directed towards a hoop by a closer chaser
        directed_chasers = []
        for hoop_id, _ in sorted_hoop_distances:
            sorted_chaser_distances = sorted(chaser_hoop_squared_distances[hoop_id].items(), key=lambda item: item[1])
            for chaser_id, _ in sorted_chaser_distances:
                if chaser_id not in directed_chasers:
                    chaser = self.logic.state.get_player(chaser_id)
                    target_hoop = self.logic.state.hoops[hoop_id]
                    directed_chasers.append(chaser_id)
                    if chaser_id in self.defence_cpu_player_ids:
                        # TODO: chasers move with volleyball movement (between hoop x +/-) and chasers acknowledge hoop blockage and move around it if volleyball less than hoop x
                        add_hoop_blockage_x = chaser.radius + volleyball.radius
                        next_chaser_position = Vector2(
                            chaser.position.x + chaser.velocity.x * dt,
                            chaser.position.y + chaser.velocity.y * dt
                        )
                        next_volleyball_position = Vector2(
                            volleyball.position.x + volleyball.velocity.x * dt,
                            volleyball.position.y + volleyball.velocity.y * dt
                        )
                        if next_volleyball_position.x > target_hoop.position.x:
                            target = Vector2(target_hoop.position.x + add_hoop_blockage_x, target_hoop.position.y)
                            direction_to_hoop = Vector2(
                                (target_hoop.position.x + add_hoop_blockage_x) - chaser.position.x,
                                target_hoop.position.y - chaser.position.y
                            )
                            next_direction_to_hoop = Vector2(
                                (target_hoop.position.x + add_hoop_blockage_x) - next_chaser_position.x,
                                target_hoop.position.y - next_chaser_position.y
                            )
                            x_pos_position = True
                        else:
                            target = Vector2(target_hoop.position.x - add_hoop_blockage_x, target_hoop.position.y)
                            direction_to_hoop = Vector2(
                                (target_hoop.position.x - add_hoop_blockage_x) - chaser.position.x,
                                target_hoop.position.y - chaser.position.y
                            )
                            next_direction_to_hoop = Vector2(
                                (target_hoop.position.x - add_hoop_blockage_x) - next_chaser_position.x,
                                target_hoop.position.y - next_chaser_position.y
                            )
                            x_pos_position = False
                        #         x_pos_position = False
                        # print('direction to hoop: ', direction_to_hoop)
        
                        # print('player direction', chaser.direction)
                        # print('player velocity', chaser.velocity)
                        # print(f'[CPU Player] Moving chaser {chaser_id} towards hoop {hoop_id} with direction {chaser.direction}')
                        chaser.direction = self.move_around_hoop_blockage(
                            player=chaser,
                            target=target,
                            target_hoop=target_hoop,
                            add_hoop_blockage_x=add_hoop_blockage_x,
                            lookahead_to_target=next_direction_to_hoop,
                            add_target_x_buffer=True
                        )
                    # print(f'[CPU Player] Moving chaser {chaser_id} towards hoop {hoop_id}')
                    break

    # def _player_move_around_hoop_blockage(self, player: Player, direction_to_hoop: Vector2, next_direction_to_hoop: Vector2, add_hoop_blockage_x: float, x_pos_position: bool, target_hoop: Hoop):
    #     """Adjust a chaser's movement vector to avoid hoop obstruction while defending.

    #     This helper determines whether the straight path from the player's current
    #     position to the intended hoop-side aiming point intersects a rectangular blocked hoop
    #     region. The blocked region models hoop thickness using an x-range expanded
    #     by ``add_hoop_blockage_x`` and top/bottom hoop boundaries in y.

    #     The method computes two candidate intersections along the player's intended
    #     line of travel:

    #     1. An x-crossing (vertical to x-axis) against the target hoop's main line (scoring area, hoop radius)
    #     2. The earliest y-crossing (vertical to y-axis) against the upper/lower boundaries of any
    #        defensive hoop (hoop thickness)

    #     If no crossing is found, the player continues with ``next_direction_to_hoop``
    #     plus a small x-buffer offset to keep spacing from the hoop face. If a
    #     crossing is found, the player direction is redirected toward a buffered
    #     corner waypoint so the chaser moves around the hoop instead of clipping
    #     through its blocked area.

    #     Args:
    #         player: Defender being steered. The method writes to
    #             ``player.direction``.
    #         direction_to_hoop: Current-frame vector from player position to the
    #             selected hoop-side aiming point.
    #         next_direction_to_hoop: Next-frame estimated vector to the same aiming
    #             point, incorporating current velocity.
    #         add_hoop_blockage_x: Horizontal half-width used for hoop collision
    #             avoidance, typically ``player.radius + volleyball.radius``.
    #         x_pos_position: Which hoop side is being targeted. ``True`` means the
    #             right side of the hoop (positive x side), ``False`` means the left
    #             side.
    #         target_hoop: Hoop currently assigned to this defender and used as the
    #             primary obstacle reference.
    #     """
    #     # min_dir and min_velocity of players can make it difficult to go around hoops
    #     if direction_to_hoop.x == 0 and direction_to_hoop.y == 0:
    #         # no movement needed, already at the hoop, so no blockage
    #         return
    #     # hoop width: hoop.radius
    #     # hoop thickness: player.radius + ball.radius
    #     # player will not be blocked by hoop line where the target point is
    #     if x_pos_position:
    #         hoop_blockage_x = target_hoop.position.x - add_hoop_blockage_x
    #         add_x_buffer = - add_hoop_blockage_x * (self.move_buffer_factor - 1)
    #     else:
    #         hoop_blockage_x = target_hoop.position.x + add_hoop_blockage_x
    #         add_x_buffer = add_hoop_blockage_x * (self.move_buffer_factor - 1)
    #     # check x crossing
    #     line_t_x = (hoop_blockage_x - player.position.x) / direction_to_hoop.x if direction_to_hoop.x != 0 else float('inf')
    #     best_x_crossing  = (float('inf'), None, None, None) # (t, x, y, hoop)
    #     best_y_crossing = (float('inf'), None, None, None) # (t, x, y, hoop)
    #     if line_t_x > 0 - self.tol and line_t_x < 1 + self.tol:
    #         check_y_at_line_t_x = player.position.y + direction_to_hoop.y * line_t_x
    #         if (check_y_at_line_t_x >= target_hoop.position.y - target_hoop.radius and check_y_at_line_t_x <= target_hoop.position.y + add_hoop_blockage_x):
    #             best_x_crossing = (line_t_x, hoop_blockage_x + add_x_buffer, check_y_at_line_t_x, target_hoop)
    #     # check all possible y crossings
    #     for hoop in self.defence_hoops:
    #         for add_hoop_blockage_radius in [hoop.radius, - hoop.radius]:
    #             y = hoop.position.y + add_hoop_blockage_radius
    #             line_t_y = (y - player.position.y) / direction_to_hoop.y if direction_to_hoop.y != 0 else float('inf')
    #             if line_t_y > 0 - self.tol and line_t_y < 1 + self. tol:
    #                 x = player.position.x + direction_to_hoop.x * line_t_y
    #                 if (x >= hoop.position.x - add_hoop_blockage_x and x <= hoop.position.x + add_hoop_blockage_x):
    #                     if line_t_y < best_y_crossing[0]:
    #                         y = hoop.position.y + add_hoop_blockage_radius * self.move_buffer_factor # add buffer after checks (before checks leads to wrong checks)
    #                         best_y_crossing = (line_t_y, x, y, hoop)
    #     if math.isinf(best_x_crossing[0]) and math.isinf(best_y_crossing[0]):
    #         # no blockage found, move directly towards the hoop with estimation of current velocity taken into account
    #         player.direction = next_direction_to_hoop
    #         # add buffer
    #         player.direction.x -= add_x_buffer # inverse to add buffer
    #         return
    #     elif best_x_crossing[0] < best_y_crossing[0]:
    #         # use best x crossing
    #         # check closest corner of the hoop where the player should move towards with buffer to avoid blockage
    #         if direction_to_hoop.y < 0: # move towards upper corner
    #             corner_y = best_x_crossing[3].position.y + best_x_crossing[3].radius * self.move_buffer_factor
    #         else: # move towards lower corner
    #             corner_y = best_x_crossing[3].position.y - best_x_crossing[3].radius * self.move_buffer_factor
    #         player.direction.x = best_x_crossing[1] - player.position.x
    #         player.direction.y = corner_y - player.position.y
    #     else: # best y_crossing is closer
    #         if x_pos_position:
    #             corner_x = best_y_crossing[3].position.x + add_hoop_blockage_x * self.move_buffer_factor
    #         else:
    #             corner_x = best_y_crossing[3].position.x - add_hoop_blockage_x * self.move_buffer_factor
    #         player.direction.x = corner_x - player.position.x
    #         player.direction.y = best_y_crossing[2] - player.position.y


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