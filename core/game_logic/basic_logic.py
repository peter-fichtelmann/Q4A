import logging
from core.game_state import GameState
from core.entities import Player, Ball, VolleyBall, DodgeBall, Vector2, PlayerRole, BallType

logger = logging.getLogger('quadball.game_logic')

class BasicLogic:
    """
    Handles baseline movement, velocity updates, and ball collisions.

    Attributes:
        state: Shared GameState instance for entity access and configuration.
        penalty_logic: Optional PenaltyLogic for turnover decisions.
    """

    def __init__(self, game_state: GameState, penalty_logic=None):
        """
        Initialize the basic movement and physics logic.

        Args:
            game_state: The active GameState instance.
            penalty_logic: Optional PenaltyLogic dependency for turnovers.
        """
        self.state = game_state
        self.penalty_logic = penalty_logic

    def update_player_velocity(self, player: Player, dt: float):
        # norm player.direction
        mag_dir = (player.direction.x**2 + player.direction.y**2) ** 0.5
        # on stick reset check before direction norm
        if player.is_knocked_out and (mag_dir < player.radius + self.state.hoops[f'hoop_{player.team}_center'].thickness):
            player.is_knocked_out = False
            logger.info(f"Player {player.id} has recovered from knockout")
        if mag_dir > 1:
            player.direction.x /= mag_dir
            player.direction.y /= mag_dir
        player.velocity.x = player.velocity.x + ( - player.deacceleration_rate * player.velocity.x + player.direction.x * player.acceleration) * dt
        player.velocity.y = player.velocity.y + ( - player.deacceleration_rate * player.velocity.y + player.direction.y * player.acceleration) * dt
        
        # Cap speed
        speed = (player.velocity.x**2 + player.velocity.y**2) ** 0.5
        if speed > player.max_speed:
            scale = player.max_speed / speed
            player.velocity.x *= scale
            player.velocity.y *= scale
        elif (speed < player.min_speed) and (mag_dir < player.min_dir):
            player.velocity.x = 0
            player.velocity.y = 0
        # print('speed', (player.velocity.x**2 + player.velocity.y**2) ** 0.5)

    def update_player_velocities(self, dt: float) -> None:
        """
        Update player velocities based on their current direction and role.
        
        Handles special behaviors such as:
        - Knocked out players moving toward their team's hoop for recovery
        - Dead volleyball keeper movement toward midline
        - Inbounding players pursuing the ball
        - Standard acceleration/deceleration based on direction input
        
        Args:
            dt: Delta game time (game time since last frame) in seconds
        """
        volleyball = self.state.get_volleyball()
        for player in self.state.players.values():
            # Update player velocity based on direction and current state
            
            if player.is_knocked_out:
                player.direction.x = self.state.hoops[f'hoop_{player.team}_center'].position.x - player.position.x
                player.direction.y = self.state.hoops[f'hoop_{player.team}_center'].position.y - player.position.y
            elif volleyball is not None:
                if volleyball.is_dead:
                    if volleyball.possession_team == player.team and player.role == PlayerRole.KEEPER:
                        if volleyball.holder_id is None:
                            player.direction.x = volleyball.position.x - player.position.x
                            player.direction.y = volleyball.position.y - player.position.y
                        else:
                            # fastest way back to midline
                            if player.team == self.state.team_0: 
                                player.direction.x = -1
                            else:
                                player.direction.x = 1
                            player.direction.y = 0
            if player.inbounding is not None: # inbounding
                ball = self.state.balls[player.inbounding]
                if ((ball.position.x - player.position.x)**2 + (ball.position.y - player.position.y)**2) > (player.radius + ball.radius) **2:
                    # not reached ball during inbounding
                    player.direction.x = ball.position.x - player.position.x
                    player.direction.y = ball.position.y - player.position.y
                else:
                    # perpendicular inbounding direction or 45 degree angle away from boundary if on corner
                    player.direction.x = 0
                    player.direction.y = 0
                    if ball.position.x <= self.state.boundaries_x[0] + player.radius: # left boundary
                        player.direction.x += 1
                    elif ball.position.x >= self.state.boundaries_x[1] - player.radius: # right boundary
                        player.direction.x -= 1
                    if ball.position.y <= self.state.boundaries_y[0] + player.radius: # bottom boundary
                        player.direction.y += 1
                    elif ball.position.y >= self.state.boundaries_y[1] - player.radius: # top boundary
                        player.direction.y -= 1
                    logger.debug(f"Inbounding direction: ({player.direction.x}, {player.direction.y})")
                    player.velocity.x = 0
                    player.velocity.y = 0
                    ball = self.state.balls[player.inbounding]
                    ball.inbounder = None
                    player.inbounding = None
                    player.dodgeball_immunity = False
                    logger.info("Inbounding procedure ended by ball re-entering pitch")
            self.update_player_velocity(player, dt)

    def get_free_ball_velocity(self, ball: Ball, dt: float) -> Vector2:
        """Update a ball's velocity based on its current velocity and friction."""
        velocity = Vector2(ball.velocity.x - ball.deacceleration_rate * ball.velocity.x * dt,
                           ball.velocity.y - ball.deacceleration_rate * ball.velocity.y * dt)
        return velocity

    def update_ball_velocities(self, dt: float) -> None:
        """
        Update ball velocities based on friction or holder's movement.
        
        If a ball is not held:
            - Apply deceleration to simulate friction/air resistance
        If a ball is held by a player:
            - Ball velocity matches the holder's velocity exactly
        
        Args:
            dt: Delta game time (game time since last frame) in seconds
        """
        for ball in self.state.balls.values():
            if ball.turnover_to_player is not None:
                logger.debug(f"Ball turnover to player velocity: {ball.turnover_to_player}")
                player = self.state.players.get(ball.turnover_to_player)
                # reset turnover to other eligible player if player unavailable
                if player is None:
                    self.penalty_logic._designate_turnover(ball)
                elif player.is_knocked_out:
                    self.penalty_logic._designate_turnover(ball)
                player = self.state.players.get(ball.turnover_to_player)
                if player is not None:
                    if not player.is_knocked_out:
                        ball.velocity.x = player.position.x - ball.position.x
                        ball.velocity.y = player.position.y - ball.position.y
                        mag_dir = (ball.velocity.x**2 + ball.velocity.y**2) ** 0.5
                        if mag_dir > player.throw_velocity:
                            ball.velocity.x = ball.velocity.x / mag_dir * player.throw_velocity
                            ball.velocity.y = ball.velocity.y / mag_dir * player.throw_velocity  
            elif ball.holder_id is None:
                # Free balls experience friction/deceleration
                ball.velocity = self.get_free_ball_velocity(ball, dt)
                # if dodgeball below threshold then dead
                if ball.ball_type == BallType.DODGEBALL:
                    squared_velocity_mag = (ball.velocity.x**2 + ball.velocity.y**2)
                    if squared_velocity_mag < ball.dead_velocity_threshold **2:
                        ball.possession_team = None                    
            else:
                # Held balls move with the player holding them
                holder = self.state.get_player(ball.holder_id)
                if holder:
                    ball.velocity.x = holder.velocity.x
                    ball.velocity.y = holder.velocity.y

    def get_update_position(self, entity: object, dt: float) -> Vector2:
        """Update position of a player or ball based on its velocity."""
        return Vector2(entity.position.x + entity.velocity.x * dt,
                       entity.position.y + entity.velocity.y * dt)

    def update_positions(self, dt: float) -> None:
        """Update positions of players and balls based on their velocities."""
        for player in self.state.players.values():
            player.previous_position.x = player.position.x
            player.previous_position.y = player.position.y
            player.position = self.get_update_position(player, dt)
            # print(f'Player {player.id} position: {player.position.x}, {player.position.y}')
            if player.role == PlayerRole.KEEPER: # dodgeball immunity if keeper in keeper zone
                if (
                    (player.team == self.state.team_0 and self.state.keeper_zone_x_0 >= player.position.x - player.radius)
                    or
                    (player.team == self.state.team_1 and player.position.x <= self.state.keeper_zone_x_1 + player.radius)
                ):
                    player.dodgeball_immunity = True
                else:
                    player.dodgeball_immunity = False
            if player.catch_cooldown > dt:
                player.catch_cooldown -= dt
            else:
                player.catch_cooldown = 0.0
        
        for ball in self.state.balls.values():
            ball.previous_position.x = ball.position.x
            ball.previous_position.y = ball.position.y
            ball.position = self.get_update_position(ball, dt)


    
    def _check_ball_collisions(self):
        """
        Detect and resolve collisions between balls.
        
        Only processes collisions between free (unheld) balls. When two balls
        collide, their velocities are reflected along the collision normal and
        adjusted based on their relative speeds to create realistic bouncing.
        
        Handles edge cases:
        - One stationary ball: Transfers moving ball's velocity to stationary one
        - Both stationary: No collision processing (prevents unnecessary computation)
        - Zero collision normal: Skips to avoid division by zero
        """
        # Check if balls are close enough to other balls to collide
        balls = list(self.state.balls.values())
        for i, ball_1 in enumerate(balls):
            if ball_1.is_dead if hasattr(ball_1, "is_dead") else False:
                continue # dead balls do not collide
            if ball_1.turnover_to_player is not None:
                continue # balls in turnover do not collide
            for ball_2 in balls[i+1:]:
                if ball_2.is_dead if hasattr(ball_2, "is_dead") else False:
                    continue # dead balls do not collide
                if ball_2.turnover_to_player is not None:
                    continue # balls in turnover do not collide
                if ball_1.holder_id is not None or ball_2.holder_id is not None:
                    continue # only check free balls
                # dist_sq = GameLogic._squared_distance(ball_1.position, ball_2.position)
                dist_sq = self.state.squared_distances_dicts[ball_1.id][ball_2.id]
                collision_dist_sq = (ball_1.radius + ball_2.radius) ** 2
                if dist_sq < collision_dist_sq:
                    # Collision occurred
                    ball_1_velocity_mag = (ball_1.velocity.x**2 + ball_1.velocity.y**2) ** 0.5
                    ball_2_velocity_mag = (ball_2.velocity.x**2 + ball_2.velocity.y**2) ** 0.5
                    if ball_1_velocity_mag == 0 and ball_2_velocity_mag == 0:
                        continue # avoid divide by zero
                    if ball_1_velocity_mag == 0:
                        ball_1.velocity.x = ball_2.velocity.x
                        ball_1.velocity.y = ball_2.velocity.y
                        ball_2.velocity.x = 0
                        ball_2.velocity.y = 0
                        continue
                    if ball_2_velocity_mag == 0:
                        ball_2.velocity.x = ball_1.velocity.x
                        ball_2.velocity.y = ball_1.velocity.y
                        ball_1.velocity.x = 0
                        ball_1.velocity.y = 0
                        continue # avoid divide by zero
                    normal = Vector2(
                        ball_2.position.x - ball_1.position.x,
                        ball_2.position.y - ball_1.position.y
                    )
                    normal_mag = (normal.x**2 + normal.y**2) ** 0.5
                    if normal_mag == 0:
                        continue # avoid divide by zero
                    normal.x /= normal_mag
                    normal.y /= normal_mag
                    # Reflect velocities
                    ball_1.velocity = ball_1.velocity.reflect(normal)
                    ball_2.velocity = ball_2.velocity.reflect(Vector2(-normal.x, -normal.y))
                    mag_velocity_ratio = ball_1_velocity_mag / ball_2_velocity_mag
                    ball_1.velocity.x *= 1 / mag_velocity_ratio
                    ball_1.velocity.y *= 1 / mag_velocity_ratio
                    ball_2.velocity.x *= mag_velocity_ratio
                    ball_2.velocity.y *= mag_velocity_ratio
                    logger.debug(f"Ball {ball_1.id} collided with Ball {ball_2.id}")
