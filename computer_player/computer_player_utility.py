
import logging
import math
from typing import Dict, Optional, List, Tuple

from core.entities import DodgeBall, Player, PlayerRole, Vector2, Hoop
from core.game_logic.game_logic import GameLogic
from core.game_logic.utility_logic import UtilityLogic

class MoveAroundHoopBlockage:
    def __init__(self,
                 defence_hoops: List[Hoop],
                 move_buffer_factor: float = 1.2,
                 tol: float = 1e-2,
                 volleyball_radius: float = 0.0, # for hoop blockage_x
                 logger: Optional[logging.Logger] = None
                 ):
        self.defence_hoops = defence_hoops
        self.move_buffer_factor = move_buffer_factor    
        self.tol = tol
        self.volleyball_radius = volleyball_radius
        self.logger = logger

    def __call__(self,
                 player: Player,
                 target_position: Vector2,
                 target_hoop: Optional[Hoop] = None,
                 add_hoop_blockage_x: Optional[float] = None,
                 lookahead_to_target: Optional[Vector2] = None,
                 add_target_x_buffer: bool = False
                 ) -> Vector2:
        """Compute a movement vector that steers a defender around hoop blockage.

        The method traces the straight segment from ``player.position`` to ``target``
        and checks whether it intersects hoop blockage boundaries. If a blocking
        intercepting is detected, it redirects movement toward a buffered hoop corner;
        otherwise it returns direct movement toward the target (or ``lookahead_to_target``
        when provided).

        It is assumed the hoops have all the same orientation and x-value: radius along the y-axis (perpendicular x-axis). Hoop rotation is not implemented.

        Args:
            player: Defender whose movement is being computed.
            target: Desired point to move toward for this frame.
            target_hoop: Primary hoop used for x-side intercepting checks and side
                determination.
            add_hoop_blockage_x: Horizontal half-width of hoop blockage for collision
                avoidance (for example, player radius plus ball radius).
            lookahead_to_target: Optional precomputed direction vector to use when no
                blockage is found (typically a velocity-aware lookahead).
            add_target_x_buffer: When ``True`` and no blockage is found, applies an
                additional x-buffer offset to the returned direct direction.

        Returns:
            Vector2: The direction vector the caller should use for movement this
            frame. A zero vector is returned when ``target`` equals
            ``player.position``.
        """
        direction_to_target = Vector2(
            target_position.x - player.position.x,
            target_position.y - player.position.y
            )
        if target_hoop is None:
            # take first defending hoop
            target_hoop = self.defence_hoops[0]
        if add_hoop_blockage_x is None:
            add_hoop_blockage_x = self.volleyball_radius + player.radius

        # min_dir and min_velocity of players can make it difficult to go around hoops
        if direction_to_target.x == 0 and direction_to_target.y == 0:
            # no movement needed, already at the hoop, so no blockage
            return Vector2(0, 0)
        x_pos_position = target_hoop.position.x < target_position.x # True if target is on right side of hoop
        # hoop width: hoop.radius
        # hoop thickness: player.radius + ball.radius
        # player will not be blocked by hoop line where the target point is
        hoop_blockage_x_pos = target_hoop.position.x + add_hoop_blockage_x
        hoop_blockage_x_neg = target_hoop.position.x - add_hoop_blockage_x
        if x_pos_position:
            hoop_blockage_x = hoop_blockage_x_neg
            add_x_buffer = - add_hoop_blockage_x * (self.move_buffer_factor - 1)
        else:
            hoop_blockage_x = hoop_blockage_x_pos
            add_x_buffer = add_hoop_blockage_x * (self.move_buffer_factor - 1)
        best_x_intercepting  = (float('inf'), None, None, None) # (t, x, y, hoop)
        best_y_intercepting = (float('inf'), None, None, None) # (t, x, y, hoop)
        # only calculate interceptings if target is on the opposite side of the hoop from the player, otherwise there is no blockage to worry about (player can move around the hoop without intercepting any blockage boundaries)
        if not ((player.position.x > hoop_blockage_x_pos and target_position.x > hoop_blockage_x_pos) or
            (player.position.x < hoop_blockage_x_neg and target_position.x < hoop_blockage_x_neg)
            ):
            # check x intercepting
            line_t_x = (hoop_blockage_x - player.position.x) / direction_to_target.x if direction_to_target.x != 0 else float('inf')
            if line_t_x > 0 - self.tol and line_t_x < 1 + self.tol:
                check_y_at_line_t_x = player.position.y + direction_to_target.y * line_t_x
                # check for all hoops if intercepting at line_t_x is within blockage range of the hoop (only check hoops on the way to target)
                for hoop in self.defence_hoops:
                    if (check_y_at_line_t_x >= hoop.position.y - hoop.radius and check_y_at_line_t_x <= hoop.position.y + add_hoop_blockage_x):
                        best_x_intercepting = (line_t_x, hoop_blockage_x + add_x_buffer, check_y_at_line_t_x, hoop)
                        break
            # check all possible y interceptings
            for hoop in self.defence_hoops:
                for add_hoop_blockage_radius in [hoop.radius, - hoop.radius]:
                    y = hoop.position.y + add_hoop_blockage_radius
                    line_t_y = (y - player.position.y) / direction_to_target.y if direction_to_target.y != 0 else float('inf')
                    if line_t_y > 0 - self.tol and line_t_y < 1 + self. tol:
                        x = player.position.x + direction_to_target.x * line_t_y
                        if (x >= hoop.position.x - add_hoop_blockage_x and x <= hoop.position.x + add_hoop_blockage_x):
                            if line_t_y < best_y_intercepting[0]:
                                y = hoop.position.y + add_hoop_blockage_radius * self.move_buffer_factor # add buffer after checks (before checks leads to wrong checks)
                                best_y_intercepting = (line_t_y, x, y, hoop)
        if math.isinf(best_x_intercepting[0]) and math.isinf(best_y_intercepting[0]):
            # no blockage found, move directly towards the hoop with estimation of current velocity taken into account
            if lookahead_to_target is not None:
                direction = lookahead_to_target
            else:
                direction = direction_to_target
            if add_target_x_buffer:
                # add buffer
                direction.x -= add_x_buffer # inverse to add buffer
        elif best_x_intercepting[0] < best_y_intercepting[0]:
            # use best x intercepting
            # check closest corner of the hoop where the player should move towards with buffer to avoid blockage
            if direction_to_target.y < 0: # move towards upper corner
                corner_y = best_x_intercepting[3].position.y + best_x_intercepting[3].radius * self.move_buffer_factor
            else: # move towards lower corner
                corner_y = best_x_intercepting[3].position.y - best_x_intercepting[3].radius * self.move_buffer_factor
            direction = Vector2(best_x_intercepting[1] - player.position.x, corner_y - player.position.y)
        else: # best y_intercepting is closer
            if x_pos_position:
                corner_x = best_y_intercepting[3].position.x + add_hoop_blockage_x * self.move_buffer_factor
            else:
                corner_x = best_y_intercepting[3].position.x - add_hoop_blockage_x * self.move_buffer_factor
            direction = Vector2(corner_x - player.position.x, best_y_intercepting[2] - player.position.y)
        return direction
    

class InterceptionRatioCalculator:
    def __init__(self,
                    logic: GameLogic,
                    move_around_hoop_blockage: MoveAroundHoopBlockage,
                    tol_reaching_target: float = 0,
                    log_level: int = None,
                    logger: Optional[logging.Logger] = None
                    ):
        self.logic = logic
        self.move_around_hoop_blockage = move_around_hoop_blockage
        self.tol_reaching_target = tol_reaching_target
        self.log_level = log_level
        self.logger = logger

    def update_moving_free_ball_position(self, copy_moving_entity: object, dt: float):
        copy_moving_entity.velocity.x, copy_moving_entity.velocity.y = self.logic.basic_logic.get_free_ball_velocity(copy_moving_entity, dt)
        copy_moving_entity.position.x, copy_moving_entity.position.y = self.logic.basic_logic.get_update_position(copy_moving_entity, dt)

    def update_moving_player_position(self, copy_moving_entity: Player, dt: float):
        self.logic.basic_logic.update_player_velocity(copy_moving_entity, dt)
        copy_moving_entity.position.x, copy_moving_entity.position.y = self.logic.basic_logic.get_update_position(copy_moving_entity, dt)

    def get_dt_stepsize(self, copy_moving_entity: object, max_distance_per_step: Optional[float], max_dt_per_step: Optional[int]) -> float:
        dt = max_distance_per_step / (UtilityLogic._magnitude(copy_moving_entity.velocity) + 1e-6) if max_distance_per_step is not None else 0.1
        if max_dt_per_step is not None and dt > max_dt_per_step:
            dt = max_dt_per_step
        return dt
    
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

        Returns player with smallest beam angle (highest dot product) and dict of player ids: dot products
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

        The larger the score, the less likey the interception.

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
        Calculate the interception time. 
        Return the player with the lowest interception time.
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
                player_position_x = self.state.hoops[f'hoop_{player.team}_center'].position.x
                player_position_y = self.state.hoops[f'hoop_{player.team}_center'].position.y
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
            interception_position = Vector2(
                moving_entity.position.x + moving_entity.velocity.x * interception_time,
                moving_entity.position.y + moving_entity.velocity.y * interception_time
            )
            interception_info_dict[player_id] = (interception_time, interception_position)


            # self.logger.debug(f"Player {player_id} has interception time {interception_time}")
        interception_position = Vector2(
            moving_entity.position.x + moving_entity.velocity.x * lowest_interception_dt,
            moving_entity.position.y + moving_entity.velocity.y * lowest_interception_dt
        )
        self.logger.debug(f"Lowest interception time is {lowest_interception_dt} by player {lowest_interception_dt_player_id} at position ({interception_position.x}, {interception_position.y})")
        return lowest_interception_dt, lowest_interception_dt_player_id, interception_position, interception_info_dict

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

        Assume constant ball velocity. Assume player starts with max speed.

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


    def __call__(self,
                    dt: float,
                    moving_entity: object,
                    intercepting_player_ids: List[str],
                    max_dt_steps: int, # calculalation complexity increases with max_dt_steps*(max_dt_steps + 1) / 2 (triangular number)
                    target_position: Optional[Vector2] = None,
                    only_first_intercepting: bool = True,
                    max_distance_per_step: Optional[float] = None,
                    max_dt_per_step: Optional[int] = None
                    ) -> Tuple[float, Dict[str, Tuple[int, float, Vector2]]]:
        """
        Check the line from moving_entity to target_position for intercepting with players in intercepting_player_ids.
        Return a intercepting score between 0 and 1, where 0 means intercepting at the beginning of the line and 1 means no intercepting and reaching the target.
        In addition, return a dictionary of the best step ratio of intercepting players with the step number and the corresponding step ratio and interception position.
        """
        if isinstance(moving_entity, Player):
            update_moving_entity_position = self.update_moving_player_position
        else:
            update_moving_entity_position = self.update_moving_free_ball_position
        # check if moving_entity will reach target position within max_dt_steps
        copy_moving_entity = moving_entity.copy()
        can_reach_target = False
        updated_max_dt_steps = max_dt_steps
        updated_moving_entity_positions = []
        # updated_moving_entity_velocities = []
        dt_steps = []
        if target_position is None:
            # set to end position after max_dt_steps if no target position provided
            for steps in range(max_dt_steps):
                dt = self.get_dt_stepsize(copy_moving_entity, max_distance_per_step, max_dt_per_step)
                dt_steps.append(dt)
                update_moving_entity_position(copy_moving_entity, dt) # assume fixed dt of 0.1 for each step
                updated_moving_entity_positions.append(copy_moving_entity.position.copy())
            can_reach_target = True
            target_position = copy_moving_entity.position
        else:
            previous_len_moving_entity_target = float('inf')
            for steps in range(max_dt_steps):
                dt = self.get_dt_stepsize(copy_moving_entity, max_distance_per_step, max_dt_per_step)
                dt_steps.append(dt)
                update_moving_entity_position(copy_moving_entity, dt) # assume fixed dt of 0.1 for each step
                updated_moving_entity_positions.append(copy_moving_entity.position.copy())
                # updated_moving_entity_velocities.append(copy_moving_entity.velocity.copy())
                # check if reached target position
                len_moving_entity_target = UtilityLogic._distance(copy_moving_entity.position, target_position)
                if len_moving_entity_target > previous_len_moving_entity_target:
                    can_reach_target = True
                    if steps == 0:
                        updated_max_dt_steps = 1 # if already at target position, just check for intercepting at the current position without updating moving entity position
                    updated_max_dt_steps = steps - 1 # if can reach target then check for line intercepting at each step until reaching target (instead of max_dt_steps)
                    break
                previous_len_moving_entity_target = len_moving_entity_target
            # self.logger.debug(f"Updated moving entity positions for interception ratio calculation: {[f'({pos.x:.2f}, {pos.y:.2f})' for pos in updated_moving_entity_positions]}")
            # self.logger.debug(f"dt steps {dt_steps}")
            # self.logger.debug(f"Updated moving entity velocities for interception ratio calculation: {[f'({vel.x:.2f}, {vel.y:.2f})' for vel in updated_moving_entity_velocities]}")
        if can_reach_target:
            step_ratio_dict = {}
            for steps in range(updated_max_dt_steps):
                copy_logic = self.logic.copy(log_level=self.log_level)
                intercepting_players = [copy_logic.state.players[player_id] for player_id in intercepting_player_ids]
                step_ratio = 1
                # self.logger.debug(f"Steps {steps} for interception ratio calculation: moving entity position ({copy_moving_entity.position.x:.2f}, {copy_moving_entity.position.y:.2f}), intercepting player positions: {[f'{player.id}: ({player.position.x:.2f}, {player.position.y:.2f})' for player in intercepting_players]}")
                for step in range(steps + 1):
                    for intercepting_player in intercepting_players:
                        if not intercepting_player.is_knocked_out:
                            if intercepting_player.role in [PlayerRole.CHASER, PlayerRole.KEEPER]:
                                intercepting_player.direction = self.move_around_hoop_blockage(
                                    player=intercepting_player,
                                    target_position=updated_moving_entity_positions[steps],
                                    target_hoop=self.move_around_hoop_blockage.defence_hoops[0], # assume hoops same x position and orientation so can use any as target hoop 
                                    lookahead_to_target=None,
                                    add_target_x_buffer=False
                                )
                            else:
                                intercepting_player.direction = Vector2(
                                    target_position.x - updated_moving_entity_positions[steps].x,
                                    target_position.y - updated_moving_entity_positions[steps].y
                                    )
                    dt_update = dt_steps[step]
                    copy_logic.basic_logic.update_player_velocities(dt_update)
                    copy_logic.basic_logic.update_positions(dt_update)
                    squared_distance_dict = {}
                    for intercepting_player in intercepting_players:
                        if not intercepting_player.is_knocked_out:
                            squared_distance_dict[intercepting_player.id] = UtilityLogic._squared_distance(intercepting_player.position, updated_moving_entity_positions[steps])
                    sorted_squared_distance = sorted(squared_distance_dict.items(), key=lambda item: item[1])
                    # check if an intercepting player crosses the line to target position within steps
                    for other_id, distance in sorted_squared_distance:
                        if other_id in intercepting_player_ids:
                            player = copy_logic.state.players[other_id]
                            if not player.is_knocked_out:
                                if distance <= UtilityLogic._squared_sum(player.radius, moving_entity.radius):
                                    step_ratio = steps / (steps + 1)
                                    # self.logger.debug(f"intercepting detected at step {step} with player {other_id} at distance {math.sqrt(distance)} and step ratio {step_ratio}")
                                    if only_first_intercepting:
                                        return step_ratio, {other_id: (step, step_ratio, updated_moving_entity_positions[step])}
                                    stored_step_ratio = step_ratio_dict.get(other_id, (float('inf'), 1, None)) # (step, step_ratio, position)
                                    if step_ratio < stored_step_ratio[1]: # stored_step_ratio is a tuple (step, step_ratio, position)
                                        step_ratio_dict[other_id] = (step, step_ratio, updated_moving_entity_positions[step])
                                    break
                    # if any intercepting
                    if step_ratio < 1:
                        # print(f"Breaking out of steps loop to check next step ratio if not only_first_intercepting")
                        break
            if len(step_ratio_dict) > 0:
                intercepting_score = 1
                for _, step_ratio, _ in step_ratio_dict.values():
                    intercepting_score = step_ratio * intercepting_score # combine step ratios for multiple intercepting players
                return intercepting_score, step_ratio_dict
            else:
                return 1, {} # no intercepting, reached target
        # not reaching target
        # print(f"Not reaching target within {max_dt_steps} steps, returning intercepting score of 0")
        return 0, {}
    

class MoveUtility:
    @staticmethod
    def evade(player_position: Vector2, entity_to_evade_position: Vector2, weight: float = 1.0) -> Vector2:
        """Evade player, e.g. chaser or loaded beater. Return evade vector"""
        player_to_entity_vector = Vector2(
            entity_to_evade_position.x - player_position.x,
            entity_to_evade_position.y - player_position.y
        )
        squared_mag_player_to_entity_vector = UtilityLogic._squared_sum(player_to_entity_vector.x, player_to_entity_vector.y)
        if squared_mag_player_to_entity_vector == 0:
            return Vector2(0, 0)
        evade_vector = Vector2(
            -player_to_entity_vector.x * weight / squared_mag_player_to_entity_vector, # norm to one and then divide by distance to entity to get stronger evasion when closer
            -player_to_entity_vector.y * weight / squared_mag_player_to_entity_vector
        )
        return evade_vector

    @staticmethod
    def adjust_move_vector_to_avoid_boundary(
            player_position: Vector2,
            move_vector: Vector2,
            boundary_x_min: float,
            boundary_x_max: float,
            boundary_y_min: float,
            boundary_y_max: float,
            buffer: float
            ):
        """Avoid movement that would move player outside of boundaries. Return adjusted move vector."""
        if player_position.x < boundary_x_min + buffer:
            move_vector.x = max(0, move_vector.x) # only allow movement to the right
        elif player_position.x > boundary_x_max - buffer:
            move_vector.x = min(0, move_vector.x) # only allow movement to the left
        if player_position.y < boundary_y_min + buffer:
            move_vector.y = max(0, move_vector.y) # only allow movement downwards
        elif player_position.y > boundary_y_max - buffer:
            move_vector.y = min(0, move_vector.y) # only allow movement upwards
        return move_vector


class BeaterThrowDecider:
    """
    Makes decisions if beaters should throw their dodogeball.
    
    Idea 1: just hard distance threshold
    Idea 2: hard threshold and probabilty per second of 1/(distance + value) where value is aggressiveness
    
    """
    def __init__(
            self,
            throw_threshold_volleyball_holder: float
            ):
        self.squared_throw_threshold_volleyball_holder = throw_threshold_volleyball_holder**2

    def should_throw_at_volleyball_holder(self, beater: Player, volleyball_holder: Player) -> bool:
        squared_distance = UtilityLogic._squared_distance(beater.position, volleyball_holder.position)
        if squared_distance <= self.squared_throw_threshold_volleyball_holder:
            return True
        return False
    

class ThrowDirector:
    """Calculates the throw vector to a moving receiver e.g. for passes and beats"""
    @staticmethod
    def get_throw_direction_static_receiver(player: Player, receiver: Player):
        return  Vector2(
            receiver.position.x - player.position.x,
            receiver.position.y - player.position.y
        )

    @staticmethod
    def get_throw_direction_moving_receiver(player: Player, receiver: Player):
        """
        Assume constant ball velocity.

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
        s_b_x = player.position.x
        s_b_y = player.position.y
        s_p_x = receiver.position.x
        s_p_y = receiver.position.y
        v_p_x = receiver.velocity.x
        v_p_y = receiver.velocity.y
        v_b_value_sq = player.throw_velocity**2
        # print('s_b_x', s_b_x)
        # print('s_b_y', s_b_y)
        # print('s_p_x', s_p_x)
        # print('s_p_y', s_p_y)
        # print('v_p_x', v_p_x)
        # print('v_p_y', v_p_y)
        # print('v_b_value_sq', v_b_value_sq)
        root = math.sqrt(s_b_x**2*v_b_value_sq - s_b_x**2*v_p_y**2 + 2*s_b_x*s_b_y*v_p_x*v_p_y - 2*s_b_x*s_p_x*v_b_value_sq + 2*s_b_x*s_p_x*v_p_y**2 - 2*s_b_x*s_p_y*v_p_x*v_p_y + s_b_y**2*v_b_value_sq - s_b_y**2*v_p_x**2 - 2*s_b_y*s_p_x*v_p_x*v_p_y - 2*s_b_y*s_p_y*v_b_value_sq + 2*s_b_y*s_p_y*v_p_x**2 + s_p_x**2*v_b_value_sq - s_p_x**2*v_p_y**2 + 2*s_p_x*s_p_y*v_p_x*v_p_y + s_p_y**2*v_b_value_sq - s_p_y**2*v_p_x**2)
        v_b_x = (-s_b_x*s_b_y*v_p_y + s_b_x*s_p_y*v_p_y - s_b_x*root + s_b_y**2*v_p_x + s_b_y*s_p_x*v_p_y - 2*s_b_y*s_p_y*v_p_x - s_p_x*s_p_y*v_p_y + s_p_x*root + s_p_y**2*v_p_x)/(s_b_x**2 - 2*s_b_x*s_p_x + s_b_y**2 - 2*s_b_y*s_p_y + s_p_x**2 + s_p_y**2) 
        v_b_y = (s_b_x**2*v_p_y - s_b_x*s_b_y*v_p_x - 2*s_b_x*s_p_x*v_p_y + s_b_x*s_p_y*v_p_x + s_b_y*s_p_x*v_p_x - s_b_y*root + s_p_x**2*v_p_y - s_p_x*s_p_y*v_p_x + s_p_y*root)/(s_b_x**2 - 2*s_b_x*s_p_x + s_b_y**2 - 2*s_b_y*s_p_y + s_p_x**2 + s_p_y**2)
        # dt = -(s_b_x*v_p_x + s_b_y*v_p_y - s_p_x*v_p_x - s_p_y*v_p_y)/(v_b_value_sq - v_p_x**2 - v_p_y**2) + root/(v_b_value_sq - v_p_x**2 - v_p_y**2)
        # print('v_b_x', v_b_x)
        # print('v_b_y', v_b_y)
        # print('dt', dt)
        return Vector2(v_b_x, v_b_y)
