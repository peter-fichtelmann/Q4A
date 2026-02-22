import logging
import random
from core.game_state import GameState
from core.entities import Player, Ball, VolleyBall, DodgeBall, Vector2, PlayerRole, BallType
from typing import Optional

logger = logging.getLogger('quadball.game_logic')

class BoundaryLogic:
    """
    Enforces play area boundaries, hoop blockage, and inbounding free ways.

    Attributes:
        state: Shared GameState instance used for boundary checks and entities.
    """

    def __init__(self, game_state: GameState):
        """
        Initialize boundary rule handling.

        Args:
            game_state: The active GameState instance.
        """
        self.state = game_state

    def _enforce_hoop_blockage(self) -> None:
        """
        Prevent chasers from getting too close to their own hoops (no goaltending).
        
        Chasers that stray too close to their team's hoop are pushed back outside
        the protected area. Only applies to non-knocked-out players who are not currently inbounding.
        
        Protected zone: hoop center ± (player_radius + volleyball_radius)
        """
        # Only for players which are not knocked out
        # if player in same team as hoop and within player.radius of the square of hoop thickness and hoop radius
        # reset position to previous position
        volleyball = self.state.get_volleyball()
        for player in self.state.players.values():
            if player.role == PlayerRole.CHASER:
                for hoop in self.state.hoops.values():
                    if hoop.team == player.team:
                        if player.inbounding is None:
                            if not player.is_knocked_out: # knocked out players can reset
                                if player.team == self.state.team_0:
                                    if not (
                                        (player.position.x < hoop.position.x + player.radius + volleyball.radius) and (player.position.x > hoop.position.x - player.radius - volleyball.radius)
                                    ):
                                        continue # not close enough own hoops 
                                elif player.team == self.state.team_1:
                                    if not (
                                        (player.position.x > hoop.position.x - player.radius - volleyball.radius) and (player.position.x < hoop.position.x + player.radius + volleyball.radius)
                                    ):
                                        continue # not close enough own hoops
                                if (player.position.y < hoop.position.y + hoop.radius) and (player.position.y > hoop.position.y - hoop.radius):
                                    # reset x position to outside hoop area
                                    if player.position.x < hoop.position.x:
                                        reset_vector = hoop.position.x - player.radius - volleyball.radius - player.position.x
                                        player.position.x = hoop.position.x - player.radius - volleyball.radius
                                    else:
                                        reset_vector = hoop.position.x + player.radius + volleyball.radius - player.position.x
                                        player.position.x = hoop.position.x + player.radius + volleyball.radius
                                    player.velocity.x = 0
                                    player.velocity.y = 0
                                    if player.has_ball:
                                        ball = self.state.get_ball(player.has_ball)
                                        if ball:
                                            ball.position.x = ball.position.x + reset_vector
                                            ball.velocity.x = 0
                                            ball.velocity.y = 0
                                    for contact_player_id in player.in_contact_player_ids:
                                        contact_player = self.state.players[contact_player_id]
                                        contact_player.position.x = contact_player.position.x + reset_vector
                                    break
                                # print(f'Player {player.id} blocked from going too close to own hoop')

    def _enforce_pitch_boundaries(self) -> None:
        """
        Enforce pitch boundary constraints for all entities.
        
        Ensures no entity moves beyond the play area. When an entity exceeds boundaries:
        - Position is clamped to stay within bounds (accounting for entity radius)
        - Velocity is zeroed to prevent continued motion into boundary
        - Special handling for volleyball: Triggers inbounding procedure if out of bounds
        - Special handling for held volleyball: Drops ball and triggers inbounding
        
        This is called after all position updates to ensure physics doesn't
        push entities out of the play area.
        """        
        # Check all entities
        for moving_entity in list(list(self.state.players.values()) + list(self.state.balls.values())):
            new_position_x = min(max(self.state.boundaries_x[0] + moving_entity.radius, moving_entity.position.x), self.state.boundaries_x[1] - moving_entity.radius)
            new_position_y = min(max(self.state.boundaries_y[0] + moving_entity.radius, moving_entity.position.y), self.state.boundaries_y[1] - moving_entity.radius)
            if new_position_x != moving_entity.position.x or new_position_y != moving_entity.position.y:
                # print('boundary enforcement for entity', moving_entity.id, new_position_x, moving_entity.position.x, new_position_y, moving_entity.position.y)
                if hasattr(moving_entity, "ball_type"):
                    # ball
                    # stopp balls at boundary
                    logger.debug(f"Ball {moving_entity.id} hit boundary at position ({moving_entity.position.x:.2f}, {moving_entity.position.y:.2f})")
                    moving_entity.velocity.x = 0
                    moving_entity.velocity.y = 0
                    if moving_entity.ball_type == BallType.VOLLEYBALL:
                        if moving_entity.holder_id is None and not moving_entity.is_dead:
                            # volleyball going out of bounds only if not hold
                            self._start_inbounding_procedure()
                if hasattr(moving_entity, "has_ball"):
                    # player
                    if moving_entity.has_ball:
                        ball = self.state.get_ball(moving_entity.has_ball)
                        if ball.ball_type == BallType.VOLLEYBALL:
                            # volleyball going out of bounds
                            logger.info("Volleyball going out of bounds at position where player out of bounds")
                            # Copy position values, don't share the same Vector2 object
                            ball.position.x = moving_entity.position.x
                            ball.position.y = moving_entity.position.y
                            moving_entity.has_ball = None
                            ball.holder_id = None
                            self._start_inbounding_procedure()

                    for contact_player_id in moving_entity.in_contact_player_ids:
                        reset_vector = Vector2(0, 0)
                        reset_vector.x = new_position_x - moving_entity.position.x
                        reset_vector.y = new_position_y - moving_entity.position.y
                        contact_player = self.state.players[contact_player_id]
                        contact_player.position.x += reset_vector.x
                        contact_player.position.y += reset_vector.y
                moving_entity.position.x = new_position_x
                moving_entity.position.y = new_position_y

    
    def _start_inbounding_procedure(self):
        """
        Start the inbounding procedure when volleyball goes out of bounds.
        
        Selects the nearest opposing team player (chaser or keeper) to inbound the ball:
        - Player must not already be inbounding another ball
        - Player must not be knocked out
        - Player must be on the opposing team
        - Only chasers and keepers can inbound (beaters cannot)
        
        Once started:
        - Inbounder becomes immune to dodgeball hits
        - Volleyball holder is cleared (ball becomes free)
        - Inbounder must travel to the ball and bring it back into play
        """
        volleyball = self.state.get_volleyball()
        if not volleyball:
            return
        elif volleyball.inbounder is not None:
            return  # Inbounding procedure already started
        # for other_id, distance in self._get_sorted_distances(volleyball.id).items():
        for other_id, distance in self.state.squared_distances.get(volleyball.id, []):
            if other_id in self.state.players.keys():
                player = self.state.players[other_id]
                if player.team != volleyball.possession_team: # inbounding player other team
                    if player.role == PlayerRole.CHASER or player.role == PlayerRole.KEEPER:
                        if player.inbounding is None:
                            if not player.has_ball:
                                if not player.is_knocked_out: # what happens if all chasers/keeper of team are knocked out?
                                    logger.info(f"Inbounding procedure started by player {player.id} for volleyball {volleyball.id}")
                                    player.inbounding = volleyball.id
                                    player.dodgeball_immunity = True # chaser/keeper immune while inbounding
                                    volleyball.inbounder = player.id
                                    volleyball.holder_id = None
                                    break

    def _inbounding_free_way(self, dt: float) -> None:
        """
        Create and enforce a free zone around the inbounder and volleyball.
        
        Ensures opponents cannot interfere with the inbounding player by:
        - Moving nearby players away from the inbounder (priority)
        - Moving nearby players away from the volleyball (secondary)
        - Removing velocity component toward the inbounder/ball
        - Adding small perpendicular velocity if players would deadlock
        
        Free zone radius: 4× player radius (approximate)
        
        This allows the inbounder time and space to retrieve the ball without
        being immediately influenced by opponents.
        
        Args:
            dt: Delta game time since last frame in seconds
        """
        volleyball = self.state.get_volleyball()
        if not volleyball:
            return
        elif volleyball.inbounder is None:
            return # volleyball not inbound procedure
        inbounding_player = self.state.get_player(volleyball.inbounder)
        if not inbounding_player:
            return
        
        # Track players that need to be moved and their movement vectors
        players_to_move = {}
        normals_players_to_move = {}
        
        # Check players too close to inbounding player
        # for other_id, distance in self._get_sorted_distances(inbounding_player.id).items():
        for other_id, distance in self.state.squared_distances.get(inbounding_player.id, []):
            if other_id in self.state.players.keys():
                other_player = self.state.players[other_id]
                if distance < (4 * (other_player.radius)) ** 2:
                    move_away_speed = other_player.max_speed
                    move_vector, normal = self._calculate_move_away_vector(inbounding_player, other_player, dt, move_away_speed)
                    if move_vector is not None:
                        players_to_move[other_id] = move_vector
                        normals_players_to_move[other_id] = normal
                else:
                    break
        
        # Check players too close to volleyball (but prioritize moving away from inbounding player)
        # for other_id, distance in self._get_sorted_distances(volleyball.id).items():
        for other_id, distance in self.state.squared_distances.get(volleyball.id, []):
            if other_id in self.state.players.keys():
                if other_id != inbounding_player.id:
                    other_player = self.state.players[other_id]
                    if distance < (4 * (other_player.radius)) ** 2:
                        # Only move away from volleyball if not already moving away from inbounding player
                        move_away_speed = other_player.max_speed
                        move_vector, normal = self._calculate_move_away_vector(volleyball, other_player, dt, move_away_speed)
                        if move_vector is not None:
                            if players_to_move.get(other_id) is not None:
                                move_vector_existing = players_to_move[other_id]
                                normal_existing = normals_players_to_move[other_id]
                                # if normals in opposite direction, add smell perpendicular vector to avoid deadlock
                                similar_orientation = (normal.x * normal_existing.y - normal.y * normal_existing.x)**2 < 0.15
                                opposite_direction = (normal.x * normal_existing.x + normal.y * normal_existing.y) < 0
                                # print((normal.x * normal_existing.y - normal.y * normal_existing.x)**2)
                                # print('normals:', normal.x, normal.y, normal_existing.x, normal_existing.y)
                                # print(similar_orientation, opposite_direction)
                                if similar_orientation and opposite_direction: # same direction
                                    # add small perpendicular vector with random direction to previous move vector
                                    sign = random.choice([-1, 1])
                                    move_vector.x = move_vector_existing.x + sign * normal_existing.y * move_away_speed * dt * 0.5
                                    move_vector.y = move_vector_existing.y + sign * -normal_existing.x * move_away_speed * dt * 0.5
                                    logger.debug(f"Added perpendicular vector to avoid deadlock for player {other_id} during inbounding free way")
                                else:
                                    continue
                            players_to_move[other_id]= move_vector
                    else:
                        break
        
        # Apply all movements
        for player_id, move_vector in players_to_move.items():
            player = self.state.players[player_id]
            player.position.x += move_vector.x
            player.position.y += move_vector.y

    def _making_alive_keeper_free_way(self, dt: float) -> None:
        """
        Create a free way around the keeper when reviving a dead volleyball.

        Moves nearby opponents away from the keeper to avoid immediate pressure
        during the dead-ball restart.

        Args:
            dt: Delta game time since last frame in seconds.
        """
        volleyball = self.state.get_volleyball()
        if not volleyball:
            return
        if not volleyball.is_dead:
            return  # Volleyball not dead, no free way needed
        keeper = None
        for player in self.state.players.values():
            if player.role == PlayerRole.KEEPER and player.team == volleyball.possession_team:
                keeper = player
                break
        for player in self.state.players.values():
            # Check players too close to keeper
            # for other_id, distance in self._get_sorted_distances(keeper.id).items():
            for other_id, distance in self.state.squared_distances.get(keeper.id, []):
                if other_id in self.state.players.keys():
                    other_player = self.state.players[other_id]
                    if distance < (4 * (other_player.radius)) ** 2:
                        move_away_speed = other_player.max_speed
                        move_vector, normal = self._calculate_move_away_vector(keeper, other_player, dt, move_away_speed)
                        if move_vector is not None:
                            other_player.position.x += move_vector.x
                            other_player.position.y += move_vector.y
        

    def _calculate_move_away_vector(self, move_free_entity, move_away_entity, dt: float, move_away_speed: float) -> Optional[tuple[Vector2, Vector2]]:
        """
        Calculate the movement vector to move an entity away from another entity.
        
        Used for free way creation during inbounding. Computes the vector that will:
        - Push the entity away along the line between them (normal vector)
        - Remove any velocity component toward the fixed entity
        - Apply maximum move away speed in the normal direction
        - Add small random jitter to prevent deadlock situations
        
        Args:
            move_free_entity: The entity creating the free zone (inbounder/keeper)
            move_away_entity: The entity that needs to move away
            dt: Delta game time since last frame in seconds
            move_away_speed: Maximum speed to move away at
            
        Returns:
            Tuple of (move_vector, normal) where:
                - move_vector: The position offset to apply (scaled by dt)
                - normal: The unit normal from fixed entity to moving entity
            Returns None if entities are at same position (division by zero)
        """
        # push player away from the entity
        normal = Vector2(
            move_away_entity.position.x - move_free_entity.position.x,
            move_away_entity.position.y - move_free_entity.position.y
        )
        normal_mag = (normal.x**2 + normal.y**2) ** 0.5
        if normal_mag == 0:
            logger.warning("Zero normal magnitude in inbounding free way (entities at same position)")
            return None
        normal.x /= normal_mag
        normal.y /= normal_mag
        # take into account the other player's velocity and movement this frame so no "unnatural movement" occurs
        dot_other = move_away_entity.velocity.x * normal.x + move_away_entity.velocity.y * normal.y
        other_velocity_along_normal = Vector2(normal.x * dot_other, normal.y * dot_other)
        other_velocity_perpendicular = Vector2(
            move_away_entity.velocity.x - other_velocity_along_normal.x,
            move_away_entity.velocity.y - other_velocity_along_normal.y
        )
        move_away_entity.velocity.x = other_velocity_perpendicular.x
        move_away_entity.velocity.y = other_velocity_perpendicular.y
        # add small jitter factor to avoid deadlocks between several _inbounding_free_way calls
        jitter_factor_x = random.uniform(0.95, 1.05) # radians
        jitter_factor_y = random.uniform(0.95, 1.05)
        move_away_vector = Vector2(
            (normal.x * move_away_speed - other_velocity_along_normal.x) * jitter_factor_x,
            (normal.y * move_away_speed - other_velocity_along_normal.y) * jitter_factor_y
        )
        return Vector2(move_away_vector.x * dt, move_away_vector.y * dt), normal

    # def _move_away(self, move_free_entity, move_away_entity, dt: float, move_away_speed: float) -> None:
    #     """
    #     Legacy method - applies movement directly to an entity.
        
    #     Wrapper around _calculate_move_away_vector that directly modifies the entity's
    #     position. Deprecated in favor of collecting moves and applying them atomically.
        
    #     Args:
    #         move_free_entity: The entity creating the free zone
    #         move_away_entity: The entity that needs to move away
    #         dt: Delta time since last frame in seconds
    #         move_away_speed: Maximum speed to move away at
    #     """
    #     move_vector = self._calculate_move_away_vector(move_free_entity, move_away_entity, dt, move_away_speed)
    #     if move_vector is not None:
    #         move_away_entity.position.x += move_vector.x
    #         move_away_entity.position.y += move_vector.y         

