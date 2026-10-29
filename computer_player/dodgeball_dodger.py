import logging
import math
from typing import List, Optional, Tuple

from core.entities import Player, PlayerRole, Vector2
from core.game_logic.game_logic import GameLogic
from computer_player.computer_player_utility.kinematics import TICK_DT, decay_table


class DodgeballDodger:
    """
    Sidestep opponent dodgeballs in flight.

    Runs after the base strategies and the moves and overrides the direction of a CPU player that a
    thrown opponent dodgeball would hit within `dodge_horizon` game seconds: the player runs
    perpendicular to the ball's path, away from it. The ball's path is a straight line with the
    exact speed decay; the player's own drift until the ball arrives is taken into account.

    A dodgeball is a threat while nobody holds it and it still belongs to the throwing team
    (it loses its possession team when it slows down to dead or is reflected).
    """
    def __init__(self,
                 logic: GameLogic,
                 dodge_horizon: Optional[float] = None, # game seconds; None: no dodging
                 dodge_buffer: float = 0.3, # m added to the hit distance (player radius + ball radius)
                 logger: Optional[logging.Logger] = None):
        """Store the dodge horizon and buffer."""
        self.logic = logic
        self.dodge_horizon = dodge_horizon
        self.dodge_buffer = dodge_buffer
        self.logger = logger or logging.getLogger("computer_player")

    def __call__(self, players: List[Player]) -> None:
        """Override the direction of each of `players` (CPU steered) that is about to be hit."""
        if self.dodge_horizon is None:
            return
        threats = [
            dodgeball for dodgeball in self.logic.state.dodgeballs
            if dodgeball.holder_id is None and dodgeball.possession_team is not None
            and (dodgeball.velocity.x != 0 or dodgeball.velocity.y != 0)
        ]
        if not threats:
            return
        for player in players:
            if player.is_knocked_out or player.dodgeball_immunity or (player.role == PlayerRole.SEEKER and not self.logic.state.seeker_on_pitch):
                continue
            for dodgeball in threats:
                if dodgeball.possession_team == player.team:
                    continue
                dodge_direction = self._dodge_direction(player, dodgeball)
                if dodge_direction is not None:
                    player.direction = dodge_direction
                    break

    def _dodge_direction(self, player: Player, dodgeball) -> Optional[Vector2]:
        """Unit direction perpendicular to the dodgeball's path, away from it, if the dodgeball would hit `player` soon."""
        approach = dodgeball_approach(player.position, player.velocity, player.deacceleration_rate, dodgeball)
        if approach is None:
            return None
        arrival_time, lateral, ux, uy = approach
        if arrival_time > self.dodge_horizon:
            return None
        if abs(lateral) > player.radius + dodgeball.radius + self.dodge_buffer:
            return None
        side = 1.0 if lateral >= 0 else -1.0
        self.logger.debug("Player %s dodges dodgeball %s arriving in %.2f s", player.id, dodgeball.id, arrival_time)
        return Vector2(-uy * side, ux * side)


def dodgeball_approach(position: Vector2, velocity: Vector2, deacceleration_rate: float, dodgeball) -> Optional[Tuple[float, float, float, float]]:
    """
    Closest approach of a free dodgeball to a player at `position` drifting with `velocity` (no new input).

    Returns (arrival time in game seconds along the ball's line, signed lateral distance to the line at
    that time (left positive), unit direction x, y of the ball), or None if the ball does not move, is
    already past the player or stops before reaching it. The ball's speed decays exactly as in BasicLogic.
    """
    speed = math.hypot(dodgeball.velocity.x, dodgeball.velocity.y)
    if speed == 0:
        return None
    ux, uy = dodgeball.velocity.x / speed, dodgeball.velocity.y / speed
    rx = position.x - dodgeball.position.x
    ry = position.y - dodgeball.position.y
    along = rx * ux + ry * uy
    if along <= 0:
        return None # behind the ball
    table = decay_table(dodgeball.deacceleration_rate)
    if table.c is None:
        arrival_time = along / speed
    else:
        fraction = along / (speed * table.c)
        if fraction >= 1:
            return None # stops before reaching the player
        arrival_time = math.log(1 - fraction) / math.log(table.q) * TICK_DT
    # player drift until the ball arrives, without new input
    tau_player = decay_table(deacceleration_rate).tau_at(arrival_time / TICK_DT)
    rx += velocity.x * tau_player
    ry += velocity.y * tau_player
    lateral = rx * -uy + ry * ux # signed distance to the ball's line (left positive)
    return arrival_time, lateral, ux, uy
