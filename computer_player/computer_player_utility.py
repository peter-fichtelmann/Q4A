
import math
from typing import Optional, List

from core.entities import Player, Vector2, Hoop

class MoveAroundHoopBlockage:
    def __init__(self,
                 defence_hoops: List[Hoop],
                 move_buffer_factor: float = 1.2,
                 tol: float = 1e-2
                 ):
        self.defence_hoops = defence_hoops
        self.move_buffer_factor = move_buffer_factor    
        self.tol = tol

    def __call__(self,
                 player: Player,
                 target: Vector2,
                 target_hoop: Hoop,
                 add_hoop_blockage_x: float,
                 lookahead_to_target: Optional[Vector2] = None,
                 add_target_x_buffer: bool = False
                 ) -> Vector2:
        """Compute a movement vector that steers a defender around hoop blockage.

        The method traces the straight segment from ``player.position`` to ``target``
        and checks whether it intersects hoop blockage boundaries. If a blocking
        crossing is detected, it redirects movement toward a buffered hoop corner;
        otherwise it returns direct movement toward the target (or ``lookahead_to_target``
        when provided).

        Args:
            player: Defender whose movement is being computed.
            target: Desired point to move toward for this frame.
            target_hoop: Primary hoop used for x-side crossing checks and side
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
            target.x - player.position.x,
            target.y - player.position.y
            )

        # min_dir and min_velocity of players can make it difficult to go around hoops
        if direction_to_target.x == 0 and direction_to_target.y == 0:
            # no movement needed, already at the hoop, so no blockage
            return Vector2(0, 0)
        x_pos_position = target_hoop.position.x < target.x # True if target is on right side of hoop
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
        best_x_crossing  = (float('inf'), None, None, None) # (t, x, y, hoop)
        # only calculate crossings if target is on the opposite side of the hoop from the player, otherwise there is no blockage to worry about (player can move around the hoop without crossing any blockage boundaries)
        if not ((player.position.x > hoop_blockage_x_pos and target.x > hoop_blockage_x_pos) or
            (player.position.x < hoop_blockage_x_neg and target.x < hoop_blockage_x_neg)
            ):
            best_y_crossing = (float('inf'), None, None, None) # (t, x, y, hoop)
            # check x crossing
            line_t_x = (hoop_blockage_x - player.position.x) / direction_to_target.x if direction_to_target.x != 0 else float('inf')
            if line_t_x > 0 - self.tol and line_t_x < 1 + self.tol:
                check_y_at_line_t_x = player.position.y + direction_to_target.y * line_t_x
                if (check_y_at_line_t_x >= target_hoop.position.y - target_hoop.radius and check_y_at_line_t_x <= target_hoop.position.y + add_hoop_blockage_x):
                    best_x_crossing = (line_t_x, hoop_blockage_x + add_x_buffer, check_y_at_line_t_x, target_hoop)
            # check all possible y crossings
            for hoop in self.defence_hoops:
                for add_hoop_blockage_radius in [hoop.radius, - hoop.radius]:
                    y = hoop.position.y + add_hoop_blockage_radius
                    line_t_y = (y - player.position.y) / direction_to_target.y if direction_to_target.y != 0 else float('inf')
                    if line_t_y > 0 - self.tol and line_t_y < 1 + self. tol:
                        x = player.position.x + direction_to_target.x * line_t_y
                        if (x >= hoop.position.x - add_hoop_blockage_x and x <= hoop.position.x + add_hoop_blockage_x):
                            if line_t_y < best_y_crossing[0]:
                                y = hoop.position.y + add_hoop_blockage_radius * self.move_buffer_factor # add buffer after checks (before checks leads to wrong checks)
                                best_y_crossing = (line_t_y, x, y, hoop)
        if math.isinf(best_x_crossing[0]) and math.isinf(best_y_crossing[0]):
            # no blockage found, move directly towards the hoop with estimation of current velocity taken into account
            if lookahead_to_target is not None:
                direction = lookahead_to_target
            else:
                direction = direction_to_target
            if add_target_x_buffer:
                # add buffer
                direction.x -= add_x_buffer # inverse to add buffer
        elif best_x_crossing[0] < best_y_crossing[0]:
            # use best x crossing
            # check closest corner of the hoop where the player should move towards with buffer to avoid blockage
            if direction_to_target.y < 0: # move towards upper corner
                corner_y = best_x_crossing[3].position.y + best_x_crossing[3].radius * self.move_buffer_factor
            else: # move towards lower corner
                corner_y = best_x_crossing[3].position.y - best_x_crossing[3].radius * self.move_buffer_factor
            direction = Vector2(best_x_crossing[1] - player.position.x, corner_y - player.position.y)
        else: # best y_crossing is closer
            if x_pos_position:
                corner_x = best_y_crossing[3].position.x + add_hoop_blockage_x * self.move_buffer_factor
            else:
                corner_x = best_y_crossing[3].position.x - add_hoop_blockage_x * self.move_buffer_factor
            direction = Vector2(corner_x - player.position.x, best_y_crossing[2] - player.position.y)
        return direction