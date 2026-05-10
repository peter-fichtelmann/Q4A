
import logging
from typing import Dict, Optional, List, Tuple

from core.entities import Player, PlayerRole, Vector2
from core.game_logic.game_logic import GameLogic
from core.game_logic.utility_logic import UtilityLogic
from computer_player.computer_player_utility.move_around_hoop_blockage import MoveAroundHoopBlockage

class InterceptionCalculatorLegacy:
    """
    The former method to estimate if players can intercept a moving entity.

    It simulates real game logic steps and is thus quite exact.

    For each step, the best direction of each player is calculated.
    Then player and moving entity movement are simulated by a copied game logic.
    Followed by a check if the moving entity is intercepted.
    
    For each possible min step before interception all steps in between have to be simulated.
    The costs grow quadratically with (n+1)n/2 steps.
    This is not reasonable for larger distance calculations.

    Consequently, the new interception calculators are less accurate but faster estimates.
    """

    def __init__(self,
                    logic: GameLogic,
                    move_around_hoop_blockage: MoveAroundHoopBlockage,
                    tol_reaching_target: float = 0,
                    log_level: int = None,
                    logger: Optional[logging.Logger] = None
                    ):
        """Initialize simulation-based interception estimator configuration."""
        self.logic = logic
        self.move_around_hoop_blockage = move_around_hoop_blockage
        self.tol_reaching_target = tol_reaching_target
        self.log_level = log_level
        self.logger = logger

    def update_moving_free_ball_position(self, copy_moving_entity: object, dt: float):
        """Advance a copied free ball state by one step."""
        copy_moving_entity.velocity.x, copy_moving_entity.velocity.y = self.logic.basic_logic.get_free_ball_velocity(copy_moving_entity, dt)
        copy_moving_entity.position.x, copy_moving_entity.position.y = self.logic.basic_logic.get_update_position(copy_moving_entity, dt)

    def update_moving_player_position(self, copy_moving_entity: Player, dt: float):
        """Advance a copied player state by one step."""
        self.logic.basic_logic.update_player_velocity(copy_moving_entity, dt)
        copy_moving_entity.position.x, copy_moving_entity.position.y = self.logic.basic_logic.get_update_position(copy_moving_entity, dt)
    
    def get_dt_stepsize(self, copy_moving_entity: object, max_distance_per_step: Optional[float], max_dt_per_step: Optional[int]) -> float:
        """Derive a simulation dt based on movement speed and step caps."""
        dt = max_distance_per_step / (UtilityLogic._magnitude(copy_moving_entity.velocity) + 1e-6) if max_distance_per_step is not None else 0.1
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
                Simulate game steps to estimate interception along a trajectory.

                Returns an interception score in [0, 1], where 0 means immediate
                interception and 1 means no interception before target/end point,
                together with best per-player interception details.
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