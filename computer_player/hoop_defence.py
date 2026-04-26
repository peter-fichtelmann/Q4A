from typing import List
from core.entities import Hoop, Player, VolleyBall, Vector2, PlayerRole
from computer_player.computer_player_utility.move_around_hoop_blockage import MoveAroundHoopBlockage
from computer_player.computer_player_utility.computer_player_utility import MoveUtility, BeaterThrowDecider, ThrowDirector
import random
import math

from core.game_logic.utility_logic import UtilityLogic

class HoopDefence:
    """
    Implements Hoop Defence where all chasers stand in front the hoops.
    The side changes when the volleyball moves over the hoop baseline.

    The keeper is moving towards the volleyball, but stays within the keeper zone.

    Beaters are sticking to the hoops and throw the volleyball if the volleyball holder is close enough.
    """
    def __init__(self,
                 logic,
                 defence_cpu_player_ids: List[str],
                 defence_team: int,
                 move_around_hoop_blockage: MoveAroundHoopBlockage,
                 beater_evade_beater_buddy_weight,
                 beater_evade_volleyball_weight,
                 beater_evade_chaser_keeper_weight,
                 loaded_beater_evade_beater_weight,
                 unloaded_beater_evade_beater_weight,
                 unloaded_beater_max_x_to_midline,
                 beater_throw_decider: BeaterThrowDecider,
                 positioning_boundary_buffer_distance: float = 2, # distance from boundary at which to start evading boundary
                 ):    
        self.logic = logic
        self.defence_players = [player for player in self.logic.state.players.values() if player.team == defence_team]
        self.defence_beaters = [player for player in self.defence_players if player.role == PlayerRole.BEATER]
        self.attack_players = [player for player in self.logic.state.players.values() if player.team != defence_team]
        self.defence_cpu_player_ids = defence_cpu_player_ids
        self.defence_team = defence_team
        self.beater_evade_beater_buddy_weight = beater_evade_beater_buddy_weight
        self.beater_evade_volleyball_weight = beater_evade_volleyball_weight
        self.beater_evade_chaser_keeper_weight = beater_evade_chaser_keeper_weight
        self.loaded_beater_evade_beater_weight = loaded_beater_evade_beater_weight
        self.unloaded_beater_evade_beater_weight = unloaded_beater_evade_beater_weight
        self.unloaded_beater_max_x_to_midline = unloaded_beater_max_x_to_midline
        self.positioning_boundary_buffer_distance = positioning_boundary_buffer_distance

        self.beater_throw_decider = beater_throw_decider
        # self.move_buffer_factor = move_buffer_factor
        # self.tol = numerical_tol

        self.keeper_zone_x = self.logic.state.keeper_zone_x_0 if defence_team == self.logic.state.team_0 else self.logic.state.keeper_zone_x_1
        self.defence_hoops = [hoop for hoop in self.logic.state.hoops.values() if hoop.team == defence_team]
        self.center_hoop = self.defence_hoops[1] if len(self.defence_hoops) == 3 else self.defence_hoops[0]
        self.move_around_hoop_blockage = move_around_hoop_blockage

    def __call__(self, dt: float, assigned_beater_ids: List[str] = []):
        volleyball = self.logic.state.volleyball
        
        volleyball_hoop_distances = {
            hoop.id: (volleyball.position.x - hoop.position.x) ** 2 + (volleyball.position.y - hoop.position.y) ** 2
            for hoop in self.defence_hoops
        }   
        sorted_hoop_distances = sorted(volleyball_hoop_distances.items(), key=lambda item: item[1])
        closest_hoop_id, closest_hoop_distance = sorted_hoop_distances[0]
        closest_hoop = self.logic.state.hoops[closest_hoop_id]
        chaser_hoop_squared_distances = {hoop.id: {} for hoop in self.defence_hoops}

        for player in self.defence_players:
            if player.role == PlayerRole.KEEPER and player.id in self.defence_cpu_player_ids:
                self.keeper_action(player, volleyball, closest_hoop)
            elif player.role == PlayerRole.CHASER:
                # get positions of chasers to hoops
                if not player.is_knocked_out:
                    for hoop in self.defence_hoops:
                        chaser_hoop_squared_distances[hoop.id][player.id] = (player.position.x - hoop.position.x) ** 2 + (player.position.y - hoop.position.y) ** 2
            # beater action if beater cpu player and not already assigned to get a dodgeball
            elif player.role == PlayerRole.BEATER and player.id in self.defence_cpu_player_ids and player.id not in assigned_beater_ids:
                self.beater_move_action(dt, player, volleyball)
                self.beater_throw_action(player, volleyball)
        self.chasers_action(sorted_hoop_distances, chaser_hoop_squared_distances, volleyball, dt)

    def beater_move_action(self, dt: float, beater: Player, volleyball: VolleyBall):
        """
        if loaded beater:
            Move beaters to center hoop and directing them with evade and -evade vectors (the closer the more impactful).
            
            Then check if beater should throw
        """
        
        move_vector = Vector2(
            self.center_hoop.position.x - beater.position.x,
            self.center_hoop.position.y - beater.position.y
        )
        move_vector_mag = UtilityLogic._magnitude(move_vector)
        if move_vector_mag == 0:
            move_vector = Vector2(0, 0)
        else:
            move_vector = Vector2(
                move_vector.x / move_vector_mag,
                move_vector.y / move_vector_mag
            )
        evade_vectors = []
        for beater_buddy in self.defence_beaters:
            # if loaded beater buddy
            if beater_buddy.id != beater.id and beater_buddy.has_ball:
                # use lookout to reduce oscillations around hoop
                # but leads to rotation around center hoop
                # lookout_beater_position = self.logic.basic_logic.get_update_position(beater, dt)
                # lookout_beater_buddy_position = self.logic.basic_logic.get_update_position(beater_buddy, dt)
                # evade_vectors.append(MoveUtility.evade(lookout_beater_position, lookout_beater_buddy_position, weight=self.beater_evade_beater_buddy_weight))
                evade_vectors.append(MoveUtility.evade(beater.position, beater_buddy.position, weight=self.beater_evade_beater_buddy_weight))

        if beater.has_ball: # loaded beater
            for opponent in self.attack_players:
                if opponent.role in [PlayerRole.CHASER, PlayerRole.KEEPER]:
                    # negative weight
                    evade_vectors.append(MoveUtility.evade(beater.position, opponent.position, weight=self.beater_evade_chaser_keeper_weight))
                elif opponent.role == PlayerRole.BEATER:
                    evade_vectors.append(MoveUtility.evade(beater.position, opponent.position, weight=self.loaded_beater_evade_beater_weight))
            # negative weight to volleyball
            evade_vectors.append(MoveUtility.evade(beater.position, volleyball.position, weight=self.beater_evade_volleyball_weight))
        else: # unloaded beater
            # try to make contact with opponent beater if not x position to close to midline
            x_to_midline = abs(beater.position.x - self.logic.state.midline_x)
            if x_to_midline > self.unloaded_beater_max_x_to_midline:
                for opponent in self.attack_players:
                    if opponent.role == PlayerRole.BEATER:
                        # negative weight
                        evade_vectors.append(MoveUtility.evade(beater.position, opponent.position, weight=self.unloaded_beater_evade_beater_weight))
                self.logic.process_action_logic.process_tackle_action(beater.id) # unloaded beaters try to make contact with other close opponent beaters
        for evade_vector in evade_vectors:
            move_vector.x += evade_vector.x
            move_vector.y += evade_vector.y
        move_vector = MoveUtility.adjust_move_vector_to_avoid_boundary(
        beater.position,
        move_vector,
        boundary_x_min = self.logic.state.boundaries_x[0],
        boundary_x_max = self.logic.state.boundaries_x[1],
        boundary_y_min = self.logic.state.boundaries_y[0],
        boundary_y_max = self.logic.state.boundaries_y[1],
        buffer = self.positioning_boundary_buffer_distance
        )
        beater.direction = move_vector
    
    def beater_throw_action(self, beater: Player, volleyball: VolleyBall):
        if not beater.has_ball:
            return
        if volleyball.holder_id is not None:
            volleyball_holder = self.logic.state.players[volleyball.holder_id]
            if self.beater_throw_decider.should_throw_at_volleyball_holder(beater, volleyball_holder):
                throw_direction = ThrowDirector.get_throw_direction_moving_receiver(beater, volleyball_holder)
                self.logic.process_action_logic.process_throw_action(beater.id, throw_direction)               

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
                        next_chaser_position_x, next_chaser_position_y = self.logic.basic_logic.get_update_position(chaser, dt)
                        next_volleyball_position_x, next_volleyball_position_y = self.logic.basic_logic.get_update_position(volleyball, dt)
                        if next_volleyball_position_x > target_hoop.position.x:
                            target_position = Vector2(target_hoop.position.x + add_hoop_blockage_x, target_hoop.position.y)
                            # direction_to_hoop = Vector2(
                            #     (target_hoop.position.x + add_hoop_blockage_x) - chaser.position.x,
                            #     target_hoop.position.y - chaser.position.y
                            # )
                            next_direction_to_hoop = Vector2(
                                (target_hoop.position.x + add_hoop_blockage_x) - next_chaser_position_x,
                                target_hoop.position.y - next_chaser_position_y
                            )
                            # x_pos_position = True
                        else:
                            target_position = Vector2(target_hoop.position.x - add_hoop_blockage_x, target_hoop.position.y)
                            # direction_to_hoop = Vector2(
                            #     (target_hoop.position.x - add_hoop_blockage_x) - chaser.position.x,
                            #     target_hoop.position.y - chaser.position.y
                            # )
                            next_direction_to_hoop = Vector2(
                                (target_hoop.position.x - add_hoop_blockage_x) - next_chaser_position_x,
                                target_hoop.position.y - next_chaser_position_y
                            )
                            # x_pos_position = False
                        #         x_pos_position = False
                        # print('direction to hoop: ', direction_to_hoop)
        
                        # print('player direction', chaser.direction)
                        # print('player velocity', chaser.velocity)
                        # print(f'[CPU Player] Moving chaser {chaser_id} towards hoop {hoop_id} with direction {chaser.direction}')
                        chaser.direction = self.move_around_hoop_blockage(
                            player=chaser,
                            target_position=target_position,
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
            if self.defence_team == self.logic.state.team_0:
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