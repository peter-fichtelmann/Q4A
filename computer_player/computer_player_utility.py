
import logging
import math
from typing import Dict, Optional, List, Tuple

from core.entities import Player, PlayerRole, Vector2, Hoop
from core.game_logic.game_logic import GameLogic
from core.game_logic.utility_logic import UtilityLogic

class MoveAroundHoopBlockage:
    def __init__(self,
                 defence_hoops: List[Hoop],
                 move_buffer_factor: float = 1.2,
                 tol: float = 1e-2,
                 logger: Optional[logging.Logger] = None
                 ):
        self.defence_hoops = defence_hoops
        self.move_buffer_factor = move_buffer_factor    
        self.tol = tol
        self.logger = logger

    def __call__(self,
                 player: Player,
                 target_position: Vector2,
                 target_hoop: Hoop,
                 add_hoop_blockage_x: float,
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
        copy_moving_entity.velocity = self.logic.basic_logic.get_free_ball_velocity(copy_moving_entity, dt)
        copy_moving_entity.position = self.logic.basic_logic.get_update_position(copy_moving_entity, dt)

    def update_moving_player_position(self, copy_moving_entity: Player, dt: float):
        self.logic.basic_logic.update_player_velocity(copy_moving_entity, dt)
        copy_moving_entity.position = self.logic.basic_logic.get_update_position(copy_moving_entity, dt)

    def get_dt_stepsize(self, copy_moving_entity: object, max_distance_per_step: Optional[float], max_dt_per_step: Optional[int]) -> float:
        dt = max_distance_per_step / (UtilityLogic._square_sum(copy_moving_entity.velocity.x, copy_moving_entity.velocity.y) ** 0.5) if max_distance_per_step is not None else 0.1
        if max_dt_per_step is not None and dt > max_dt_per_step:
            dt = max_dt_per_step
        return dt


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
                len_moving_entity_target = ((target_position.x - copy_moving_entity.position.x)**2 + (target_position.y - copy_moving_entity.position.y)**2) ** 0.5
                if len_moving_entity_target > previous_len_moving_entity_target:
                    can_reach_target = True
                    if steps == 0:
                        updated_max_dt_steps = 1 # if already at target position, just check for intercepting at the current position without updating moving entity position
                    updated_max_dt_steps = steps - 1 # if can reach target then check for line intercepting at each step until reaching target (instead of max_dt_steps)
                    break
                previous_len_moving_entity_target = len_moving_entity_target
            self.logger.debug(f"Updated moving entity positions for interception ratio calculation: {[f'({pos.x:.2f}, {pos.y:.2f})' for pos in updated_moving_entity_positions]}")
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
                                add_hoop_blockage_x = intercepting_player.radius + self.logic.state.get_volleyball().radius
                                intercepting_player.direction = self.move_around_hoop_blockage(
                                    player=intercepting_player,
                                    target_position=updated_moving_entity_positions[steps],
                                    target_hoop=self.move_around_hoop_blockage.defence_hoops[0], # assume hoops same x position and orientation so can use any as target hoop 
                                    add_hoop_blockage_x=add_hoop_blockage_x,
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
                                if distance <= (player.radius + moving_entity.radius)**2:
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
                for step_ratio in step_ratio_dict.values():
                    intercepting_score = step_ratio * intercepting_score # combine step ratios for multiple intercepting players
                return intercepting_score, step_ratio_dict
            else:
                return 1, {} # no intercepting, reached target
        # not reaching target
        # print(f"Not reaching target within {max_dt_steps} steps, returning intercepting score of 0")
        return 0, {}
    

    



