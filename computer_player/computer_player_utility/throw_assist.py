import math
from dataclasses import dataclass
from typing import List, Optional

from config import Config
from core.entities import BallType, Player, PlayerRole, Vector2
from core.game_logic.process_action_logic import ProcessActionLogic
from computer_player.computer_player_utility.kinematics import TICK_DT, decay_table
from computer_player.computer_player_utility.interception_calculator import InterceptionCalculator
from computer_player.computer_player_utility.computer_player_utility import BeaterThrowDecider, ThrowDirector

SHOT_BEAT_TIER = 0 # shots (volleyball) and beats (dodgeball) come before passes within a safety band
PASS_TIER = 1


@dataclass
class ThrowAssistOption:
    """A pass, beat or shot reachable by rotating the human's throw."""
    kind: str # 'shot', 'beat' or 'pass'
    target_id: str # hoop or player id
    direction: Vector2 # unit throw direction
    angle: float # absolute rotation from the human's throw in degrees
    time_margin: float # game seconds, the larger the safer
    tier: int

    @property
    def band(self) -> int:
        """0: safe, 1: risky."""
        return 0 if self.time_margin >= Config.THROW_ASSIST_SAFE_MARGIN else 1


class ThrowAssist:
    """
    Aim help for human throws: rotates the throw by at most a few degrees onto the option the human most likely meant.

    The throw speed is kept, only the direction changes. Options:
    - volleyball: shots through an attack hoop (at most THROW_ASSIST_SHOT_MAX_ANGLE_DEG, hoops do not move)
      and passes to chasers/keepers of the own team. A throw that already scores is left as is.
    - dodgeball: beats on opponents and passes to beaters of the own team without a dodgeball.

    Every option gets a time margin (game seconds): passes and shots the margin to the fastest interceptor,
    beats THROW_ASSIST_BEAT_DODGE_TIME - flight time, as a live dodgeball cannot be intercepted, only dodged.
    Options with a negative margin are dropped. The chosen option has the lowest (safety band, tier, rotation):
    a safe pass wins over a risky beat, shots and beats win over passes in the same band.
    """
    def __init__(self, state, interception_calculator: InterceptionCalculator):
        self.state = state
        self.interception_calculator = interception_calculator
        self.beater_throw_decider = BeaterThrowDecider(0.0, 0.0, state=state, teammate_block_margin=Config.THROW_ASSIST_TEAMMATE_BLOCK_MARGIN)
        self.max_angle = Config.THROW_ASSIST_MAX_ANGLE_DEG
        self.shot_max_angle = Config.THROW_ASSIST_SHOT_MAX_ANGLE_DEG
        self.shot_search_step = Config.THROW_ASSIST_SHOT_SEARCH_STEP_DEG
        self.margin_cap = Config.THROW_ASSIST_TIME_MARGIN_CAP

    def assisted_direction(self, player: Player, strength_ratio: float = 1.0) -> Optional[Vector2]:
        """Throw direction for `player`'s throw (charged to `strength_ratio`) with the magnitude of its stick input, or None to throw unchanged."""
        option = self.best_option(player, strength_ratio)
        if option is None or option.angle == 0:
            return None
        raw = player.direction
        mag_raw = math.hypot(raw.x, raw.y)
        return Vector2(option.direction.x * mag_raw, option.direction.y * mag_raw)

    def best_option(self, player: Player, strength_ratio: float = 1.0) -> Optional[ThrowAssistOption]:
        """The chosen option of `player`'s current throw, None if no option is within reach."""
        options = self.options(player, strength_ratio)
        if not options:
            return None
        return min(options, key=lambda option: (option.band, option.tier, option.angle))

    def options(self, player: Player, strength_ratio: float = 1.0) -> List[ThrowAssistOption]:
        """Every option within the rotation limits (empty if the player cannot throw); `strength_ratio` of the charged throw."""
        if not player.has_ball:
            return []
        ball = self.state.get_ball(player.has_ball)
        if ball is None:
            return []
        if ball.ball_type == BallType.VOLLEYBALL and ball.is_dead:
            return []
        if self.state.game_time < self.state.throw_blocked_until.get(player.id, float('-inf')):
            return [] # the throw is refused anyway
        raw = player.direction
        mag_raw = math.hypot(raw.x, raw.y)
        if mag_raw == 0:
            return []
        # same speed as process_throw_action: stick inputs below 1 and shorter charges throw slower
        speed = ProcessActionLogic.effective_throw_velocity(player) * strength_ratio * min(mag_raw, 1.0)
        raw_unit = Vector2(raw.x / mag_raw, raw.y / mag_raw)
        own_hoops = [hoop for hoop in self.state.hoops.values() if hoop.team == player.team]
        if ball.ball_type == BallType.VOLLEYBALL:
            attack_hoops = [hoop for hoop in self.state.hoops.values() if hoop.team != player.team]
            for hoop in attack_hoops:
                if InterceptionCalculator.throw_through_hoop(ball, self._scaled(raw_unit, speed), [hoop]):
                    return [] # a score attempt is never changed
            interceptor_ids = [opponent.id for opponent in self._opponents(player) if opponent.role in (PlayerRole.CHASER, PlayerRole.KEEPER)]
            options = [option for hoop in attack_hoops
                       if (option := self._shot_option(ball, hoop, raw_unit, speed, own_hoops, interceptor_ids)) is not None]
            for receiver in self._teammates(player):
                if receiver.role in (PlayerRole.CHASER, PlayerRole.KEEPER):
                    option = self._volleyball_pass_option(player, ball, receiver, raw_unit, speed, own_hoops, interceptor_ids)
                    if option is not None:
                        options.append(option)
            return options
        options = []
        dead_ball_interceptor_ids = [opponent.id for opponent in self._opponents(player) if opponent.role == PlayerRole.BEATER]
        for target in self._opponents(player):
            if not target.dodgeball_immunity:
                option = self._dodgeball_option(player, ball, target, raw_unit, speed, 'beat', dead_ball_interceptor_ids)
                if option is not None:
                    options.append(option)
        for receiver in self._teammates(player):
            if receiver.role == PlayerRole.BEATER and not receiver.has_ball:
                option = self._dodgeball_option(player, ball, receiver, raw_unit, speed, 'pass', dead_ball_interceptor_ids)
                if option is not None:
                    options.append(option)
        return options

    def _shot_option(self, ball, hoop, raw_unit: Vector2, speed: float, own_hoops, interceptor_ids: List[str]) -> Optional[ThrowAssistOption]:
        """Smallest rotation within the shot limit that throws through `hoop`."""
        n_steps = int(round(self.shot_max_angle / self.shot_search_step))
        for step in range(1, n_steps + 1):
            for sign in (1, -1):
                angle = sign * step * self.shot_search_step
                direction = self._rotated(raw_unit, angle)
                velocity = self._scaled(direction, speed)
                if not InterceptionCalculator.throw_through_hoop(ball, velocity, [hoop]):
                    continue
                if InterceptionCalculator.throw_through_hoop(ball, velocity, own_hoops):
                    continue
                # distance along the throw to the hoop line
                distance = abs((hoop.position.x - ball.position.x) / direction.x)
                arrival_time = self.interception_calculator.arrival_time(ball, speed, distance)
                time_margin = self.interception_calculator.throw_time_margin(ball, velocity, arrival_time, interceptor_ids, self.margin_cap)
                if time_margin < 0:
                    return None
                return ThrowAssistOption('shot', hoop.id, direction, abs(angle), time_margin, SHOT_BEAT_TIER)
        return None

    def _volleyball_pass_option(self, player: Player, ball, receiver: Player, raw_unit: Vector2, speed: float,
                                own_hoops, interceptor_ids: List[str]) -> Optional[ThrowAssistOption]:
        """Pass to `receiver` if within the rotation limit, not through own hoops and not intercepted first."""
        aim = self._aim(player, ball, receiver, raw_unit, speed)
        if aim is None:
            return None
        direction, angle, velocity, catch_tick = aim
        if InterceptionCalculator.throw_through_hoop(ball, velocity, own_hoops):
            return None
        time_margin = self.interception_calculator.throw_time_margin(
            ball, velocity, catch_tick * TICK_DT, interceptor_ids, self.margin_cap, receiver_id=receiver.id)
        if time_margin < 0:
            return None
        return ThrowAssistOption('pass', receiver.id, direction, angle, time_margin, PASS_TIER)

    def _dodgeball_option(self, player: Player, ball, target: Player, raw_unit: Vector2, speed: float, kind: str,
                          dead_ball_interceptor_ids: List[str]) -> Optional[ThrowAssistOption]:
        """
        Beat on or pass to `target` if within the rotation limit and no teammate reflects the dodgeball before.

        A live dodgeball cannot be caught by opponents, so a beat has to arrive alive and its margin is the
        time the target has left to dodge. A pass arriving alive is safe; a dead one can be picked up by
        opponent beaters, which then compete with the receiver.
        """
        aim = self._aim(player, ball, target, raw_unit, speed)
        if aim is None:
            return None
        direction, angle, velocity, catch_tick = aim
        if self.beater_throw_decider._teammate_in_the_way(player, target, ball.position, velocity, ball):
            return None
        arrival_time = catch_tick * TICK_DT
        arrival_speed = speed * decay_table(ball.deacceleration_rate).q ** catch_tick
        is_alive = arrival_speed > ball.dead_velocity_threshold
        if kind == 'beat':
            if not is_alive:
                return None
            time_margin = min(self.margin_cap, Config.THROW_ASSIST_BEAT_DODGE_TIME - arrival_time)
            tier = SHOT_BEAT_TIER
        else:
            if is_alive:
                time_margin = self.margin_cap
            else:
                time_margin = self.interception_calculator.throw_time_margin(
                    ball, velocity, arrival_time, dead_ball_interceptor_ids, self.margin_cap, receiver_id=target.id)
            tier = PASS_TIER
        if time_margin < 0:
            return None
        return ThrowAssistOption(kind, target.id, direction, angle, time_margin, tier)

    def _aim(self, player: Player, ball, target: Player, raw_unit: Vector2, speed: float):
        """(unit direction, rotation in degrees, throw velocity, catch tick) to reach the moving `target`, None if out of reach."""
        velocity, _, catch_tick = ThrowDirector.throw_analytic_with_tick(player, target, ball.position, throw_velocity=speed)
        if velocity is None:
            return None
        direction = Vector2(velocity.x / speed, velocity.y / speed)
        angle = abs(self._angle(raw_unit, direction))
        if angle > self.max_angle:
            return None
        return direction, angle, velocity, catch_tick

    def _teammates(self, player: Player) -> List[Player]:
        """Teammates that can catch: on the pitch and not knocked out."""
        return [other for other in self.state.players.values()
                if other.team == player.team and other.id != player.id and self._is_in_play(other)]

    def _opponents(self, player: Player) -> List[Player]:
        """Opponents on the pitch that are not knocked out."""
        return [other for other in self.state.players.values()
                if other.team != player.team and self._is_in_play(other)]

    def _is_in_play(self, player: Player) -> bool:
        if player.is_knocked_out:
            return False
        return player.role != PlayerRole.SEEKER or self.state.seeker_on_pitch

    @staticmethod
    def _angle(a: Vector2, b: Vector2) -> float:
        """Signed angle from `a` to `b` in degrees."""
        return math.degrees(math.atan2(a.x * b.y - a.y * b.x, a.x * b.x + a.y * b.y))

    @staticmethod
    def _rotated(v: Vector2, degrees: float) -> Vector2:
        radians = math.radians(degrees)
        cos, sin = math.cos(radians), math.sin(radians)
        return Vector2(v.x * cos - v.y * sin, v.x * sin + v.y * cos)

    @staticmethod
    def _scaled(v: Vector2, factor: float) -> Vector2:
        return Vector2(v.x * factor, v.y * factor)
