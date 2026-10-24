import logging
import math
from typing import Optional, List

from core.entities import Player, Vector2, Hoop


class MoveAroundHoopBlockage:
    """Compute movement vectors that avoid hoop-blockage collision regions."""

    def __init__(self,
                 defence_hoops: List[Hoop],
                 move_buffer_factor_x: float = 1.2,
                 move_buffer_factor_y: float = 1.2,
                 tol: float = 1e-2,
                 volleyball_radius: float = 0.0, # for hoop blockage_x
                 logger: Optional[logging.Logger] = None
                 ):
        """Store hoop geometry and tuning parameters for blockage avoidance."""
        self.defence_hoops = defence_hoops
        self.move_buffer_factor_x = move_buffer_factor_x
        self.move_buffer_factor_y = move_buffer_factor_y
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

        The method traces the straight segment from ``player.position`` to ``target_position``
        and checks whether it intersects hoop blockage boundaries. If a blocking
        intersection is detected, it redirects movement toward a buffered hoop corner;
        otherwise it returns direct movement toward the target (or ``lookahead_to_target``
        when provided).

        It is assumed the hoops have all the same orientation and x-value: radius along the y-axis (perpendicular x-axis). Hoop rotation is not implemented.

        Args:
            player: Defender whose movement is being computed.
            target_position: Desired point to move toward for this frame.
            target_hoop: Primary hoop used for x-side intersection checks and side
                determination.
            add_hoop_blockage_x: Horizontal half-width of hoop blockage for collision
                avoidance (for example, player radius plus ball radius).
            lookahead_to_target: Optional precomputed direction vector to use when no
                blockage is found (typically a velocity-aware lookahead).
            add_target_x_buffer: When ``True`` and no blockage is found, applies an
                additional x-buffer offset to the returned direct direction.

        Returns:
            Vector2: The direction vector the caller should use for movement this
            frame. A zero vector is returned when ``target_position`` equals
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
        # blockage zone per hoop, same as BoundaryLogic._enforce_hoop_blockage:
        # hoop.x +/- (player.radius + ball.radius), hoop.y +/- (hoop.radius + player.radius)
        add_hoop_blockage_y = target_hoop.radius + player.radius
        blocking_hoop = self._first_blocking_hoop(player.position, target_position, add_hoop_blockage_x, add_hoop_blockage_y)
        if blocking_hoop is None:
            # no blockage found, move directly towards the target with estimation of current velocity taken into account
            if lookahead_to_target is not None:
                direction = lookahead_to_target
            else:
                direction = direction_to_target
            if add_target_x_buffer:
                # add buffer, inverse to the side of the target
                add_x_buffer = add_hoop_blockage_x * (self.move_buffer_factor_x - 1)
                if target_hoop.position.x < target_position.x:
                    direction.x += add_x_buffer
                else:
                    direction.x -= add_x_buffer
            return direction
        return self._corner_direction(player, target_position, blocking_hoop, add_hoop_blockage_x, add_hoop_blockage_y)

    def avoid(self, player: Player, direction: Vector2, lookahead_distance: float) -> Vector2:
        """Return ``direction``, or a detour around the hoops when it runs into a blockage zone within ``lookahead_distance``.

        For a direction that is a sum of several pulls (formation, evading, getting open) instead of a way to a target point.
        The detour keeps the magnitude of ``direction``.
        """
        direction_mag = math.hypot(direction.x, direction.y)
        if direction_mag == 0 or not self.defence_hoops:
            return direction
        add_hoop_blockage_x = self.volleyball_radius + player.radius
        add_hoop_blockage_y = self.defence_hoops[0].radius + player.radius
        look_position = Vector2(
            player.position.x + direction.x / direction_mag * lookahead_distance,
            player.position.y + direction.y / direction_mag * lookahead_distance
        )
        blocking_hoop = self._first_blocking_hoop(player.position, look_position, add_hoop_blockage_x, add_hoop_blockage_y)
        if blocking_hoop is None:
            return direction
        detour = self._corner_direction(player, look_position, blocking_hoop, add_hoop_blockage_x, add_hoop_blockage_y)
        return Vector2(detour.x * direction_mag, detour.y * direction_mag)

    def _corner_direction(self,
                          player: Player,
                          target_position: Vector2,
                          blocking_hoop: Hoop,
                          add_hoop_blockage_x: float,
                          add_hoop_blockage_y: float
                          ) -> Vector2:
        """Unit vector towards the buffered zone corner of ``blocking_hoop`` with the shortest way to ``target_position``."""
        # go around the blocking hoop via the buffered corner of its zone with the shortest path to the target:
        # corner -> target, or corner -> second corner -> target when the direct way is blocked
        corner_dx = add_hoop_blockage_x * self.move_buffer_factor_x
        corner_dy = add_hoop_blockage_y * self.move_buffer_factor_y
        corners = [
            Vector2(blocking_hoop.position.x + sign_x * corner_dx, blocking_hoop.position.y + sign_y * corner_dy)
            for sign_x in (-1, 1) for sign_y in (-1, 1)
        ]
        corner_to_target_lengths = [
            math.hypot(target_position.x - corner.x, target_position.y - corner.y)
            if self._first_blocking_hoop(corner, target_position, add_hoop_blockage_x, add_hoop_blockage_y) is None else float('inf')
            for corner in corners
        ]
        best_corner = None
        best_length = float('inf')
        for i, corner in enumerate(corners):
            if self._first_blocking_hoop(player.position, corner, add_hoop_blockage_x, add_hoop_blockage_y) is not None:
                continue
            remaining_length = corner_to_target_lengths[i]
            if math.isinf(remaining_length):
                for j, second_corner in enumerate(corners):
                    if j == i or math.isinf(corner_to_target_lengths[j]):
                        continue
                    if self._first_blocking_hoop(corner, second_corner, add_hoop_blockage_x, add_hoop_blockage_y) is None:
                        remaining_length = min(remaining_length, math.hypot(second_corner.x - corner.x, second_corner.y - corner.y) + corner_to_target_lengths[j])
            length = math.hypot(corner.x - player.position.x, corner.y - player.position.y) + remaining_length
            if length < best_length - self.tol:
                best_corner, best_length = corner, length
        if best_corner is None:
            # no corner reachable (e.g. inside the zone while knocked out), head to the closest corner on the target's y side
            sign_y = -1 if target_position.y < player.position.y else 1
            sign_x = -1 if player.position.x < blocking_hoop.position.x else 1
            best_corner = Vector2(blocking_hoop.position.x + sign_x * corner_dx, blocking_hoop.position.y + sign_y * corner_dy)
        direction = Vector2(best_corner.x - player.position.x, best_corner.y - player.position.y)
        # the corner is only a waypoint, so pass it at full speed
        direction_mag = math.hypot(direction.x, direction.y)
        if direction_mag > 0:
            direction = Vector2(direction.x / direction_mag, direction.y / direction_mag)
        return direction

    def _first_blocking_hoop(self,
                             start: Vector2,
                             end: Vector2,
                             add_hoop_blockage_x: float,
                             add_hoop_blockage_y: float
                             ) -> Optional[Hoop]:
        """Return the hoop whose blockage zone the segment from ``start`` to ``end`` enters first, or ``None``.

        Touching a zone edge does not count (the blockage rule pins players onto the edge), so ``tol``
        is subtracted from the zone half-widths.
        """
        dx = end.x - start.x
        dy = end.y - start.y
        best_t = float('inf')
        best_hoop = None
        for hoop in self.defence_hoops:
            # Liang-Barsky clipping of the segment against the zone rectangle
            t_enter, t_exit = 0.0, 1.0
            blocked = True
            for p, q in (
                (-dx, start.x - (hoop.position.x - add_hoop_blockage_x + self.tol)),
                (dx, (hoop.position.x + add_hoop_blockage_x - self.tol) - start.x),
                (-dy, start.y - (hoop.position.y - add_hoop_blockage_y + self.tol)),
                (dy, (hoop.position.y + add_hoop_blockage_y - self.tol) - start.y),
            ):
                if p == 0:
                    if q < 0:
                        blocked = False
                        break
                else:
                    t = q / p
                    if p < 0:
                        t_enter = max(t_enter, t)
                    else:
                        t_exit = min(t_exit, t)
                    if t_enter > t_exit:
                        blocked = False
                        break
            if blocked and t_enter < best_t:
                best_t, best_hoop = t_enter, hoop
        return best_hoop