import math
from functools import lru_cache
from typing import Optional, Tuple

from config import Config

TICK_DT = 1.0 / Config.FPS * Config.GAME_TIME_TO_REAL_TIME_RATIO


class DecayTable:
    """
    Closed-form motion of the fixed-dt tick update in BasicLogic (velocity first, then position):

        v_{n+1} = q * v_n + (1 - q) * v_term,   x_{n+1} = x_n + dt * v_{n+1},   q = 1 - k * dt

    which gives after n ticks (t_n = n * dt)

        x_n = x_0 + v_0 * tau(n) + v_term * (t_n - tau(n)),   tau(n) = dt * q * (1 - q^n) / (1 - q)

    v_0 * tau(n) is the coasting displacement and v_term * (t_n - tau(n)) the displacement gained by
    running with constant input. Balls have v_term = 0. For players the formula is exact when
    acceleration / deacceleration_rate <= max_speed (MOTION_MODEL "analytic"), as the speed cap never binds.

    tau is tabulated for integer ticks; tau_at also accepts fractional ticks.
    """
    def __init__(self, deacceleration_rate: float, dt: float = TICK_DT, max_ticks: int = Config.MOTION_MODEL_MAX_TICKS):
        """Precompute q and tau(n) for n = 0..2*max_ticks (room for two-phase estimates)."""
        self.dt = dt
        self.q = 1.0 - deacceleration_rate * dt
        self.c = dt * self.q / (1.0 - self.q) if deacceleration_rate > 0 else None
        self.max_ticks = max_ticks
        self.tau = [self.tau_at(n) for n in range(2 * max_ticks + 1)]

    def tau_at(self, n: float) -> float:
        """Coasting displacement factor after n (possibly fractional) ticks."""
        if self.c is None:
            return n * self.dt
        return self.c * (1.0 - self.q ** n)


@lru_cache(maxsize=None)
def decay_table(deacceleration_rate: float) -> DecayTable:
    """Shared DecayTable per deacceleration rate."""
    return DecayTable(deacceleration_rate)


def terminal_speed(player) -> float:
    """Speed a player converges to with full input (acceleration / deacceleration rate, capped)."""
    if player.deacceleration_rate <= 0:
        return player.max_speed
    return min(player.acceleration / player.deacceleration_rate, player.max_speed)


def terminal_velocity(player, direction) -> Optional[Tuple[float, float]]:
    """Terminal velocity for a constant stick input, or None if the input counts as no input (coasting)."""
    mag_dir = math.hypot(direction.x, direction.y)
    if mag_dir == 0 or mag_dir < player.min_dir:
        return None
    speed = terminal_speed(player)
    if mag_dir > 1:
        speed /= mag_dir
    return direction.x * speed, direction.y * speed


def player_position_at(player, n: float, direction=None) -> Tuple[float, float]:
    """Predicted player position after n (possibly fractional) ticks holding the stick input constant."""
    table = decay_table(player.deacceleration_rate)
    if direction is None:
        direction = player.direction
    v_term = terminal_velocity(player, direction)
    vx, vy = player.velocity.x, player.velocity.y
    if v_term is None:
        speed = math.hypot(vx, vy)
        if speed == 0:
            return player.position.x, player.position.y
        if math.hypot(direction.x, direction.y) < player.min_dir and player.min_speed > 0 and 0 < table.q < 1:
            # coasting without input: velocity snaps to zero in the first tick its updated speed is below min_speed
            if speed * table.q < player.min_speed:
                return player.position.x, player.position.y
            n_snap = math.floor(math.log(player.min_speed / speed) / math.log(table.q)) + 1
            n = min(n, n_snap - 1)
        tau = table.tau_at(n)
        return player.position.x + vx * tau, player.position.y + vy * tau
    tau = table.tau_at(n)
    run = n * table.dt - tau
    return (player.position.x + vx * tau + v_term[0] * run,
            player.position.y + vy * tau + v_term[1] * run)


def first_interception_tick(
        player_x: float, player_y: float,
        player_vx: float, player_vy: float,
        run_speed: float,
        player_table: DecayTable,
        target_x: float, target_y: float,
        target_vx: float, target_vy: float,
        target_table: DecayTable,
        reach_distance: float,
        target_tick_offset: int = 0,
        max_ticks: int = Config.MOTION_MODEL_MAX_TICKS,
        ) -> Optional[Tuple[int, float, float]]:
    """
    First tick n at which a player can be within reach_distance of a decaying target (e.g. a free ball).

    Without further input the player drifts to the coasting point C(n) = p_0 + v_0 * tau_p(n); running
    in a constant direction adds up to R(n) = run_speed * (t_n - tau_p(n)) in any direction, so the set of
    reachable positions at tick n is the disc (C(n), R(n)). Interception at n is possible iff

        |B(n) - C(n)| <= R(n) + reach_distance,   B(n) = b_0 + v_b * tau_b(n + target_tick_offset)

    The first n is found by scanning with the largest step that cannot skip it: the distance from B(n) to
    the reach boundary shrinks by at most the ball's and the player's drift per tick plus the growth of R
    per tick (all non-increasing or constant), so no tick before n + distance / closing speed can be in
    reach. A fast ball passing a nearby player (a window of about 3 ticks) is therefore never missed, while
    far or slow targets are skipped in few steps.

    Returns (n, steer_x, steer_y) with the constant steering vector B(n) - C(n), or None if not
    possible within max_ticks.
    """
    tau_p = player_table.tau
    tau_b = target_table.tau
    dt = player_table.dt
    max_ticks = min(max_ticks, len(tau_b) - 1 - target_tick_offset, len(tau_p) - 1)
    if max_ticks < 0:
        return None

    def gap(n):
        tb = tau_b[n + target_tick_offset]
        tp = tau_p[n]
        ex = target_x + target_vx * tb - player_x - player_vx * tp
        ey = target_y + target_vy * tb - player_y - player_vy * tp
        reach = run_speed * (n * dt - tp) + reach_distance
        return ex * ex + ey * ey - reach * reach, ex, ey, reach

    g, ex, ey, reach = gap(0)
    if g <= 0:
        return 0, ex, ey
    target_speed = math.hypot(target_vx, target_vy)
    player_speed = math.hypot(player_vx, player_vy)
    reach_growth = run_speed * dt # upper bound of R(n + 1) - R(n)
    n = 0
    while n < max_ticks:
        closing = (target_speed * (tau_b[n + target_tick_offset + 1] - tau_b[n + target_tick_offset])
                   + player_speed * (tau_p[n + 1] - tau_p[n]) + reach_growth)
        distance = math.sqrt(g + reach * reach) - reach # to the reach boundary, > 0 here
        step = max(1, int(distance / closing)) if closing > 0 else max_ticks - n
        previous = n
        n = min(n + step, max_ticks)
        g, ex, ey, reach = gap(n)
        if g <= 0:
            low, high = previous, n # gap(low) > 0, gap(high) <= 0; the step is 1 tick unless the root lies exactly at n
            while high - low > 1:
                middle = (low + high) // 2
                g_middle, ex_middle, ey_middle, _ = gap(middle)
                if g_middle <= 0:
                    high, ex, ey = middle, ex_middle, ey_middle
                else:
                    low = middle
            return high, ex, ey
    return None


def first_throw_tick(
        thrower_x: float, thrower_y: float,
        throw_velocity: float,
        ball_table: DecayTable,
        receiver,
        reach_distance: float,
        max_ticks: int = Config.MOTION_MODEL_MAX_TICKS,
        scan_step: int = Config.MOTION_MODEL_SCAN_STEP,
        ) -> Optional[Tuple[float, float, float]]:
    """
    First (fractional) tick n at which a thrown ball can reach the receiver, assuming the receiver keeps
    its stick input: throw_velocity * tau_b(n) + reach_distance >= |P(n) - S|.

    Integer scan, then regula falsi on the fractional tick. Returns (n, receiver_x, receiver_y) with the
    predicted receiver position P(n), or None if the ball cannot reach the receiver within max_ticks.
    """
    max_ticks = min(max_ticks, len(ball_table.tau) - 1)

    def reach_gap(n, tau_ball):
        px, py = player_position_at(receiver, n)
        return throw_velocity * tau_ball + reach_distance - math.hypot(px - thrower_x, py - thrower_y), px, py

    previous = 0
    h_previous = reach_distance - math.hypot(receiver.position.x - thrower_x, receiver.position.y - thrower_y)
    if h_previous >= 0:
        return 0, receiver.position.x, receiver.position.y
    n = 0
    while n < max_ticks:
        n = min(n + max(scan_step, n // 4), max_ticks)
        h, px, py = reach_gap(n, ball_table.tau[n])
        if h >= 0:
            low, high, h_low, h_high = previous, n, h_previous, h
            for _ in range(3):
                middle = low + (high - low) * (-h_low) / (h_high - h_low)
                h_middle, px_middle, py_middle = reach_gap(middle, ball_table.tau_at(middle))
                if h_middle >= 0:
                    high, h_high, px, py = middle, h_middle, px_middle, py_middle
                else:
                    low, h_low = middle, h_middle
            return high, px, py
        previous, h_previous = n, h
    return None
