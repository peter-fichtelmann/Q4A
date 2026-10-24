import logging
import math
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple
from config import Config
from core.entities import Hoop, Player, Vector2, VolleyBall
from core.game_logic.utility_logic import UtilityLogic
from computer_player.computer_player_utility.kinematics import decay_table, first_throw_tick
from computer_player.computer_player_utility.interception_calculator import InterceptionCalculator


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
    
    """
    def __init__(
            self,
            throw_threshold_volleyball_holder: float,
            throw_threshold_loaded_beater: float
            ):
        """Store squared distance thresholds used by beater throw checks."""
        self.squared_throw_threshold_volleyball_holder = throw_threshold_volleyball_holder**2
        self.squared_throw_threshold_loaded_beater = throw_threshold_loaded_beater**2

    def should_throw_at_volleyball_holder(self, beater: Player, volleyball_holder: Player) -> bool:
        """Return True when holder is throwable and inside holder range threshold."""
        if volleyball_holder.dodgeball_immunity:
            return False
        squared_distance = UtilityLogic._squared_distance(beater.position, volleyball_holder.position)
        if squared_distance <= self.squared_throw_threshold_volleyball_holder:
            return True
        return False
    
    def should_throw_at_loaded_beater(self, beater: Player, loaded_beater: Player) -> bool:
        """Return True when a loaded opposing beater is within throw range."""
        squared_distance = UtilityLogic._squared_distance(beater.position, loaded_beater.position)
        if squared_distance <= self.squared_throw_threshold_loaded_beater:
            return True
        return False


class ThrowDirector:
    """Calculates the throw vector to a moving receiver e.g. for passes and beats"""
    @staticmethod
    def get_throw_direction_static_receiver(player: Player, receiver: Player):
        """Return direct throw vector from thrower to a static receiver position."""
        return  Vector2(
            receiver.position.x - player.position.x,
            receiver.position.y - player.position.y
        )

    @staticmethod
    def _prepare_linear_solve(player: Player, receiver: Player):
        """Prepare variables for linear solve of throw direction to moving receiver."""
        # assume ball starts at player position
        s_b_x = player.position.x
        s_b_y = player.position.y
        s_p_x = receiver.position.x
        s_p_y = receiver.position.y
        v_p_x = receiver.velocity.x
        v_p_y = receiver.velocity.y
        v_b_value_sq = player.throw_velocity**2
        root = math.sqrt(s_b_x**2*v_b_value_sq - s_b_x**2*v_p_y**2 + 2*s_b_x*s_b_y*v_p_x*v_p_y - 2*s_b_x*s_p_x*v_b_value_sq + 2*s_b_x*s_p_x*v_p_y**2 - 2*s_b_x*s_p_y*v_p_x*v_p_y + s_b_y**2*v_b_value_sq - s_b_y**2*v_p_x**2 - 2*s_b_y*s_p_x*v_p_x*v_p_y - 2*s_b_y*s_p_y*v_b_value_sq + 2*s_b_y*s_p_y*v_p_x**2 + s_p_x**2*v_b_value_sq - s_p_x**2*v_p_y**2 + 2*s_p_x*s_p_y*v_p_x*v_p_y + s_p_y**2*v_b_value_sq - s_p_y**2*v_p_x**2)

        return s_b_x, s_b_y, s_p_x, s_p_y, v_p_x, v_p_y, v_b_value_sq, root

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

        With MOTION_MODEL "analytic" the exact ball decay and receiver acceleration are used; if the
        ball cannot reach the receiver, it falls back to the constant velocity solution (throw anyway).
        """
        if Config.MOTION_MODEL == "analytic":
            throw_direction, _ = ThrowDirector._throw_analytic(player, receiver)
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
        s_b_x, s_b_y, s_p_x, s_p_y, v_p_x, v_p_y, v_b_value_sq, root = ThrowDirector._prepare_linear_solve(player, receiver)
        v_b_x = (-s_b_x*s_b_y*v_p_y + s_b_x*s_p_y*v_p_y - s_b_x*root + s_b_y**2*v_p_x + s_b_y*s_p_x*v_p_y - 2*s_b_y*s_p_y*v_p_x - s_p_x*s_p_y*v_p_y + s_p_x*root + s_p_y**2*v_p_x)/(s_b_x**2 - 2*s_b_x*s_p_x + s_b_y**2 - 2*s_b_y*s_p_y + s_p_x**2 + s_p_y**2) 
        v_b_y = (s_b_x**2*v_p_y - s_b_x*s_b_y*v_p_x - 2*s_b_x*s_p_x*v_p_y + s_b_x*s_p_y*v_p_x + s_b_y*s_p_x*v_p_x - s_b_y*root + s_p_x**2*v_p_y - s_p_x*s_p_y*v_p_x + s_p_y*root)/(s_b_x**2 - 2*s_b_x*s_p_x + s_b_y**2 - 2*s_b_y*s_p_y + s_p_x**2 + s_p_y**2)
        # dt = -(s_b_x*v_p_x + s_b_y*v_p_y - s_p_x*v_p_x - s_p_y*v_p_y)/(v_b_value_sq - v_p_x**2 - v_p_y**2) + root/(v_b_value_sq - v_p_x**2 - v_p_y**2)
        # print('v_b_x', v_b_x)
        # print('v_b_y', v_b_y)
        # print('dt', dt)
        return Vector2(v_b_x, v_b_y)

    @staticmethod
    def get_throw_direction_and_position_moving_receiver(player: Player, receiver: Player):
        """
        Return throw vector and predicted receiver position for moving receiver.

        With MOTION_MODEL "analytic" the ball decay and the receiver's acceleration with its current
        stick input are modelled exactly; returns (None, None) if the ball cannot reach the receiver.
        """
        if Config.MOTION_MODEL == "analytic":
            return ThrowDirector._throw_analytic(player, receiver)
        s_b_x, s_b_y, s_p_x, s_p_y, v_p_x, v_p_y, v_b_value_sq, root = ThrowDirector._prepare_linear_solve(player, receiver)
        v_b_x = (-s_b_x*s_b_y*v_p_y + s_b_x*s_p_y*v_p_y - s_b_x*root + s_b_y**2*v_p_x + s_b_y*s_p_x*v_p_y - 2*s_b_y*s_p_y*v_p_x - s_p_x*s_p_y*v_p_y + s_p_x*root + s_p_y**2*v_p_x)/(s_b_x**2 - 2*s_b_x*s_p_x + s_b_y**2 - 2*s_b_y*s_p_y + s_p_x**2 + s_p_y**2) 
        v_b_y = (s_b_x**2*v_p_y - s_b_x*s_b_y*v_p_x - 2*s_b_x*s_p_x*v_p_y + s_b_x*s_p_y*v_p_x + s_b_y*s_p_x*v_p_x - s_b_y*root + s_p_x**2*v_p_y - s_p_x*s_p_y*v_p_x + s_p_y*root)/(s_b_x**2 - 2*s_b_x*s_p_x + s_b_y**2 - 2*s_b_y*s_p_y + s_p_x**2 + s_p_y**2)
        dt = -(s_b_x*v_p_x + s_b_y*v_p_y - s_p_x*v_p_x - s_p_y*v_p_y)/(v_b_value_sq - v_p_x**2 - v_p_y**2) + root/(v_b_value_sq - v_p_x**2 - v_p_y**2)
        predicted_receiver_position = Vector2(
            receiver.position.x + receiver.velocity.x * dt,
            receiver.position.y + receiver.velocity.y * dt
        )
        return Vector2(v_b_x, v_b_y), predicted_receiver_position

    @staticmethod
    def _throw_analytic(player: Player, receiver: Player) -> Tuple[Optional[Vector2], Optional[Vector2]]:
        """Throw vector (magnitude throw_velocity) and predicted receiver position via kinematics.first_throw_tick."""
        result = first_throw_tick(
            thrower_x=player.position.x,
            thrower_y=player.position.y,
            throw_velocity=player.throw_velocity,
            ball_table=decay_table(Config.BALL_DEACCELERATION_RATE),
            receiver=receiver,
            reach_distance=Config.THROW_CATCH_MARGIN_FACTOR * (receiver.radius + Config.VOLLEYBALL_RADIUS),
        )
        if result is None:
            return None, None
        _, receiver_x, receiver_y = result
        throw_x = receiver_x - player.position.x
        throw_y = receiver_y - player.position.y
        mag_throw = math.hypot(throw_x, throw_y)
        if mag_throw == 0:
            throw_x, throw_y = receiver.position.x - player.position.x, receiver.position.y - player.position.y
            mag_throw = math.hypot(throw_x, throw_y) or 1.0
        return (Vector2(throw_x / mag_throw * player.throw_velocity, throw_y / mag_throw * player.throw_velocity),
                Vector2(receiver_x, receiver_y))


class ScoreAttempter:
    """
    Decide whether the volleyball holder shoots and at which hoop.

    Shared by the base attack and the moves, so a player scores the same way
    no matter which of them currently steers it.
    """
    def __init__(self,
                 interception_calculator: InterceptionCalculator,
                 process_action_logic,
                 score_squared_max_distance: float,
                 scoring_threshold: float,
                 logger: Optional[logging.Logger] = None):
        """Store the interception model and the shot thresholds."""
        self.interception_calculator = interception_calculator
        self.process_action_logic = process_action_logic
        # only consider scoring on hoops within this squared distance from the volleyball, since far shots are unlikely to be good opportunities
        self.score_squared_max_distance = score_squared_max_distance
        self.scoring_threshold = scoring_threshold
        self.logger = logger or logging.getLogger("computer_player")

    def get_intercepting_scores_for_hoops(self,
                                          volleyball: VolleyBall,
                                          volleyball_holder: Player,
                                          attack_hoops: List[Hoop],
                                          defending_chaser_keeper_ids: List[str]) -> Dict[str, float]:
        """Compute interception-risk scores for shots toward each attack hoop."""
        intercepting_scores_dict = {}
        for hoop in attack_hoops:
            volleyball_hoop_vector = Vector2(
                hoop.position.x - volleyball.position.x,
                hoop.position.y - volleyball.position.y
            )
            squared_volleyball_hoop_distance = volleyball_hoop_vector.x**2 + volleyball_hoop_vector.y**2
            if squared_volleyball_hoop_distance > self.score_squared_max_distance:
                continue
            copy_volleyball = volleyball.copy()
            mag_volleyball_hoop_vector = math.sqrt(squared_volleyball_hoop_distance)
            copy_volleyball.velocity.x = volleyball_holder.throw_velocity * volleyball_hoop_vector.x / mag_volleyball_hoop_vector
            copy_volleyball.velocity.y = volleyball_holder.throw_velocity * volleyball_hoop_vector.y / mag_volleyball_hoop_vector
            beam_cosine_angle, beam_cosine_angle_player_id, _ = self.interception_calculator.beam_cosine_angle(
                moving_entity=copy_volleyball,
                intercepting_player_ids=defending_chaser_keeper_ids,
                target_position=hoop.position,
                moving_entity_target_vector=volleyball_hoop_vector)
            intercepting_score = self.interception_calculator.interception_score_from_beam_cosine_angle(
                beam_cosine_angle=beam_cosine_angle,
                beam_angle_player_id=beam_cosine_angle_player_id,
                mag_moving_entity_velocity=volleyball_holder.throw_velocity,
            )
            intercepting_scores_dict[hoop.id] = intercepting_score
        return intercepting_scores_dict

    def attempt(self,
                volleyball: VolleyBall,
                volleyball_holder: Player,
                attack_hoops: List[Hoop],
                defending_chaser_keeper_ids: List[str]) -> bool:
        """Shoot when interception risk for a hoop is below threshold. Returns True if a shot was taken."""
        intercepting_scores_dict = self.get_intercepting_scores_for_hoops(volleyball, volleyball_holder, attack_hoops, defending_chaser_keeper_ids)
        # if no intercepting_scores, then probably to far away to score
        if len(intercepting_scores_dict) == 0:
            return False
        # get hoop with highest interception score (lowest chance of being intercepted)
        best_hoop_id = min(intercepting_scores_dict, key=intercepting_scores_dict.get)
        best_score = intercepting_scores_dict[best_hoop_id]
        if best_score > self.scoring_threshold:
            self.logger.info("Scoring on hoop %s with interception score %s", best_hoop_id, best_score)
            best_hoop = next(hoop for hoop in attack_hoops if hoop.id == best_hoop_id)
            volleyball_holder.direction = Vector2(
                best_hoop.position.x - volleyball_holder.position.x,
                best_hoop.position.y - volleyball_holder.position.y
            )
            self.process_action_logic.process_throw_action(volleyball_holder.id)
            return True
        return False


@dataclass
class PassOption:
    """A pass that reaches its receiver without crossing the passer's own hoops."""
    receiver_id: str
    throw_direction: Vector2
    predicted_receiver_position: Vector2
    interception_score: float # the larger, the less likely the pass is intercepted (>= 1 outside the interception cone)


class PassEvaluator:
    """
    Rate pass receivers and check single passes.

    Shared by the base attack and the moves, so both use the same pass-to-player
    score (position penalty) and the same interception model.
    """
    def __init__(self,
                 interception_calculator: InterceptionCalculator,
                 passing_evade_vector_position_penalty_weight: float):
        """Store the interception model and the evade weight of the position penalty."""
        self.interception_calculator = interception_calculator
        self.passing_evade_vector_position_penalty_weight = passing_evade_vector_position_penalty_weight

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

        Returns None if the ball cannot reach the receiver or the throw would go through own hoops.
        """
        throw_direction, predicted_receiver_position = ThrowDirector.get_throw_direction_and_position_moving_receiver(volleyball_holder, receiver)
        if throw_direction is None:
            return None # ball cannot reach this player
        if InterceptionCalculator.intercepting_hoop_before_target(volleyball, predicted_receiver_position, own_hoops):
            return None
        # beam_cosine_angle normalizes throw_direction in place, which is then thrown as is
        beam_cosine_angle, beam_cosine_angle_player_id, _ = self.interception_calculator.beam_cosine_angle(
            moving_entity=volleyball,
            intercepting_player_ids=defending_chaser_keeper_ids,
            target_position=predicted_receiver_position,
            moving_entity_target_vector=throw_direction
        )
        interception_score = self.interception_calculator.interception_score_from_beam_cosine_angle(
            beam_cosine_angle=beam_cosine_angle,
            beam_angle_player_id=beam_cosine_angle_player_id,
            mag_moving_entity_velocity=volleyball_holder.throw_velocity,
        )
        return PassOption(receiver.id, throw_direction, predicted_receiver_position, interception_score)
