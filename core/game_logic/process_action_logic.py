from core.game_state import GameState
from core.entities import Player, Ball, VolleyBall, DodgeBall, Vector2, PlayerRole, BallType

class ProcessActionLogic:
    """
    Processes player action inputs such as throwing and tackling.

    Attributes:
        state: Shared GameState instance for player and ball updates.
    """

    def __init__(self, game_state: GameState):
        """
        Initialize action processing logic.

        Args:
            game_state: The active GameState instance.
        """
        self.state = game_state

    def process_throw_action(self, player_id: str) -> bool:
        """
        Process a throw action by a player.
        
        When a player throws:
        - Ball is released from their possession
        - Ball velocity is set based on player's throw velocity and current direction
        - Catch cooldown is imposed (prevents immediately re-catching the ball)
        - Ball's previous_thrower_id is recorded (prevents bouncing off thrower immediately (dodgeballs only))
        
        Args:
            player_id: The ID of the player throwing the ball
            
        Returns:
            True if throw was successful, False if player has no ball or doesn't exist
        """
        player = self.state.get_player(player_id)
        if not player or not player.has_ball:
            return False
        
        ball = self.state.get_ball(player.has_ball)
        if not ball:
            return False
        
        # Release the ball; copy player's position so the ball doesn't share the same Vector2
        ball.previous_thrower_id = player.id # so dodgeball not bouncing off from thrower immediately
        ball.holder_id = None
        mag_dir = (player.direction.x**2 + player.direction.y**2) ** 0.5
        if mag_dir > 1:
            player.direction.x /= mag_dir
            player.direction.y /= mag_dir
        ball.velocity.x = player.throw_velocity * player.direction.x
        ball.velocity.y = player.throw_velocity * player.direction.y
        mag_velocity = (ball.velocity.x**2 + ball.velocity.y**2) ** 0.5
        # Prevent divide-by-zero if mag_velocity is (unexpectedly) zero
        if mag_velocity > 1e-2:
            player.catch_cooldown = 2 * player.radius / mag_velocity * player.max_speed * 2.5  # Prevent immediate re-catch with buffer
        else:
            player.catch_cooldown = 0.0
        player.has_ball = False

        print(f"[GAME] Player {player_id} threw {ball.id}")
        return True
    
    def process_tackle_action(self, player_id: str) -> bool:
        """
        Process a tackle action (currently unimplemented).
        
        Placeholder for future tackling/blocking mechanics.
        TODO: Implement tackle logic
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
                                player.tackling_player_ids.append(other_id)
                                other_player.tackling_player_ids.append(player.id)
                                print(f"[GAME] Player {player_id} tackled player {other_id}")
                                return True
        return False