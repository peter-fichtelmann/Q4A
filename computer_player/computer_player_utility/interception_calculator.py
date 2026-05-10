import math
from typing import Dict, Optional, List, Tuple

from core.entities import Vector2
from core.game_logic.utility_logic import UtilityLogic
from core.game_logic.game_logic import GameLogic

class InterceptionCalculator:
    """
    This class implements methods to calculate if players can intercept a moving entity.

    It is the successor of the legacy method where interception was estimated
    more exactly via expensive step simulations.

    This class provides methods that are less accurate but much faster.

    There are 2 approaches:
    1) beam angle estimation:
        Assumes the moving entity is much faster than the players and thus a ball.
        Assumes a linear beam from the moving entity in the moving entity's velocity.
        Assumes the moving entity and players move with constant velocity.
        Calculates the angle between the moving entity's velocity and the moving entity-player positions.
        If the angle is small enough, the player is in the beam and can potentially intercept.
    2) line interception:
        Assumes moving entity and players move with constant speed (max speed for players).
        In contrast to 1), the players can be faster.
        Sympy solved a linear equation system to find the player's velocity direction to intercept optimally and the time needed.
        It resulted in a long term, but is still quite fast to solve.
    """
    def __init__(self, logic: GameLogic):
        """Keep a reference to game state for player kinematics and lookups."""
        self.logic = logic
    
    def beam_cosine_angle(self,
                moving_entity: object,
                intercepting_player_ids: List[str],
                target_position: Optional[Vector2] = None, # not needed if is in front target is False
                moving_entity_target_vector: Optional[Vector2] = None,
                is_in_front_target: bool = True
                ) -> Tuple[float, Dict[str, float]]:
        """
        Calculate the beam cosine angle as dot products of the normed moving_entity-target vector to the normed moving_entity-player vectors.
        If dot product close to 1 enough then part of beam and interception likely.

        if is_in_front_target
        1) Calculate dot product between player_target_vector and moving_entity_target_vector.
        If 0 or positive -> similar directions and thus in front of target (closer to moving_entity)

        2) Calculate dot product between moving_entity_player_vector and moving_entity_target_vector
        The vectors are normalized, so the dot product directly corresponds to the beam angle.


        Does not take velocities into account at the moment.

        Returns the best cosine score, the corresponding player id, and a
        dictionary mapping player ids to cosine scores.
        """
        if target_position is None and is_in_front_target:
            raise ValueError("target_position must be provided if is_in_front_target is True")
        # add case handling: target_position is None
        if moving_entity_target_vector is None:
            moving_entity_target_vector = Vector2(
                target_position.x - moving_entity.position.x,
                target_position.y - moving_entity.position.y
            )
        mag_moving_entity_target_vector = UtilityLogic._magnitude(moving_entity_target_vector)
        moving_entity_target_vector.x /= mag_moving_entity_target_vector
        moving_entity_target_vector.y /= mag_moving_entity_target_vector
        max_dot_product = 0
        max_dot_product_player_id = None
        beam_angle_player_dict = {}
        for player_id in intercepting_player_ids:
            player = self.logic.state.players[player_id]
            if player.is_knocked_out:
                # TODO Take knocked out players into account, when they close enough center hoop
                continue
            if is_in_front_target:
                # check if player is not behind target
                player_target_vector_x = target_position.x - player.position.x
                player_target_vector_y = target_position.y - player.position.y
                dot_product_player_target = player_target_vector_x * moving_entity_target_vector.x + player_target_vector_y * moving_entity_target_vector.y
                # orthogonal or in front of target
                if dot_product_player_target < 0:
                    # TODO Allow if distance player-target close enough
                    continue
            moving_entity_player_vector_x = player.position.x - moving_entity.position.x
            moving_entity_player_vector_y = player.position.y - moving_entity.position.y
            mag_moving_entity_player_vector = UtilityLogic._magnitude_without_vector(
                moving_entity_player_vector_x,
                moving_entity_player_vector_y
            )
            moving_entity_player_vector_x /= mag_moving_entity_player_vector
            moving_entity_player_vector_y /= mag_moving_entity_player_vector
            dot_product = moving_entity_target_vector.x * moving_entity_player_vector_x + moving_entity_target_vector.y * moving_entity_player_vector_y
            
            
            if dot_product > max_dot_product:
                max_dot_product = dot_product
                max_dot_product_player_id = player.id
            beam_angle_player_dict[player.id] = dot_product
        return max_dot_product, max_dot_product_player_id, beam_angle_player_dict
    
    def interception_score_from_beam_cosine_angle(self,
                                                  beam_cosine_angle: float,
                                                  beam_angle_player_id: str,
                                                #   squared_moving_entity_target_distance: float,
                                                  mag_moving_entity_velocity: float,
                                                  
                                                  ) -> float:
        """
        Assume a rectangular triangle between moving_entity, target and player with maximum distance to intercept.
        
        cos(angle) = s_t / hypotenuse = s_t / (s_p^2 + s_t^2)^0.5 where s_p is the distance to player and s_t is the distance to target.

        Assuming constant moving_entity and max player velocity, s_p = s_t * v_p / v_e where v_p is player velocity and v_e is moving entity velocity.

        So calculating with squared distances to avoid square root:

        cos(angle)^2 = (s_t^2) / (s_t^2 * v_p^2 / v_e^2 + s_t^2) = 1 / (v_p^2 / v_e^2 + 1)

        Large cosine means small angle.

        The larger the score, the less likely the interception.

        """
        if beam_cosine_angle == 0:
            # no interception
            return 1
        # TODO incorporate individual player velocity also regarding current velocity direction
        mag_player_velocity = self.logic.state.players[beam_angle_player_id].max_speed
        squared_cosine_angle = mag_moving_entity_velocity**2 / (mag_player_velocity**2 + mag_moving_entity_velocity**2 + 1e-6)
        cosine_angle = math.sqrt(squared_cosine_angle)
        interception_score = (1 - beam_cosine_angle) / (1 - cosine_angle + 1e-6) 
        # self.logger.debug('cosine_angle: %s, beam_cosine_angle: %s, interception_score: %s', cosine_angle, beam_cosine_angle, interception_score)
        return interception_score
    

    def line_interception(self,
                          moving_entity: object,
                          intercepting_player_ids: List[str],
                          ) -> Tuple[float, str, Vector2, Dict[str, float|Vector2]]:
        """
        Check the line from moving_entity to target_position for intercepting with players in intercepting_player_ids.
        Estimate interception time for each candidate player.

        Returns the lowest interception time, the selected player id, and a
        dictionary of per-player interception times.
        """
        lowest_interception_dt = float('inf')
        lowest_interception_dt_player_id = None
        interception_info_dict = {}
        for player_id in intercepting_player_ids:
            player = self.logic.state.players[player_id]
            penalty_time = 0.0
            player_position_x = player.position.x
            player_position_y = player.position.y
            if player.is_knocked_out:
                # Take estimated knocked time for knocked out players to recover into account
                dx = self.logic.state.hoops[f'hoop_{player.team}_center'].position.x - player.position.x
                dy = self.logic.state.hoops[f'hoop_{player.team}_center'].position.y - player.position.y
                distance_to_own_hoop = UtilityLogic._magnitude_without_vector(dx, dy)
                penalty_time = distance_to_own_hoop / player.max_speed
                # use hoop position as player position
                player_position_x = self.logic.state.hoops[f'hoop_{player.team}_center'].position.x
                player_position_y = self.logic.state.hoops[f'hoop_{player.team}_center'].position.y
            interception_time = self.get_interception_time(
                player_position_x=player_position_x,
                player_position_y=player_position_y,
                moving_entity_position_x=moving_entity.position.x,
                moving_entity_position_y=moving_entity.position.y,
                moving_entity_velocity_x=moving_entity.velocity.x,
                moving_entity_velocity_y=moving_entity.velocity.y,
                player_max_speed=player.max_speed
            )
            if interception_time == float('inf'):
                continue
            interception_time += penalty_time
            if interception_time < lowest_interception_dt:
                lowest_interception_dt = interception_time
                lowest_interception_dt_player_id = player_id
            # interception_position = Vector2(
            #     moving_entity.position.x + moving_entity.velocity.x * interception_time,
            #     moving_entity.position.y + moving_entity.velocity.y * interception_time
            # )
            interception_info_dict[player_id] = interception_time


            # self.logger.debug(f"Player {player_id} has interception time {interception_time}")
        # interception_position = Vector2(
        #     moving_entity.position.x + moving_entity.velocity.x * lowest_interception_dt,
        #     moving_entity.position.y + moving_entity.velocity.y * lowest_interception_dt
        # )
        # self.logger.debug(f"Lowest interception time is {lowest_interception_dt} by player {lowest_interception_dt_player_id} at position ({interception_position.x}, {interception_position.y})")
        return lowest_interception_dt, lowest_interception_dt_player_id, interception_info_dict

    @staticmethod
    def get_interception_time(
        player_position_x: float,
        player_position_y: float,
        moving_entity_position_x: float,
        moving_entity_position_y: float,
        moving_entity_velocity_x: float,
        moving_entity_velocity_y: float,
        player_max_speed: float
        ) -> float:
        """
        Similiar to get_throw_direction_moving_receiver but instead of throwin ball, throwing yourself with max_speed

        Assumes the moving entity has constant velocity and the intercepting
        player can instantly move at max speed.

        Used first solution via sympy solve:

        import sympy as sp

            v_b_x, v_b_y = sp.symbols('v_b_x v_b_y', real=True, imaginary=False)
            z = sp.symbols('z', positive=True, real=True, imaginary=False)
            s_b_x, s_b_y, s_p_x, s_p_y = sp.symbols('s_b_x s_b_y s_p_x s_p_y', constant=True, real=True, nonnegative=True, imaginary=False)
            v_p_x, v_p_y = sp.symbols('v_p_x v_p_y', constant=True, real=True, imaginary=False)
            v_b_value_sq = sp.symbols('v_b_value_sq', constant=True, positive=True, real=True, imaginary=False)
            # Your example system
            eq1 = (s_b_x - s_p_x) + (v_b_x - v_p_x) * dt
            eq2 = (s_b_y - s_p_y) + (v_b_y - v_p_y) * dt
            eq3 = v_b_x**2 + v_b_y**2 - v_b_value_sq

            solutions = sp.nonlinsolve([eq1, eq2, eq3], (v_b_x, v_b_y, dt))
        """
        # assume ball starts at player position
        s_b_x = player_position_x
        s_b_y = player_position_y
        s_p_x = moving_entity_position_x
        s_p_y = moving_entity_position_y
        v_p_x = moving_entity_velocity_x
        v_p_y = moving_entity_velocity_y
        v_b_value_sq = player_max_speed**2
        # print('s_b_x', s_b_x)
        # print('s_b_y', s_b_y)
        # print('s_p_x', s_p_x)
        # print('s_p_y', s_p_y)
        # print('v_p_x', v_p_x)
        # print('v_p_y', v_p_y)
        # print('v_b_value_sq', v_b_value_sq)
        inner_root = s_b_x**2*v_b_value_sq - s_b_x**2*v_p_y**2 + 2*s_b_x*s_b_y*v_p_x*v_p_y - 2*s_b_x*s_p_x*v_b_value_sq + 2*s_b_x*s_p_x*v_p_y**2 - 2*s_b_x*s_p_y*v_p_x*v_p_y + s_b_y**2*v_b_value_sq - s_b_y**2*v_p_x**2 - 2*s_b_y*s_p_x*v_p_x*v_p_y - 2*s_b_y*s_p_y*v_b_value_sq + 2*s_b_y*s_p_y*v_p_x**2 + s_p_x**2*v_b_value_sq - s_p_x**2*v_p_y**2 + 2*s_p_x*s_p_y*v_p_x*v_p_y + s_p_y**2*v_b_value_sq - s_p_y**2*v_p_x**2
        divider = (v_b_value_sq - v_p_x**2 - v_p_y**2)
        if inner_root >= 0 and divider != 0:
            root = math.sqrt(inner_root)
            inverse_divider = 1 / divider
            # v_b_x = (-s_b_x*s_b_y*v_p_y + s_b_x*s_p_y*v_p_y - s_b_x*root + s_b_y**2*v_p_x + s_b_y*s_p_x*v_p_y - 2*s_b_y*s_p_y*v_p_x - s_p_x*s_p_y*v_p_y + s_p_x*root + s_p_y**2*v_p_x)/(s_b_x**2 - 2*s_b_x*s_p_x + s_b_y**2 - 2*s_b_y*s_p_y + s_p_x**2 + s_p_y**2) 
            # v_b_y = (s_b_x**2*v_p_y - s_b_x*s_b_y*v_p_x - 2*s_b_x*s_p_x*v_p_y + s_b_x*s_p_y*v_p_x + s_b_y*s_p_x*v_p_x - s_b_y*root + s_p_x**2*v_p_y - s_p_x*s_p_y*v_p_x + s_p_y*root)/(s_b_x**2 - 2*s_b_x*s_p_x + s_b_y**2 - 2*s_b_y*s_p_y + s_p_x**2 + s_p_y**2)
            dt = -(s_b_x*v_p_x + s_b_y*v_p_y - s_p_x*v_p_x - s_p_y*v_p_y)*inverse_divider + root*inverse_divider
            if dt < 0:
                dt = float('inf')
                # raise ValueError(f"Negative interception time, no valid interception with: \n s_b_x {player_position_x}, s_b_y {player_position_y}, s_p_x {moving_entity_position_x}, s_p_y {moving_entity_position_y}, v_p_x {moving_entity_velocity_x}, v_p_y {moving_entity_velocity_y}, player_max_speed {player_max_speed}")        
        else:
            # no intercept, ball to fast
            dt = float('inf')
        return dt
        # print('v_b_x', v_b_x)
        # print('v_b_y', v_b_y)
