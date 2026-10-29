import logging
import math
from dataclasses import dataclass
from types import SimpleNamespace
from typing import Dict, List, Optional, Tuple
from config import Config
from core.entities import Hoop, Player, PlayerRole, Vector2, VolleyBall
from core.game_logic.utility_logic import UtilityLogic
from core.game_logic.process_action_logic import ProcessActionLogic
from computer_player.computer_player_utility.kinematics import TICK_DT, decay_table, first_throw_tick, player_position_at
from computer_player.computer_player_utility.interception_calculator import InterceptionCalculator


class ChargedThrow:
    """
    Throws take time: a throw is charged for one tick per strength step (ProcessActionLogic.start_throw_charge)
    and only then leaves, `throw_charge_full_ticks` ticks for full strength. The computer players throw at full
    strength, except very short passes, which arrive earlier with a shorter, weaker charge.

    During the charge thrower, receiver and defenders keep moving, so (with MOTION_MODEL "analytic") the CPU aims
    from where the ball will be at the release, at where the receiver will be then, gives the defenders the
    charge time as well, and re-aims at every step of the charge (`reaim`).
    """
    @staticmethod
    def release_ticks(state) -> int:
        """Ticks until a full-strength throw started now leaves (0 with the legacy motion model, whose estimates ignore the charge)."""
        return state.throw_charge_full_ticks if Config.MOTION_MODEL == "analytic" else 0

    @staticmethod
    def release_origin(thrower: Player, ball_position: Vector2, release_tick: float) -> Vector2:
        """Where the held ball is after `release_tick` ticks, the thrower keeping its stick input (a held ball keeps its offset)."""
        if release_tick <= 0:
            return Vector2(ball_position.x, ball_position.y)
        x, y = player_position_at(thrower, release_tick)
        return Vector2(ball_position.x + x - thrower.position.x, ball_position.y + y - thrower.position.y)

    @staticmethod
    def released_ball(ball, origin: Vector2) -> SimpleNamespace:
        """Stand-in of `ball` thrown from `origin`, for checks that only read the position and decay (throw_through_hoop, beam)."""
        return SimpleNamespace(position=origin, deacceleration_rate=ball.deacceleration_rate)

    @staticmethod
    def fastest_release_ticks(full_ticks: int, full_velocity: float, deacceleration_rate: float, distance: float) -> int:
        """
        Charge ticks for a throw over `distance` that arrives first: charge ticks + flight ticks, the flight
        with strength ticks / full_ticks of `full_velocity`. Only very short throws come out below full_ticks.
        """
        table = decay_table(deacceleration_rate)

        def total_ticks(ticks):
            speed = full_velocity * ticks / full_ticks
            if speed <= 0:
                return float('inf')
            if table.c is None:
                return ticks + distance / speed / table.dt
            fraction = distance / (speed * table.c)
            if fraction >= 1:
                return float('inf') # stops before
            return ticks + math.log(1 - fraction) / math.log(table.q)

        best_ticks, best_total = full_ticks, total_ticks(full_ticks)
        for ticks in range(full_ticks - 1, 0, -1): # unimodal: stop at the first worse charge
            total = total_ticks(ticks)
            if total >= best_total:
                break
            best_ticks, best_total = ticks, total
        return best_ticks

    @staticmethod
    def reaim(state, cpu_player_id_set) -> None:
        """
        Re-aim the charged throws of CPU players at their targets (receiver, beat target or hoop) with the
        remaining charge ticks, as thrower and target may have changed their input since the throw started.
        """
        if Config.MOTION_MODEL != "analytic":
            return
        for player_id, charge in state.throw_charges.items():
            if player_id not in cpu_player_id_set or charge.direction is None or charge.target_id is None:
                continue
            remaining = charge.release_ticks - charge.ticks
            thrower = state.players.get(player_id)
            ball = state.balls.get(charge.ball_id)
            if remaining <= 0 or thrower is None or ball is None:
                continue
            origin = ChargedThrow.release_origin(thrower, ball.position, remaining)
            speed = ProcessActionLogic.effective_throw_velocity(thrower) * charge.release_ticks / state.throw_charge_full_ticks
            hoop = state.hoops.get(charge.target_id)
            if hoop is not None:
                dx, dy = hoop.position.x - origin.x, hoop.position.y - origin.y
                distance = math.hypot(dx, dy)
                if distance > 0:
                    charge.direction = Vector2(dx / distance * speed, dy / distance * speed)
                continue
            target = state.players.get(charge.target_id)
            if target is None:
                continue
            direction, _, _ = ThrowDirector.throw_analytic_with_tick(thrower, target, origin, throw_velocity=speed, release_tick=remaining)
            if direction is not None:
                charge.direction = direction


class MoveUtility:
    """Helper functions for movement and boundary-safe steering."""

    @staticmethod
    def evade(player_position: Vector2, entity_to_evade_position: Vector2, weight: float|Tuple[float, float] = 1.0) -> Vector2:
        """Return an inverse-distance weighted vector away from another entity."""
        player_to_entity_vector = Vector2(
            entity_to_evade_position.x - player_position.x,
            entity_to_evade_position.y - player_position.y
        )
        squared_mag_player_to_entity_vector = UtilityLogic._squared_sum(player_to_entity_vector.x, player_to_entity_vector.y)
        if squared_mag_player_to_entity_vector == 0:
            return Vector2(0, 0)
        if isinstance(weight, Tuple):
            weight_x, weight_y = weight
        else:
            weight_x = weight
            weight_y = weight
        evade_vector = Vector2(
            -player_to_entity_vector.x * weight_x / squared_mag_player_to_entity_vector, # norm to one and then divide by distance to entity to get stronger evasion when closer
            -player_to_entity_vector.y * weight_y / squared_mag_player_to_entity_vector
        )
        return evade_vector

    @staticmethod
    def evade_squared(player_position: Vector2, entity_to_evade_position: Vector2, weight: float = 1.0, max_magnitude: Optional[float] = None) -> Vector2:
        """Return a vector away from another entity with magnitude weight / distance^2, capped at `max_magnitude`."""
        player_to_entity_vector = Vector2(
            entity_to_evade_position.x - player_position.x,
            entity_to_evade_position.y - player_position.y
        )
        squared_distance = UtilityLogic._squared_sum(player_to_entity_vector.x, player_to_entity_vector.y)
        if squared_distance == 0:
            return Vector2(0, 0)
        distance = math.sqrt(squared_distance)
        magnitude = weight / squared_distance
        if max_magnitude is not None:
            magnitude = min(magnitude, max_magnitude)
        return Vector2(
            -player_to_entity_vector.x / distance * magnitude,
            -player_to_entity_vector.y / distance * magnitude
        )

    @staticmethod
    def attract_quadratic(player_position: Vector2, entity_to_attract_position: Vector2, weight: float = 1.0) -> Vector2:
        """Return a vector towards another entity whose magnitude grows with the squared distance (weight * distance^2)."""
        player_to_entity_vector = Vector2(
            entity_to_attract_position.x - player_position.x,
            entity_to_attract_position.y - player_position.y
        )
        distance = math.sqrt(UtilityLogic._squared_sum(player_to_entity_vector.x, player_to_entity_vector.y))
        return Vector2(
            player_to_entity_vector.x * weight * distance, # vector has magnitude distance, times distance gives distance^2
            player_to_entity_vector.y * weight * distance
        )

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
        """Clamp move direction so buffered field boundaries are not crossed."""
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
    Decide whether beaters should throw their dodgeball.
    
    Idea 1: just hard distance threshold
    Idea 2: hard threshold and probability per second of 1/(distance + value) where value is aggressiveness

    Shared by all beater strategies and the dodgeball assigner. A target that a dodgeball of the
    thrower's team is already flying at is not thrown at again, so a second beater keeps its
    dodgeball as backup instead of wasting it on the same player.

    Bludger control (`keep_last_dodgeball`): a beater with the team's last dodgeball does not throw it
    while an opponent beater is loaded, except at a loaded opponent beater or at a volleyball holder
    within `last_dodgeball_threat_distance` of the thrower's own hoops.

    Teammates in the way (`teammate_block_margin`): a dodgeball touching a teammate of the thrower is
    reflected and loses its possession, so the beat fails. A beater does not throw if a teammate,
    moved on with its velocity until the dodgeball passes it, is closer to the throw line before the
    target than its radius + the dodgeball radius + this margin.
    """
    def __init__(
            self,
            throw_threshold_volleyball_holder: float,
            throw_threshold_loaded_beater: float,
            state=None,
            keep_last_dodgeball: bool = False,
            last_dodgeball_threat_distance: float = 8.0,
            teammate_block_margin: Optional[float] = None, # m; None: teammates in the way are ignored
            ):
        """Store squared distance thresholds used by beater throw checks."""
        self.squared_throw_threshold_volleyball_holder = throw_threshold_volleyball_holder**2
        self.squared_throw_threshold_loaded_beater = throw_threshold_loaded_beater**2
        self.state = state
        self.keep_last_dodgeball = keep_last_dodgeball
        self.squared_last_dodgeball_threat_distance = last_dodgeball_threat_distance**2
        self.teammate_block_margin = teammate_block_margin
        self.pending_throws: Dict[str, Tuple[str, int]] = {} # target id -> (dodgeball id, thrower team) of a throw in flight

    def update_pending_throws(self, state) -> None:
        """Forget throws that are over: dodgeball picked up, slowed down or reflected (possession lost), or target knocked out."""
        for target_id, (dodgeball_id, team) in list(self.pending_throws.items()):
            dodgeball = state.balls.get(dodgeball_id)
            target = state.players.get(target_id)
            if (dodgeball is None or target is None or target.is_knocked_out
                    or (dodgeball.holder_id is not None and dodgeball.holder_id not in state.throw_charges) # still charged: pending
                    or dodgeball.possession_team != team):
                del self.pending_throws[target_id]

    def throw_at(self, process_action_logic, beater: Player, target: Player) -> bool:
        """Start a full-strength charged throw of `beater`'s dodgeball at the moving `target` and remember it. Returns whether the throw started."""
        if process_action_logic.is_charging_throw(beater.id):
            return False # already throwing
        if self._keeps_last_dodgeball(beater, target):
            return False
        dodgeball_id = beater.has_ball
        held_ball = self.state.balls.get(dodgeball_id) if self.state is not None else None
        release_tick = ChargedThrow.release_ticks(process_action_logic.state)
        origin = ChargedThrow.release_origin(beater, held_ball.position if held_ball else beater.position, release_tick)
        throw_direction = ThrowDirector.get_throw_direction_moving_receiver(beater, target, origin, release_tick=release_tick)
        if self.teammate_block_margin is not None and self._teammate_in_the_way(beater, target, origin, throw_direction, held_ball):
            return False
        if not process_action_logic.start_throw_charge(beater.id, throw_direction, target_id=target.id):
            return False
        self.pending_throws[target.id] = (dodgeball_id, beater.team)
        return True

    def _teammate_in_the_way(self, beater: Player, target: Player, origin: Vector2, throw_direction: Vector2, ball) -> bool:
        """Whether a teammate of `beater` other than `target` would reflect a dodgeball thrown from `origin` along `throw_direction` before it reaches `target`."""
        if self.state is None:
            return False
        speed = math.hypot(throw_direction.x, throw_direction.y)
        if speed == 0:
            return False
        ux, uy = throw_direction.x / speed, throw_direction.y / speed
        target_distance = (target.position.x - origin.x) * ux + (target.position.y - origin.y) * uy
        ball_radius = ball.radius if ball is not None else 0.0
        for player in self.state.players.values():
            if player.team != beater.team or player.id == beater.id or player.id == target.id or player.is_knocked_out:
                continue
            if player.role == PlayerRole.SEEKER and not self.state.seeker_on_pitch:
                continue
            along = (player.position.x - origin.x) * ux + (player.position.y - origin.y) * uy
            if along <= 0 or along >= target_distance:
                continue
            # where the teammate is when the dodgeball passes it (constant speeds)
            time = along / speed
            x = player.position.x + player.velocity.x * time - origin.x
            y = player.position.y + player.velocity.y * time - origin.y
            along = x * ux + y * uy
            if along <= 0 or along >= target_distance:
                continue
            if abs(x * uy - y * ux) < player.radius + ball_radius + self.teammate_block_margin:
                return True
        return False

    def _keeps_last_dodgeball(self, beater: Player, target: Player) -> bool:
        """Whether `beater` keeps its dodgeball as the team's last one instead of throwing it at `target`."""
        if not self.keep_last_dodgeball or self.state is None:
            return False
        players = self.state.players.values()
        if any(player.team == beater.team and player.role == PlayerRole.BEATER and player.has_ball and player.id != beater.id for player in players):
            return False # not the last dodgeball
        if not any(player.team != beater.team and player.role == PlayerRole.BEATER and player.has_ball and not player.is_knocked_out for player in players):
            return False # no loaded opponent beater to keep control against
        if target.role == PlayerRole.BEATER and target.has_ball:
            return False # beating a loaded beater frees its dodgeball
        volleyball = self.state.volleyball
        if volleyball is not None and target.id == volleyball.holder_id:
            own_hoops = [hoop for hoop in self.state.hoops.values() if hoop.team == beater.team]
            if any(UtilityLogic._squared_distance(target.position, hoop.position) <= self.squared_last_dodgeball_threat_distance for hoop in own_hoops):
                return False # scoring threat
        return True

    def _is_targeted(self, target: Player) -> bool:
        """Whether a dodgeball is already flying at `target`."""
        return target.id in self.pending_throws

    def should_throw_at_volleyball_holder(self, beater: Player, volleyball_holder: Player) -> bool:
        """Return True when holder is throwable, not already thrown at and inside holder range threshold."""
        if volleyball_holder.dodgeball_immunity or self._is_targeted(volleyball_holder):
            return False
        squared_distance = UtilityLogic._squared_distance(beater.position, volleyball_holder.position)
        if squared_distance <= self.squared_throw_threshold_volleyball_holder:
            return True
        return False
    
    def should_throw_at_loaded_beater(self, beater: Player, loaded_beater: Player) -> bool:
        """Return True when a loaded opposing beater is not already thrown at and within throw range."""
        if self._is_targeted(loaded_beater):
            return False
        squared_distance = UtilityLogic._squared_distance(beater.position, loaded_beater.position)
        if squared_distance <= self.squared_throw_threshold_loaded_beater:
            return True
        return False


class ThrowDirector:
    """Calculates the throw vector to a moving receiver e.g. for passes and beats"""
    @staticmethod
    def get_throw_direction_static_receiver(player: Player, receiver: Player, origin: Optional[Vector2] = None):
        """Return direct throw vector from the ball's start `origin` (default the player) to a static receiver position."""
        origin = origin or player.position
        return  Vector2(
            receiver.position.x - origin.x,
            receiver.position.y - origin.y
        )

    @staticmethod
    def _prepare_linear_solve(player: Player, receiver: Player, origin: Optional[Vector2] = None):
        """Prepare variables for linear solve of throw direction to moving receiver."""
        # the ball starts at `origin` (a held ball is offset from its holder, around the player radius), default player position
        origin = origin or player.position
        s_b_x = origin.x
        s_b_y = origin.y
        s_p_x = receiver.position.x
        s_p_y = receiver.position.y
        v_p_x = receiver.velocity.x
        v_p_y = receiver.velocity.y
        v_b_value_sq = ProcessActionLogic.effective_throw_velocity(player)**2
        root = math.sqrt(s_b_x**2*v_b_value_sq - s_b_x**2*v_p_y**2 + 2*s_b_x*s_b_y*v_p_x*v_p_y - 2*s_b_x*s_p_x*v_b_value_sq + 2*s_b_x*s_p_x*v_p_y**2 - 2*s_b_x*s_p_y*v_p_x*v_p_y + s_b_y**2*v_b_value_sq - s_b_y**2*v_p_x**2 - 2*s_b_y*s_p_x*v_p_x*v_p_y - 2*s_b_y*s_p_y*v_b_value_sq + 2*s_b_y*s_p_y*v_p_x**2 + s_p_x**2*v_b_value_sq - s_p_x**2*v_p_y**2 + 2*s_p_x*s_p_y*v_p_x*v_p_y + s_p_y**2*v_b_value_sq - s_p_y**2*v_p_x**2)

        return s_b_x, s_b_y, s_p_x, s_p_y, v_p_x, v_p_y, v_b_value_sq, root

    @staticmethod
    def get_throw_direction_moving_receiver(player: Player, receiver: Player, origin: Optional[Vector2] = None, release_tick: int = 0):
        """
        Assume constant ball velocity. The throw velocity is the player's, but the ball starts at `origin`
        (the held ball's position, default the player's), so the throw line runs from there to the receiver.

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

        With MOTION_MODEL "analytic" the exact ball decay and receiver acceleration are used, and a charged
        throw leaving `origin` in `release_tick` ticks aims at where the receiver will be by then; if the
        ball cannot reach the receiver, it falls back to the constant velocity solution (throw anyway).
        """
        if Config.MOTION_MODEL == "analytic":
            throw_direction, _, _ = ThrowDirector.throw_analytic_with_tick(player, receiver, origin, release_tick=release_tick)
            if throw_direction is not None:
                return throw_direction
        # # assume ball starts at player position
        # s_b_x = player.position.x
        # s_b_y = player.position.y
        # s_p_x = receiver.position.x
        # s_p_y = receiver.position.y
        # v_p_x = receiver.velocity.x
        # v_p_y = receiver.velocity.y
        # v_b_value_sq = player.throw_velocity**2
        # # print('s_b_x', s_b_x)
        # # print('s_b_y', s_b_y)
        # # print('s_p_x', s_p_x)
        # # print('s_p_y', s_p_y)
        # # print('v_p_x', v_p_x)
        # # print('v_p_y', v_p_y)
        # # print('v_b_value_sq', v_b_value_sq)
        # root = math.sqrt(s_b_x**2*v_b_value_sq - s_b_x**2*v_p_y**2 + 2*s_b_x*s_b_y*v_p_x*v_p_y - 2*s_b_x*s_p_x*v_b_value_sq + 2*s_b_x*s_p_x*v_p_y**2 - 2*s_b_x*s_p_y*v_p_x*v_p_y + s_b_y**2*v_b_value_sq - s_b_y**2*v_p_x**2 - 2*s_b_y*s_p_x*v_p_x*v_p_y - 2*s_b_y*s_p_y*v_b_value_sq + 2*s_b_y*s_p_y*v_p_x**2 + s_p_x**2*v_b_value_sq - s_p_x**2*v_p_y**2 + 2*s_p_x*s_p_y*v_p_x*v_p_y + s_p_y**2*v_b_value_sq - s_p_y**2*v_p_x**2)
        s_b_x, s_b_y, s_p_x, s_p_y, v_p_x, v_p_y, v_b_value_sq, root = ThrowDirector._prepare_linear_solve(player, receiver, origin)
        v_b_x = (-s_b_x*s_b_y*v_p_y + s_b_x*s_p_y*v_p_y - s_b_x*root + s_b_y**2*v_p_x + s_b_y*s_p_x*v_p_y - 2*s_b_y*s_p_y*v_p_x - s_p_x*s_p_y*v_p_y + s_p_x*root + s_p_y**2*v_p_x)/(s_b_x**2 - 2*s_b_x*s_p_x + s_b_y**2 - 2*s_b_y*s_p_y + s_p_x**2 + s_p_y**2) 
        v_b_y = (s_b_x**2*v_p_y - s_b_x*s_b_y*v_p_x - 2*s_b_x*s_p_x*v_p_y + s_b_x*s_p_y*v_p_x + s_b_y*s_p_x*v_p_x - s_b_y*root + s_p_x**2*v_p_y - s_p_x*s_p_y*v_p_x + s_p_y*root)/(s_b_x**2 - 2*s_b_x*s_p_x + s_b_y**2 - 2*s_b_y*s_p_y + s_p_x**2 + s_p_y**2)
        # dt = -(s_b_x*v_p_x + s_b_y*v_p_y - s_p_x*v_p_x - s_p_y*v_p_y)/(v_b_value_sq - v_p_x**2 - v_p_y**2) + root/(v_b_value_sq - v_p_x**2 - v_p_y**2)
        # print('v_b_x', v_b_x)
        # print('v_b_y', v_b_y)
        # print('dt', dt)
        return Vector2(v_b_x, v_b_y)

    @staticmethod
    def get_throw_direction_and_position_moving_receiver(player: Player, receiver: Player, origin: Optional[Vector2] = None):
        """
        Return throw vector and predicted receiver position for moving receiver.

        With MOTION_MODEL "analytic" the ball decay and the receiver's acceleration with its current
        stick input are modelled exactly; returns (None, None) if the ball cannot reach the receiver.
        """
        if Config.MOTION_MODEL == "analytic":
            return ThrowDirector._throw_analytic(player, receiver, origin)
        s_b_x, s_b_y, s_p_x, s_p_y, v_p_x, v_p_y, v_b_value_sq, root = ThrowDirector._prepare_linear_solve(player, receiver, origin)
        v_b_x = (-s_b_x*s_b_y*v_p_y + s_b_x*s_p_y*v_p_y - s_b_x*root + s_b_y**2*v_p_x + s_b_y*s_p_x*v_p_y - 2*s_b_y*s_p_y*v_p_x - s_p_x*s_p_y*v_p_y + s_p_x*root + s_p_y**2*v_p_x)/(s_b_x**2 - 2*s_b_x*s_p_x + s_b_y**2 - 2*s_b_y*s_p_y + s_p_x**2 + s_p_y**2) 
        v_b_y = (s_b_x**2*v_p_y - s_b_x*s_b_y*v_p_x - 2*s_b_x*s_p_x*v_p_y + s_b_x*s_p_y*v_p_x + s_b_y*s_p_x*v_p_x - s_b_y*root + s_p_x**2*v_p_y - s_p_x*s_p_y*v_p_x + s_p_y*root)/(s_b_x**2 - 2*s_b_x*s_p_x + s_b_y**2 - 2*s_b_y*s_p_y + s_p_x**2 + s_p_y**2)
        dt = -(s_b_x*v_p_x + s_b_y*v_p_y - s_p_x*v_p_x - s_p_y*v_p_y)/(v_b_value_sq - v_p_x**2 - v_p_y**2) + root/(v_b_value_sq - v_p_x**2 - v_p_y**2)
        predicted_receiver_position = Vector2(
            receiver.position.x + receiver.velocity.x * dt,
            receiver.position.y + receiver.velocity.y * dt
        )
        return Vector2(v_b_x, v_b_y), predicted_receiver_position

    @staticmethod
    def _throw_analytic(player: Player, receiver: Player, origin: Optional[Vector2] = None) -> Tuple[Optional[Vector2], Optional[Vector2]]:
        """Throw vector (magnitude throw_velocity) and predicted receiver position via kinematics.first_throw_tick."""
        throw_direction, predicted_receiver_position, _ = ThrowDirector.throw_analytic_with_tick(player, receiver, origin)
        return throw_direction, predicted_receiver_position

    @staticmethod
    def throw_analytic_with_tick(player: Player, receiver: Player, origin: Optional[Vector2] = None,
                                 throw_velocity: Optional[float] = None,
                                 release_tick: int = 0) -> Tuple[Optional[Vector2], Optional[Vector2], Optional[float]]:
        """
        Like _throw_analytic, plus the (fractional) tick from now at which the ball reaches the receiver (`throw_velocity`
        defaults to the player's). A charged throw leaves `origin` in `release_tick` ticks.
        """
        origin = origin or player.position
        if throw_velocity is None:
            throw_velocity = ProcessActionLogic.effective_throw_velocity(player)
        result = first_throw_tick(
            thrower_x=origin.x,
            thrower_y=origin.y,
            throw_velocity=throw_velocity,
            ball_table=decay_table(Config.BALL_DEACCELERATION_RATE),
            receiver=receiver,
            reach_distance=Config.THROW_CATCH_MARGIN_FACTOR * (receiver.radius + Config.VOLLEYBALL_RADIUS),
            release_tick=release_tick,
        )
        if result is None:
            return None, None, None
        catch_tick, receiver_x, receiver_y = result
        throw_x = receiver_x - origin.x
        throw_y = receiver_y - origin.y
        mag_throw = math.hypot(throw_x, throw_y)
        if mag_throw == 0:
            throw_x, throw_y = receiver.position.x - origin.x, receiver.position.y - origin.y
            mag_throw = math.hypot(throw_x, throw_y) or 1.0
        return (Vector2(throw_x / mag_throw * throw_velocity, throw_y / mag_throw * throw_velocity),
                Vector2(receiver_x, receiver_y),
                catch_tick)


class ScoreAttempter:
    """
    Decide whether the volleyball holder shoots and at which hoop.

    Shared by the base attack and the moves, so a player scores the same way
    no matter which of them currently steers it.

    interception_model:
        'beam': beam cosine angle score, shoot if above `scoring_threshold`.
        'time_margin': game seconds the fastest defender needs longer to reach the shot than the shot needs
            to the hoop (analytic motion model), shoot if at least `shot_time_margin`.

    Hoops seen at less than `min_shot_angle` degrees from the hoop line (a shot from far to the side)
    are never shot at, since such shots rarely go through the hoop.

    With `angle_scaled_risk`, the interception risk allowed for a shot scales with sin(angle to the hoop line):
    a 90° shot may take the risk of the plain threshold, a 20° shot only about a third (sin 20° = 0.34).
    Risk is 1 - score in the 'beam' model, and 1 / (1 + exp(margin / `shot_risk_time_scale`)) in the
    'time_margin' model. Among the hoops, the one exceeding its required score the most is shot at.
    """
    def __init__(self,
                 interception_calculator: InterceptionCalculator,
                 process_action_logic,
                 score_squared_max_distance: float,
                 scoring_threshold: float,
                 interception_model: str = 'beam',
                 shot_time_margin: float = 0.5,
                 time_margin_cap: float = 3.0,
                 min_shot_angle: float = 0.0,
                 angle_scaled_risk: bool = False,
                 shot_risk_time_scale: float = 0.5,
                 logger: Optional[logging.Logger] = None):
        """Store the interception model and the shot thresholds."""
        self.interception_calculator = interception_calculator
        self.process_action_logic = process_action_logic
        # only consider scoring on hoops within this squared distance from the volleyball, since far shots are unlikely to be good opportunities
        self.score_squared_max_distance = score_squared_max_distance
        self.scoring_threshold = scoring_threshold
        self.use_time_margin = interception_model == 'time_margin' and Config.MOTION_MODEL == 'analytic'
        self.shot_time_margin = shot_time_margin
        self.time_margin_cap = time_margin_cap
        # |dx| < tan(min_shot_angle) * |dy|: the shot comes in at less than min_shot_angle to the hoop line
        self.min_shot_angle_tan = math.tan(math.radians(min_shot_angle))
        self.angle_scaled_risk = angle_scaled_risk
        self.shot_risk_time_scale = shot_risk_time_scale
        # interception risk allowed for a 90° shot
        if self.use_time_margin:
            self.straight_shot_risk = 1 / (1 + math.exp(shot_time_margin / shot_risk_time_scale))
        else:
            self.straight_shot_risk = 1 - scoring_threshold
        self.logger = logger or logging.getLogger("computer_player")

    def is_too_far_to_the_side(self, dx: float, dy: float) -> bool:
        """Whether a shot along (dx, dy) to a hoop comes in at less than `min_shot_angle` to the hoop line."""
        return abs(dx) < self.min_shot_angle_tan * abs(dy)

    def required_score(self, dx: float, dy: float) -> float:
        """Score (time margin or beam score) a shot along (dx, dy) needs, the larger the more to the side with `angle_scaled_risk`."""
        threshold = self.shot_time_margin if self.use_time_margin else self.scoring_threshold
        if not self.angle_scaled_risk:
            return threshold
        distance = math.hypot(dx, dy)
        allowed_risk = self.straight_shot_risk * abs(dx) / distance if distance > 0 else 0.0 # risk scaled by sin(angle to the hoop line)
        if allowed_risk <= 0:
            return float('inf') # exactly along the hoop line
        if self.use_time_margin:
            return self.shot_risk_time_scale * math.log(1 / allowed_risk - 1)
        return 1 - allowed_risk

    def get_time_margins_for_hoops(self,
                                   volleyball: VolleyBall,
                                   volleyball_holder: Player,
                                   attack_hoops: List[Hoop],
                                   defending_chaser_keeper_ids: List[str]) -> Dict[str, float]:
        """Time margin of a shot at each attack hoop in range, the larger the safer."""
        time_margins_dict = {}
        throw_velocity = ProcessActionLogic.effective_throw_velocity(volleyball_holder)
        # the shot leaves after a full charge, from where the held ball is by then
        release_tick = ChargedThrow.release_ticks(self.process_action_logic.state)
        origin = ChargedThrow.release_origin(volleyball_holder, volleyball.position, release_tick)
        for hoop in attack_hoops:
            dx = hoop.position.x - origin.x
            dy = hoop.position.y - origin.y
            squared_distance = dx**2 + dy**2
            if squared_distance > self.score_squared_max_distance or squared_distance == 0:
                continue
            if self.is_too_far_to_the_side(dx, dy):
                continue
            distance = math.sqrt(squared_distance)
            arrival_time = self.interception_calculator.arrival_time(volleyball, throw_velocity, distance)
            if arrival_time == float('inf'):
                continue # the ball stops before the hoop
            time_margins_dict[hoop.id] = self.interception_calculator.throw_time_margin(
                volleyball, Vector2(throw_velocity * dx / distance, throw_velocity * dy / distance),
                release_tick * TICK_DT + arrival_time, defending_chaser_keeper_ids, self.time_margin_cap,
                origin=origin, release_tick=release_tick)
        return time_margins_dict

    def get_intercepting_scores_for_hoops(self,
                                          volleyball: VolleyBall,
                                          volleyball_holder: Player,
                                          attack_hoops: List[Hoop],
                                          defending_chaser_keeper_ids: List[str]) -> Dict[str, float]:
        """Compute interception-risk scores for shots toward each attack hoop."""
        intercepting_scores_dict = {}
        throw_velocity = ProcessActionLogic.effective_throw_velocity(volleyball_holder)
        for hoop in attack_hoops:
            volleyball_hoop_vector = Vector2(
                hoop.position.x - volleyball.position.x,
                hoop.position.y - volleyball.position.y
            )
            squared_volleyball_hoop_distance = volleyball_hoop_vector.x**2 + volleyball_hoop_vector.y**2
            if squared_volleyball_hoop_distance > self.score_squared_max_distance:
                continue
            if self.is_too_far_to_the_side(volleyball_hoop_vector.x, volleyball_hoop_vector.y):
                continue
            copy_volleyball = volleyball.copy()
            mag_volleyball_hoop_vector = math.sqrt(squared_volleyball_hoop_distance)
            copy_volleyball.velocity.x = throw_velocity * volleyball_hoop_vector.x / mag_volleyball_hoop_vector
            copy_volleyball.velocity.y = throw_velocity * volleyball_hoop_vector.y / mag_volleyball_hoop_vector
            beam_cosine_angle, beam_cosine_angle_player_id, _ = self.interception_calculator.beam_cosine_angle(
                moving_entity=copy_volleyball,
                intercepting_player_ids=defending_chaser_keeper_ids,
                target_position=hoop.position,
                moving_entity_target_vector=volleyball_hoop_vector)
            intercepting_score = self.interception_calculator.interception_score_from_beam_cosine_angle(
                beam_cosine_angle=beam_cosine_angle,
                beam_angle_player_id=beam_cosine_angle_player_id,
                mag_moving_entity_velocity=throw_velocity,
            )
            intercepting_scores_dict[hoop.id] = intercepting_score
        return intercepting_scores_dict

    def attempt(self,
                volleyball: VolleyBall,
                volleyball_holder: Player,
                attack_hoops: List[Hoop],
                defending_chaser_keeper_ids: List[str]) -> bool:
        """Shoot at the safest hoop when its score (interception score or time margin) is good enough. Returns True if a shot was started."""
        if self.process_action_logic.is_charging_throw(volleyball_holder.id):
            return False # already throwing
        if self.use_time_margin:
            intercepting_scores_dict = self.get_time_margins_for_hoops(volleyball, volleyball_holder, attack_hoops, defending_chaser_keeper_ids)
        else:
            intercepting_scores_dict = self.get_intercepting_scores_for_hoops(volleyball, volleyball_holder, attack_hoops, defending_chaser_keeper_ids)
        # if no intercepting_scores, then probably to far away to score
        if len(intercepting_scores_dict) == 0:
            return False
        # get hoop whose score exceeds its required score the most (lowest chance of being intercepted for its angle)
        hoops_by_id = {hoop.id: hoop for hoop in attack_hoops}
        excess_dict = {}
        for hoop_id, score in intercepting_scores_dict.items():
            hoop = hoops_by_id[hoop_id]
            excess_dict[hoop_id] = score - self.required_score(hoop.position.x - volleyball.position.x, hoop.position.y - volleyball.position.y)
        best_hoop_id = max(excess_dict, key=excess_dict.get)
        best_score = intercepting_scores_dict[best_hoop_id]
        good_enough = excess_dict[best_hoop_id] >= 0 if self.use_time_margin else excess_dict[best_hoop_id] > 0
        if good_enough:
            return self.shoot(volleyball, volleyball_holder, hoops_by_id[best_hoop_id], best_score)
        return False

    def shoot(self, volleyball: VolleyBall, volleyball_holder: Player, hoop: Hoop, score: float) -> bool:
        """Start a full-strength charged shot at `hoop`. Returns False if the throw is refused (e.g. right after receiving a turnover ball)."""
        # aim from the held ball at the release, which is offset from the holder's centre by about the player radius
        origin = ChargedThrow.release_origin(volleyball_holder, volleyball.position, ChargedThrow.release_ticks(self.process_action_logic.state))
        throw_direction = Vector2(hoop.position.x - origin.x, hoop.position.y - origin.y)
        if self.process_action_logic.start_throw_charge(volleyball_holder.id, throw_direction, target_id=hoop.id):
            self.logger.info("Scoring on hoop %s with interception score %s", hoop.id, score)
            return True
        return False


@dataclass
class PassOption:
    """A pass that reaches its receiver without crossing the passer's own hoops."""
    receiver_id: str
    throw_direction: Vector2
    predicted_receiver_position: Vector2
    interception_score: float # the larger, the less likely the pass is intercepted (>= 1 outside the interception cone)
    time_margin: Optional[float] = None # game seconds the ball arrives before the fastest defender could reach it ('time_margin' model)
    strength_ratio: float = 1.0 # charge of the throw; below 1 only for very short passes that arrive earlier that way
    catch_time: Optional[float] = None # game seconds from now (charge + flight) until the ball reaches the receiver (analytic motion model)


class PassEvaluator:
    """
    Rate pass receivers and check single passes.

    Shared by the base attack and the moves, so both use the same pass-to-player
    score (position penalty) and the same interception model.

    interception_model:
        'beam': a pass is safe if its beam interception score passes the caller's threshold.
        'time_margin': a pass is safe if the ball reaches the receiver at least `pass_time_margin`
            game seconds before the fastest defender could reach it (analytic motion model).
            With `active_receiver`, the receiver runs to the ball like the defenders do, instead of
            keeping its stick input.
    """
    def __init__(self,
                 interception_calculator: InterceptionCalculator,
                 passing_evade_vector_position_penalty_weight: float,
                 interception_model: str = 'beam',
                 pass_time_margin: float = 0.5,
                 time_margin_cap: float = 3.0,
                 active_receiver: bool = False):
        """Store the interception model and the evade weight of the position penalty."""
        self.interception_calculator = interception_calculator
        self.passing_evade_vector_position_penalty_weight = passing_evade_vector_position_penalty_weight
        self.use_time_margin = interception_model == 'time_margin' and Config.MOTION_MODEL == 'analytic'
        self.pass_time_margin = pass_time_margin
        self.time_margin_cap = time_margin_cap
        self.active_receiver = active_receiver # the receiver runs to the ball, so it may catch it before its predicted position

    def is_safe(self, pass_option: PassOption, beam_threshold: float, strict: bool = False) -> bool:
        """Whether the pass is safe enough: time margin model, or the beam score against the caller's threshold."""
        if self.use_time_margin:
            return pass_option.time_margin >= self.pass_time_margin
        if strict:
            return pass_option.interception_score > beam_threshold
        return pass_option.interception_score >= beam_threshold

    def position_penalty(self, player: Player, attack_hoops: List[Hoop], evade_vector: Vector2) -> float:
        """
        Pass-to-player score, the lower the better.

        Squared distance to the closest attack hoop (closer players have a better chance to score)
        plus the weighted squared magnitude of the player's evade vector (pressure on that player).
        """
        closest_attack_hoop_squared_distance = min([
            UtilityLogic._squared_distance(player.position, hoop.position) for hoop in attack_hoops
        ])
        squared_mag_evade_vector = evade_vector.x**2 + evade_vector.y**2
        return closest_attack_hoop_squared_distance + self.passing_evade_vector_position_penalty_weight * squared_mag_evade_vector

    def evaluate(self,
                 volleyball: VolleyBall,
                 volleyball_holder: Player,
                 receiver: Player,
                 own_hoops: List[Hoop],
                 defending_chaser_keeper_ids: List[str]) -> Optional[PassOption]:
        """
        Throw direction, predicted receiver position and interception score of a pass.

        The pass is a charged throw (see ChargedThrow): full strength, or a shorter charge if that reaches a
        very close receiver earlier. With the analytic motion model it is aimed from the ball's position at the
        release, and the time margin gives the defenders the charge time as well.

        Returns None if the ball cannot reach the receiver or the throw would go through own hoops.
        """
        time_margin = None
        catch_time = None
        strength_ratio = 1.0
        throw_velocity = ProcessActionLogic.effective_throw_velocity(volleyball_holder)
        origin = volleyball.position
        release_tick = 0
        if Config.MOTION_MODEL == "analytic":
            full_ticks = self.interception_calculator.logic.state.throw_charge_full_ticks
            origin = ChargedThrow.release_origin(volleyball_holder, volleyball.position, full_ticks)
            receiver_x, receiver_y = player_position_at(receiver, full_ticks)
            release_tick = ChargedThrow.fastest_release_ticks(
                full_ticks, throw_velocity, volleyball.deacceleration_rate, math.hypot(receiver_x - origin.x, receiver_y - origin.y))
            if release_tick != full_ticks:
                origin = ChargedThrow.release_origin(volleyball_holder, volleyball.position, release_tick)
            strength_ratio = release_tick / full_ticks
            throw_velocity *= strength_ratio
            throw_direction, predicted_receiver_position, catch_tick = ThrowDirector.throw_analytic_with_tick(
                volleyball_holder, receiver, origin, throw_velocity=throw_velocity, release_tick=release_tick)
            if catch_tick is not None:
                catch_time = catch_tick * TICK_DT
        else:
            throw_direction, predicted_receiver_position = ThrowDirector.get_throw_direction_and_position_moving_receiver(volleyball_holder, receiver, volleyball.position)
        if throw_direction is None:
            return None # ball cannot reach this player
        released_ball = ChargedThrow.released_ball(volleyball, origin)
        # throw_direction still has the throw speed as magnitude here
        if InterceptionCalculator.throw_through_hoop(released_ball, throw_direction, own_hoops):
            return None
        if self.use_time_margin:
            # throw_direction still has the throw speed as magnitude here
            time_margin = self.interception_calculator.throw_time_margin(
                volleyball, throw_direction, catch_time, defending_chaser_keeper_ids, self.time_margin_cap,
                receiver_id=receiver.id if self.active_receiver else None, origin=origin, release_tick=release_tick)
        # beam_cosine_angle normalizes throw_direction in place, which is then thrown as is
        beam_cosine_angle, beam_cosine_angle_player_id, _ = self.interception_calculator.beam_cosine_angle(
            moving_entity=released_ball,
            intercepting_player_ids=defending_chaser_keeper_ids,
            target_position=predicted_receiver_position,
            moving_entity_target_vector=throw_direction
        )
        interception_score = self.interception_calculator.interception_score_from_beam_cosine_angle(
            beam_cosine_angle=beam_cosine_angle,
            beam_angle_player_id=beam_cosine_angle_player_id,
            mag_moving_entity_velocity=throw_velocity,
        )
        return PassOption(receiver.id, throw_direction, predicted_receiver_position, interception_score, time_margin,
                          strength_ratio=strength_ratio, catch_time=catch_time)

    @staticmethod
    def throw(process_action_logic, volleyball_holder: Player, pass_option: PassOption) -> bool:
        """Start the charged throw of `pass_option`. Returns False if refused (e.g. right after receiving a turnover ball, or already throwing)."""
        return process_action_logic.start_throw_charge(
            volleyball_holder.id, pass_option.throw_direction, pass_option.strength_ratio, target_id=pass_option.receiver_id)
