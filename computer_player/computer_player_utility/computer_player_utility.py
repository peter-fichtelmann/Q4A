import math
from core.entities import Player, Vector2
from core.game_logic.utility_logic import UtilityLogic


class MoveUtility:
    """Helper functions for movement and boundary-safe steering."""

    @staticmethod
    def evade(player_position: Vector2, entity_to_evade_position: Vector2, weight: float = 1.0) -> Vector2:
        """Return an inverse-distance weighted vector away from another entity."""
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
