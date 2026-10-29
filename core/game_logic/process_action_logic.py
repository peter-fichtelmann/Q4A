import logging
import math
from typing import Callable, Optional
from core.game_logic.utility_logic import UtilityLogic
from core.game_state import GameState, ThrowCharge
from core.entities import Player, Ball, VolleyBall, DodgeBall, Vector2, PlayerRole, BallType

BASE_LOGGER = logging.getLogger('quadball.game_logic')

class ProcessActionLogic:
    """
    Processes player action inputs such as throwing and tackling.

    Attributes:
        state: Shared GameState instance for player and ball updates.
    """

    def __init__(self, game_state: GameState, logger: logging.Logger | None = None):
        """
        Initialize action processing logic.

        Args:
            game_state: The active GameState instance.
        """
        self.state = game_state
        self.logger = logger or BASE_LOGGER
        # (player, strength ratio) -> direction of a charged throw started without one, fixed at the start of the charge,
        # e.g. the throw assist of the human steering the player; None (or a None result): the player's direction
        self.throw_direction_provider: Optional[Callable[[Player, float], Optional[Vector2]]] = None

    def can_throw(self, player: Optional[Player]) -> bool:
        """Whether `player` holds a ball it may throw right now."""
        if not player or not player.has_ball:
            return False
        ball = self.state.get_ball(player.has_ball)
        if not ball:
            return False
        if self.state.game_time < self.state.throw_blocked_until.get(player.id, float('-inf')):
            # just received a turnover ball: a tackler still pressing the tackle (= throw) button must not throw it away
            return False
        if ball.ball_type == BallType.VOLLEYBALL and ball.is_dead:
            # throwing dead volleyball is not allowed
            return False
        return True

    def process_throw_action(self, player_id: str, throw_direction: Optional[Vector2] = None, strength_ratio: float = 1.0) -> bool:
        """
        Process a throw action by a player.

        When a player throws:
        - Ball is released from their possession
        - Ball velocity is set based on player's throw velocity, the strength ratio and current direction
        - Catch cooldown is imposed (prevents immediately re-catching the ball)
        - Ball's previous_thrower_id is recorded (prevents bouncing off thrower immediately (dodgeballs only))

        Args:
            player_id: The ID of the player throwing the ball
            throw_direction: The direction in which the ball is thrown
            strength_ratio: Fraction of the full throw velocity (1: full velocity), from charging the throw
        Returns:
            True if throw was successful, False if player has no ball or doesn't exist
        """
        player = self.state.get_player(player_id)
        self.state.throw_charges.pop(player_id, None)
        if not self.can_throw(player):
            return False
        ball = self.state.get_ball(player.has_ball)

        # Release the ball; copy player's position so the ball doesn't share the same Vector2
        ball.previous_thrower_id = player.id # so dodgeball not bouncing off from thrower immediately
        ball.holder_id = None
        if throw_direction is None:
            throw_direction = player.direction
        mag_dir = UtilityLogic._magnitude(throw_direction)
        throw_velocity = self.effective_throw_velocity(player) * strength_ratio
        if mag_dir > 1:
            throw_direction.x /= mag_dir
            throw_direction.y /= mag_dir
            mag_velocity = throw_velocity # mag velocity should be same as player throw velocity because throw direction is normalized
        else:
            mag_velocity = throw_velocity * mag_dir # if throw direction is not normalized, scale velocity by mag_dir to prevent faster throws in diagonal directions

        ball.velocity.x = throw_velocity * throw_direction.x
        ball.velocity.y = throw_velocity * throw_direction.y
        # mag_velocity = UtilityLogic._calculate_magnitude(ball.velocity)
        # Prevent divide-by-zero if mag_velocity is (unexpectedly) zero
        if mag_velocity > 1e-2:
            player.catch_cooldown = 2 * player.radius / mag_velocity * player.max_speed * 2.5  # Prevent immediate re-catch with buffer
        else:
            player.catch_cooldown = 0.0
        player.has_ball = False

        self.logger.info("Player %s threw %s with strength %.1f", player_id, ball.id, strength_ratio)
        return True

    def is_charging_throw(self, player_id: str) -> bool:
        """Whether `player_id` is charging a throw (the ball is still held)."""
        return player_id in self.state.throw_charges

    @staticmethod
    def min_strength_ratio(player: Player) -> float:
        """Strength of an uncharged throw: the ball leaves at the player's max speed."""
        throw_velocity = ProcessActionLogic.effective_throw_velocity(player)
        return min(1.0, player.max_speed / throw_velocity) if throw_velocity > 0 else 1.0

    @staticmethod
    def charged_strength_ratio(player: Player, ticks: int, full_ticks: int) -> float:
        """Strength after `ticks` of charging: from min_strength_ratio (0 ticks) up to 1 (full_ticks)."""
        min_ratio = ProcessActionLogic.min_strength_ratio(player)
        return min_ratio + (1 - min_ratio) * min(ticks, full_ticks) / full_ticks

    def charge_ticks_for_strength(self, player: Player, strength_ratio: float) -> int:
        """Ticks of charging a throw of `strength_ratio` takes (0: thrown at once with min_strength_ratio)."""
        full_ticks = self.state.throw_charge_full_ticks
        min_ratio = self.min_strength_ratio(player)
        if min_ratio >= 1:
            return 0
        return min(full_ticks, max(0, math.ceil((strength_ratio - min_ratio) / (1 - min_ratio) * full_ticks - 1e-9)))

    def start_throw_charge(self,
                           player_id: str,
                           throw_direction: Optional[Vector2] = None,
                           strength_ratio: float = 1.0) -> bool:
        """
        Start charging a throw: it fills one tick per update (process_throw_charges) and the ball leaves
        once the charge reaches `strength_ratio` (rounded up to whole ticks), or when a human lets go
        (release_throw_charge). A strength that needs no tick (charged_strength_ratio) is thrown at once.

        The aim is fixed now: `throw_direction`, or else the throw_direction_provider's direction for a
        full-strength throw, or else the player's current direction.

        Returns False if the player cannot throw or already charges a throw.
        """
        player = self.state.get_player(player_id)
        if player_id in self.state.throw_charges or not self.can_throw(player):
            return False
        if throw_direction is None and self.throw_direction_provider is not None:
            throw_direction = self.throw_direction_provider(player, 1.0)
        if throw_direction is None:
            throw_direction = player.direction.copy()
        charge = ThrowCharge(
            ball_id=player.has_ball,
            release_ticks=self.charge_ticks_for_strength(player, strength_ratio),
            direction=throw_direction,
        )
        if charge.release_ticks == 0:
            return self._throw_charged(player_id, charge)
        self.state.throw_charges[player_id] = charge
        return True

    def release_throw_charge(self, player_id: str) -> bool:
        """
        A human let go of the throw action: throw with the strength charged so far (min_strength_ratio
        without a single tick yet). Returns whether the ball was thrown.
        """
        charge = self.state.throw_charges.get(player_id)
        if charge is None:
            return False
        return self._throw_charged(player_id, charge)

    def cancel_throw_charge(self, player_id: str) -> None:
        """Drop a throw being charged without throwing (e.g. another player takes control)."""
        self.state.throw_charges.pop(player_id, None)

    def process_throw_charges(self) -> None:
        """
        Fill every throw being charged by one tick, at the end of each update, and release it once it
        reaches its release ticks. A charge ends without a throw if the player no longer holds its ball.
        """
        for player_id, charge in list(self.state.throw_charges.items()):
            player = self.state.get_player(player_id)
            if player is None or player.has_ball != charge.ball_id or player.is_knocked_out:
                del self.state.throw_charges[player_id]
                continue
            charge.ticks = min(charge.ticks + 1, self.state.throw_charge_full_ticks)
            if charge.ticks >= charge.release_ticks:
                self._throw_charged(player_id, charge)

    def _throw_charged(self, player_id: str, charge: ThrowCharge) -> bool:
        """Throw a charged ball with its charged strength in the direction fixed at the start of the charge."""
        player = self.state.get_player(player_id)
        if player is None:
            self.state.throw_charges.pop(player_id, None)
            return False
        strength_ratio = self.charged_strength_ratio(player, charge.ticks, self.state.throw_charge_full_ticks)
        return self.process_throw_action(player_id, charge.direction, strength_ratio)

    @staticmethod
    def effective_throw_velocity(player: Player) -> float:
        """Throw velocity of `player` right now: tackled players throw at half velocity."""
        if player.tackling_player_ids:
            return 0.5 * player.throw_velocity
        return player.throw_velocity

    def process_tackle_action(self, player_id: str) -> bool:
        """
        Attempt a tackle against an opposing in-contact ball carrier.

        A tackle is registered when:
        - The acting player exists and is not currently carrying a ball
        - At least one contacted player is on the opposing team
        - The opposing contacted player is currently carrying a ball
        - The opposing contacted player is not tackle immune (stalled volleyball turnover receiver)

        On success both players receive each other in their tackling lists so
        `_enforce_tackle` can freeze movement for the frame.

        Args:
            player_id: The ID of the tackling player.

        Returns:
            True if a valid tackle target was found, otherwise False.
        """
        player = self.state.get_player(player_id)
        # for other_id, distance in self.state.squared_distances.get(player.id, [])
        #     if other_id in self.state.players.keys():
        #         other_player = self.state.players[other_id]
        #         if other_player.team != player.team:
        #             if not other_player.is_knocked_out:
        #                 if (
        #                     player.role == other_player.role
        #                 ) or (
        #                     player.role == PlayerRole.CHASER and other_player.role == PlayerRole.KEEPER
        #                 ) or (
        #                     player.role == PlayerRole.KEEPER and other_player.role == PlayerRole.CHASER
        #                 ):
        #                     if distance < (player.radius + other_player.radius) ** 2:
        #                         print(f"[GAME] Player {player_id} tackled player {other_id}")
        if not player.has_ball:
            if len(player.in_contact_player_ids) > 0:
                for other_id in player.in_contact_player_ids:
                    if other_id in self.state.players.keys():
                        other_player = self.state.players[other_id]
                        # only tackling player with ball allowed
                        if other_player.has_ball:
                            if other_player.team != player.team:
                                if self.state.game_time < self.state.tackle_immune_until.get(other_id, float('-inf')):
                                    continue # just received a stalled volleyball turnover
                                player.tackling_player_ids.append(other_id)
                                other_player.tackling_player_ids.append(player.id)
                                self.logger.debug("Player %s tackled player %s", player_id, other_id)
                                return True
        return False

    def process_holding_tackles(self) -> None:
        """Attempt a tackle for every player holding the tackle (`is_holding_tackle`), each frame after the collision check."""
        for player in self.state.players.values():
            if player.is_holding_tackle and not player.is_knocked_out:
                self.process_tackle_action(player.id)


    def can_claim(self, player: Player) -> bool:
        """
        Whether a player may start claiming the third dodgeball.

        Only a beater of the team the third dodgeball is assigned to can claim,
        while not knocked out, not holding a ball, and only if no other beater
        is already claiming.
        """
        if self.state.third_dodgeball is None or self.state.third_dodgeball_team is None:
            return False
        if player.role != PlayerRole.BEATER or player.team != self.state.third_dodgeball_team:
            return False
        if player.is_knocked_out or player.has_ball or player.is_claiming:
            return False
        for other_player in self.state.players.values():
            # only one claiming beater at a time
            if other_player.is_claiming:
                return False
        return True

    def process_claiming(self, player_id: str) -> bool:
        """
        Start claiming the third dodgeball.

        The claiming beater runs straight to the third dodgeball until picking it
        up or the third dodgeball situation ends, is immune to dodgeballs while
        claiming and gets a free way from other beaters.

        Args:
            player_id: The ID of the beater claiming.

        Returns:
            True if the claim started, otherwise False.
        """
        player = self.state.get_player(player_id)
        if player is None or not self.can_claim(player):
            return False
        player.is_claiming = True
        player.dodgeball_immunity = True
        self.logger.info("Player %s claims third dodgeball %s", player.id, self.state.third_dodgeball)
        return True

    @staticmethod
    def end_claim(player: Player) -> None:
        """End a claim and drop the immunity it granted."""
        if player.is_claiming:
            player.is_claiming = False
            player.dodgeball_immunity = False
