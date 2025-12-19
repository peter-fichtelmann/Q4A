from typing import Optional, Tuple
from core.entities import Player, Ball, Vector2, PlayerRole, BallType
from core.game_state import GameState
import random
from operator import itemgetter # faster dict sorting performance

class GameLogicSystem:
    """
    Implements the core game rules for quadball.
    This system is SERVER-AUTHORITATIVE, meaning the server runs this logic
    and clients trust its decisions.
    """
    
    def __init__(self, game_state: GameState):
        self.state = game_state
        self.squared_distances = {}  # Placeholder for any precomputed distances if needed of the form {entity_id_1: [(entity_id_2: squared_distance)]} with sorted tuples
        self.squared_distances_dicts = {} # Placeholder for any precomputed distances if needed of the dict nested form {entity_id_1: {entity_id_2: squared_distance}}
        entities_list = list(list(self.state.players.values()) + list(self.state.balls.values()))
        for entity in entities_list:
            self.squared_distances_dicts[entity.id] = {}
    
    def update(self, dt: float) -> None:
        """
        Update game logic each frame.
        - Check collisions
        - Update player knockouts
        - Check for goals
        - Validate all state changes
        
        Args:
            dt: Delta game time in seconds
        """
        # Update game time
        self.state.update_game_time(dt)
        
        self.update_player_velocities(dt)
        self._check_player_collisions()
        self.update_ball_velocities(dt)
        

        # Update player positions and ball positions
        self.update_positions(dt)
        # free way for volleyball inbounder
        self._inbounding_free_way(dt)
        self._making_alive_keeper_free_way(dt)
        self._enforce_hoop_blockage() # after update positions because possibly resetting to previous position
        self.make_volleyball_alive()
        
        self._calculate_distances()
        self._check_ball_collisions() # after distance calculation

        self._check_volleyball_possessions()
        self._check_dodgeball_interactions()

        self._check_goals()

        self._check_third_dodgeball()
        
        # Check pitch boundaries
        self._enforce_pitch_boundaries() # at least after free ways and position updates




    def update_player_velocities(self, dt: float) -> None:
        volleyball = self.state.get_volleyball()
        for player in self.state.players.values():
            # Update player velocity based on direction
            
            if player.is_knocked_out:
                player.direction.x = self.state.hoops[f'hoop_{player.team}_center'].position.x - player.position.x
                player.direction.y = self.state.hoops[f'hoop_{player.team}_center'].position.y - player.position.y
            elif volleyball is not None:
                if volleyball.is_dead:
                    if volleyball.possession == player.team and player.role == PlayerRole.KEEPER:
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
                    print('inbounding direction', player.direction.x, player.direction.y)
                    player.velocity.x = 0
                    player.velocity.y = 0
                    ball = self.state.balls[player.inbounding]
                    ball.inbounder = None
                    player.inbounding = None
                    player.dodgeball_immunity = False
                    print('inbounding procedure ended by ball re-entering pitch')
            # norm player.direction
            mag_dir = (player.direction.x**2 + player.direction.y**2) ** 0.5
            # on stick reset check before direction norm
            if player.is_knocked_out:
                print('mag dir', mag_dir, 'to hoop', player.radius + self.state.hoops[f'hoop_{player.team}_center'].thickness)
            if player.is_knocked_out and (mag_dir < player.radius + self.state.hoops[f'hoop_{player.team}_center'].thickness):
                player.is_knocked_out = False
                print(f"[GAME] Player {player.id} has recovered from knockout")
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

    def update_ball_velocities(self, dt: float) -> None:
        for ball in self.state.balls.values():
            if ball.holder_id is None:
                ball.velocity.x = ball.velocity.x - ball.deacceleration_rate * ball.velocity.x * dt
                ball.velocity.y = ball.velocity.y - ball.deacceleration_rate * ball.velocity.y * dt
            else:
                holder = self.state.get_player(ball.holder_id)
                if holder:
                    ball.velocity.x = holder.velocity.x
                    ball.velocity.y = holder.velocity.y

    def update_positions(self, dt: float) -> None:
        """Update positions of players and balls based on their velocities."""
        for player in self.state.players.values():
            player.previous_position.x = player.position.x
            player.previous_position.y = player.position.y
            player.position.x += player.velocity.x * dt
            player.position.y += player.velocity.y * dt
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
            ball.position.x += ball.velocity.x * dt
            ball.position.y += ball.velocity.y * dt

    def make_volleyball_alive(self) -> None:
        volleyball = self.state.get_volleyball()
        if volleyball is None:
            return
        if not volleyball.is_dead:
            return
        if volleyball.holder_id is None:
            return
        player = self.state.players[volleyball.holder_id]
        if player.role == PlayerRole.KEEPER and player.team == volleyball.possession:
            midline_x = self.state.boundaries_x[1] / 2
            if player.team == self.state.team_0:
                if player.position.x > midline_x:
                    return
            else:
                if player.position.x < midline_x:
                    return
            volleyball.is_dead = False
        
    def _enforce_hoop_blockage(self) -> None:
        """Chasers cannot come their own hoops to close to prevent goaltending"""
        # only for players which are not knocked out
        # TODO
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
                                            ball.position.y = ball.position.y
                                            ball.velocity.x = 0
                                            ball.velocity.y = 0
                                    break
                                # print(f'Player {player.id} blocked from going too close to own hoop')

    def _calculate_distances(self) -> None:
        """Precompute distances between players and balls if needed."""
        entities_list = list(list(self.state.players.values()) + list(self.state.balls.values()))
        for i, entity_1 in enumerate(entities_list):
            if i+1 == len(entities_list):
                break
            # If entity_1 is knocked out skip pairs involving it
            if hasattr(entity_1, 'is_knocked_out'):
                if entity_1.is_knocked_out:
                    continue

            for entity_2 in entities_list[i+1:]:
                # Skip pairs where entity_2 is knocked out
                if hasattr(entity_2, 'is_knocked_out'):
                    if entity_2.is_knocked_out:
                        continue
                # Skip keeper-beater and chaser-beater combinations (any order)
                if isinstance(entity_1, Player) and isinstance(entity_2, Player):
                    if ((entity_1.role == PlayerRole.BEATER and entity_2.role in (PlayerRole.KEEPER, PlayerRole.CHASER)) or
                        (entity_2.role == PlayerRole.BEATER and entity_1.role in (PlayerRole.KEEPER, PlayerRole.CHASER))):
                        continue
                # Skip beater-volleyball combinations (any order)
                if isinstance(entity_1, Player) and isinstance(entity_2, Ball):
                    if entity_1.role == PlayerRole.BEATER and entity_2.ball_type == BallType.VOLLEYBALL:
                        continue
                if isinstance(entity_2, Player) and isinstance(entity_1, Ball):
                    if entity_2.role == PlayerRole.BEATER and entity_1.ball_type == BallType.VOLLEYBALL:
                        continue
                # if isinstance(entity_2, Ball) and isinstance(entity_1, Ball): # Ball-Ball collisions checked in separate method
                #     continue

                # Store squared distance for the pair
                # self.squared_distances[(entity_1.id, entity_2.id)] = GameLogicSystem._squared_distance(entity_1.position, entity_2.position)
                squared_distance = GameLogicSystem._squared_distance(entity_1.position, entity_2.position)
                self.squared_distances_dicts[entity_1.id][entity_2.id] = squared_distance
                self.squared_distances_dicts[entity_2.id][entity_1.id] = squared_distance
                # Store or use the distance as needed
        for entity in entities_list:
            # sort the inner dict by distance ascending
            self.squared_distances[entity.id] = sorted(self.squared_distances_dicts[entity.id].items(), key=itemgetter(1))
    # def _get_sorted_distances(self, entity_id: str) -> Tuple[str, float]:
    #     """Return a dict mapping the other-entity id -> squared distance sorted nearest-first.
    #     """

    #     # The internal `self.squared_distances` stores distances keyed by a tuple
    #     # of two entity ids (id1, id2). Filter entries that include `entity_id`,
    #     # sort them by distance (ascending) and return a dict where keys are the
    #     # other entity id and values are the squared distances.

    #     # # Build a filtered dict of pair -> distance where the given entity_id is part of the pair
    #     # pair_distances = {
    #     #     pair: dist
    #     #     for pair, dist in self.squared_distances.items()
    #     #     if entity_id in pair
    #     # }

    #     # # Sort pairs by distance (nearest first). This produces a list of
    #     # # ((id1, id2), distance) tuples.
    #     # sorted_pairs = sorted(pair_distances.items(), key=lambda item: item[1])

    #     # Convert to other_id -> distance mapping preserving the sorted order
    #     # other_dict: dict = {}
    #     # for (id1, id2), distance in sorted_pairs:
    #     #     other_id = id2 if id1 == entity_id else id1
    #     #     other_dict[other_id] = distance
    #     sorted_tuples = sorted(self.squared_distances[entity_id].items(), key=itemgetter(1))
    #     # other_dict: dict = {}
    #     # for other_id, distance in sorted_tuples:
    #     #     other_dict[other_id] = distance
    #     # print(other_dict)
    #     return sorted_tuples
    
    def _check_volleyball_possessions(self) -> None:
        """Check if players can pick up the volleyball."""
        volleyball = self.state.get_volleyball()
        if not volleyball or volleyball.holder_id is not None:
            return  # Volleyball either doesn't exist or is held
        if volleyball.holder_id is not None:
            return # volleyball already in possession
        # for other_id, distance in self._get_sorted_distances(volleyball.id).items():
        for other_id, distance in self.squared_distances.get(volleyball.id, []):
            if other_id in self.state.players.keys():
                player = self.state.players[other_id]
                if not player.is_knocked_out:
                    if player.catch_cooldown <= 0.0:
                        if volleyball.is_dead and not (player.role == PlayerRole.KEEPER and volleyball.possession == player.team):
                            continue # only keeper possess dead volleyball
                        if player.role == PlayerRole.CHASER or player.role == PlayerRole.KEEPER:
                            if distance < (player.radius + volleyball.radius) ** 2:
                                if volleyball.inbounder is None or player.id == volleyball.inbounder: # no inbounding or inbounding player
                                    # Player picks up the volleyball
                                    volleyball.holder_id = player.id
                                    volleyball.possession = player.team
                                    player.has_ball = volleyball.id
                                    # volleyball.position = player.position
                                    print(f"[GAME] Player {player.id} picked up the volleyball")
                                break

    def _check_dodgeball_possession_of_player(self, player: Player, dodgeball: Ball) -> bool:
        if player.catch_cooldown <= 0.0:
            if player.role == PlayerRole.BEATER:
                if not player.has_ball:
                    # Player picks up dodgeball
                    dodgeball.holder_id = player.id
                    dodgeball.possession = player.team
                    player.has_ball = dodgeball.id
                    print(f"[GAME] Player {player.id} picked up a dodgeball")
                    return True
        return False

    def _check_dodgeball_interactions(self) -> None:
        dodgeballs = self.state.get_dodgeballs()
        if len(dodgeballs) == 0:
            return # no dodgeball exist
        for dodgeball in dodgeballs:
            # for other_id, distance in self._get_sorted_distances(dodgeball.id).items():
            for other_id, distance in self.squared_distances.get(dodgeball.id, []):
                if other_id in self.state.players.keys():
                    player = self.state.players[other_id]
                    if not player.is_knocked_out:
                        if distance < (player.radius + dodgeball.radius) ** 2:
                            if distance < (player.radius + dodgeball.radius) **2:
                                dodgeball_mag_velocity = (dodgeball.velocity.x**2 + dodgeball.velocity.y**2) ** 0.5
                                if dodgeball.possession is None or dodgeball_mag_velocity < 0.1 * player.throw_velocity: # ball pickup with dead dodgeball or slow moving one
                                    if self._check_dodgeball_possession_of_player(player, dodgeball):
                                        break
                                else: # beat checks
                                    if self._check_beats(player, dodgeball):
                                        break

    def _check_beats(self, player: Player, dodgeball: Ball) -> bool:
        """Check for dodgeball hits on players."""
        if dodgeball.holder_id is not None: # only thrown dodgeballs can beat
            return False
        if player.team == dodgeball.possession or player.dodgeball_immunity: # no friendly beats or immune
            if player.id == dodgeball.previous_thrower_id and player.catch_cooldown > 0.0:
                return False # beater still throwing dodgeball
            dodgeball.possession = None
            # reflecting dodgeball even by own player
            normal = Vector2(
                dodgeball.position.x - player.position.x,
                dodgeball.position.y - player.position.y
            )
            normal_mag = (normal.x**2 + normal.y**2) ** 0.5
            normal.x /= normal_mag
            normal.y /= normal_mag
            # print(f'normal: {normal.x}, {normal.y}, before reflect vel: {dodgeball.velocity.x}, {dodgeball.velocity.y}, after reflect vel: {dodgeball.velocity.reflect(normal, dodgeball.reflect_velocity_loss).x} {dodgeball.velocity.reflect(normal, dodgeball.reflect_velocity_loss).y}')
            dodgeball.velocity = dodgeball.velocity.reflect(normal, dodgeball.reflect_velocity_loss)
            return False
        else:
            player.is_knocked_out = True
            dodgeball.possession = None
            normal = Vector2(
                dodgeball.position.x - player.position.x,
                dodgeball.position.y - player.position.y
            )
            normal_mag = (normal.x**2 + normal.y**2) ** 0.5
            normal.x /= normal_mag
            normal.y /= normal_mag
            dodgeball.velocity = dodgeball.velocity.reflect(normal, dodgeball.reflect_velocity_loss)
            print(f"[GAME] Player {player.id} was knocked out by dodgeball {dodgeball.id}")
            return True
        

    # def _check_ball_collisions(self) -> None:
    #     """Check if players can pick up nearby balls."""

    #                     elif other_id in self.state.balls.keys():
    #                         ball = self.state.balls[other_id]
    #                         # Ignore ball-ball collisions for now
    #                         continue

    def _check_ball_collisions(self):
        # check if balls close enough to other balls to collide
        balls = list(self.state.balls.values())
        for i, ball_1 in enumerate(balls):
            for ball_2 in balls[i+1:]:
                if not ball_1.is_dead and not ball_1.is_dead:
                    if ball_1.holder_id is not None or ball_2.holder_id is not None:
                        continue # only check free balls
                    # dist_sq = GameLogicSystem._squared_distance(ball_1.position, ball_2.position)
                    dist_sq = self.squared_distances_dicts[ball_1.id][ball_2.id]
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
                        print(f"[GAME] Ball {ball_1.id} collided with Ball {ball_2.id}")

    def _check_player_collisions(self) -> None:
        for i, player in enumerate(list(self.state.players.values())[:-1]):
            if player.is_knocked_out:
                continue
            # for other_id, distance in self._get_sorted_distances(player.id).items():
            for other_id, distance in self.squared_distances.get(player.id, []):
                if other_id in list(self.state.players.keys())[i+1:]: # only check each pair once
                    other_player = self.state.players[other_id]
                    if other_player.is_knocked_out:
                        continue
                    collision_dist_sq = (player.radius + other_player.radius) ** 2
                    if distance < collision_dist_sq:
                        # Collision occurred
                        normal = Vector2(
                            other_player.position.x - player.position.x,
                            other_player.position.y - player.position.y
                        )
                        normal_mag = (normal.x**2 + normal.y**2) ** 0.5
                        if normal_mag == 0:
                            continue # avoid divide by zero
                        normal.x /= normal_mag
                        normal.y /= normal_mag
                        # print('normal', normal.x, normal.y)
                        # print('pre-collision player vel', player.velocity.x, player.velocity.y)
                        # print('pre-collision other player vel', other_player.velocity.x, other_player.velocity.y)
                        dot_player = player.velocity.x * normal.x + player.velocity.y * normal.y
                        dot_other = other_player.velocity.x * normal.x + other_player.velocity.y * normal.y
                        # print('dot player', dot_player)
                        # print('dot other', dot_other)
                        if dot_player < 0 and dot_other > 0:
                            continue # both moving away from each other
                        # split velcoity into contribution along connecting vector and perpendicular to it
                        player_velocity_along_normal = Vector2(normal.x * dot_player, normal.y * dot_player)
                        player_velocity_perpendicular = Vector2(
                            player.velocity.x - player_velocity_along_normal.x,
                            player.velocity.y - player_velocity_along_normal.y
                        )
                        other_velocity_along_normal = Vector2(normal.x * dot_other, normal.y * dot_other)
                        other_velocity_perpendicular = Vector2(
                            other_player.velocity.x - other_velocity_along_normal.x,
                            other_player.velocity.y - other_velocity_along_normal.y
                        )
                        if dot_player > 0 and dot_other > 0: # player moves towards other
                            mag_player_vel_along_normal = (player_velocity_along_normal.x**2 + player_velocity_along_normal.y**2) ** 0.5
                            mag_other_vel_along_normal = (other_velocity_along_normal.x**2 + other_velocity_along_normal.y**2) ** 0.5
                            if mag_player_vel_along_normal < mag_other_vel_along_normal: # player slower than not pushing other
                                continue
                        elif dot_player < 0 and dot_other < 0: # other moves towards player
                            mag_player_vel_along_normal = (player_velocity_along_normal.x**2 + player_velocity_along_normal.y**2) ** 0.5
                            mag_other_vel_along_normal = (other_velocity_along_normal.x**2 + other_velocity_along_normal.y**2) ** 0.5
                            if mag_player_vel_along_normal > mag_other_vel_along_normal: # other slower than not pushing player
                                continue
                         # else both moving away from towards each other or one stationary
                        combined_velocity_along_normal = Vector2(
                            (player_velocity_along_normal.x + other_velocity_along_normal.x) / 2,
                            (player_velocity_along_normal.y + other_velocity_along_normal.y) / 2
                        )
                        player.velocity.x = combined_velocity_along_normal.x + player_velocity_perpendicular.x
                        player.velocity.y = combined_velocity_along_normal.y + player_velocity_perpendicular.y
                        other_player.velocity.x = combined_velocity_along_normal.x + other_velocity_perpendicular.x
                        other_player.velocity.y = combined_velocity_along_normal.y + other_velocity_perpendicular.y

                        # print('player vel along normal', player_velocity_along_normal.x, player_velocity_along_normal.y)
                        # print('player vel perp', player_velocity_perpendicular.x, player_velocity_perpendicular.y)
                        # print('other vel along normal', other_velocity_along_normal.x, other_velocity_along_normal.y)
                        # print('other vel perp', other_velocity_perpendicular.x, other_velocity_perpendicular.y)
                        # print('combined vel along normal', combined_velocity_along_normal.x, combined_velocity_along_normal.y)


                        # print('payer new vel', player.velocity.x, player.velocity.y)
                        # print('other new vel', other_player.velocity.x, other_player.velocity.y)
                        # TODO: deal with boundaries close to players

    def _check_goals(self) -> None:
        """Check if ball passes through a hoop."""
        volleyball = self.state.get_volleyball()
        if not volleyball:
            return  # Volleyball doesn't exist
        if volleyball.is_dead:
            return # Dead volleyball cannot score
        for team in [0, 1]:
            hoop_x = self.state.hoops[f'hoop_{team}_center'].position.x
            steps_to_hoops = (hoop_x - volleyball.previous_position.x) / (volleyball.position.x - volleyball.previous_position.x) if volleyball.previous_position.x != volleyball.position.x else float('inf')
            if steps_to_hoops > 0 and steps_to_hoops < 1: # crossed hoop this frame
                for hoop_id, hoop in self.state.hoops.items():
                    if hoop.team == team:
                        y_hoop = hoop.position.y
                        # Check if ball is at hoop height
                        if volleyball.position.y >= y_hoop - hoop.radius and volleyball.position.y <= y_hoop + hoop.radius:
                            # print(f'volleyball crossed hoop {hoop_id} at y={volleyball.position.y}, hoop y={y_hoop}')
                            if volleyball.crossed_hoop is None:
                                volleyball.crossed_hoop = (hoop_id, volleyball.position.y)
                            else:
                                volleyball.crossed_hoop = None # volleyball crossed back before fully through e.g. by keeper or dodgeball collision
                                print('volleyball crossed back before fully through hoop')
                            break
        if volleyball.crossed_hoop is not None:
            hoop_id, cross_y = volleyball.crossed_hoop
            hoop = self.state.hoops[hoop_id]
            passed_distance = ((volleyball.position.x - hoop.position.x) ** 2 + (volleyball.position.y - cross_y) ** 2) ** 0.5
            if passed_distance > volleyball.radius: # whole ball has passed through hoop
                # Goal scored!
                self.state.update_score(hoop.team, 10)
                volleyball.crossed_hoop = None
                volleyball.holder_id = None
                for player in self.state.players.values():
                    if player.team == hoop.team:
                        if player.role == PlayerRole.KEEPER: # only if a keeper exists dead volleyball
                            volleyball.possession = player.team
                            volleyball.is_dead = True
                            return
                volleyball.possession = None # if no keeper
                # TODO: Dead volleyball -> make alive process by keeper
                

            # Check if ball position is within hoop radius
            # dist_x = volleyball.position.x - hoop.position.x
            # dist_y = volleyball.position.y - hoop.position.y
            # distance = (dist_x**2 + dist_y**2) ** 0.5

            # the whole volleyball must pass through either side of the hoops
            # calculate cross point between hoop x line and ball velocity line
            # if cross point at hoop y position:
                # set crossed hoop attribute of ball with hoop id and cross point
                # if distance from cross point larger hoop.radius + volleyball.radius
                # score
                # if cross same hoop again remove cross hoop attribute
        

            # if distance < hoop.radius + volleyball.radius:
                    # Goal scored!


            # self.state.update_score(hoop.team, 10)
            # volleyball.holder_id = None
            # print(f"[GAME] Goal! Team {hoop.team} scores 10 points")

    def _check_third_dodgeball(self) -> None:
        dodgeballs = self.state.get_dodgeballs()
        # if len(dodgeballs) == 0:
        #     return # no dodgeball exist
        if len(dodgeballs) == 3:
        # potential_number_third_dodgeballs = len(dodgeballs) // 2
            dodgeballs_per_team = {
                self.state.team_0: [],
                self.state.team_1: [],
                'not_hold': []
                }
            for dodgeball in dodgeballs:
                if dodgeball.holder_id is None:
                    dodgeballs_per_team['not_hold'].append(dodgeball.id)
                else:
                    holder = self.state.players[dodgeball.holder_id]
                    dodgeballs_per_team[holder.team].append(dodgeball.id)
            if len(dodgeballs_per_team[self.state.team_0]) == 2 and len(dodgeballs_per_team[self.state.team_1]) == 0:
                third_dodgeball_id = dodgeballs_per_team['not_hold'][0]
                third_dodgeball = self.state.balls[third_dodgeball_id]
                third_dodgeball.possession = self.state.team_1
                # print(f'[GAME] Third dodgeball {third_dodgeball.id} assigned to team {self.state.team_1}')
            elif len(dodgeballs_per_team[self.state.team_0]) == 0 and len(dodgeballs_per_team[self.state.team_1]) == 2:
                third_dodgeball_id = dodgeballs_per_team['not_hold'][0]
                third_dodgeball = self.state.balls[third_dodgeball_id]
                third_dodgeball.possession = self.state.team_1
                # print(f'[GAME] Third dodgeball {third_dodgeball.id} assigned to team {self.state.team_1}')
            # if third_dodgeball -> check if still third: if not picked up by new possession team or beat-attempt two bludger team

    def _enforce_pitch_boundaries(self) -> None:
        """Keep players and balls within pitch bounds."""        
        # Check all entities
        for moving_entity in list(list(self.state.players.values()) + list(self.state.balls.values())):
            new_position_x = min(max(self.state.boundaries_x[0] + moving_entity.radius, moving_entity.position.x), self.state.boundaries_x[1] - moving_entity.radius)
            new_position_y = min(max(self.state.boundaries_y[0] + moving_entity.radius, moving_entity.position.y), self.state.boundaries_y[1] - moving_entity.radius)
            if new_position_x != moving_entity.position.x or new_position_y != moving_entity.position.y:
                # print('boundary enforcement for entity', moving_entity.id, new_position_x, moving_entity.position.x, new_position_y, moving_entity.position.y)
                if hasattr(moving_entity, "ball_type"):
                    # stopp balls at boundary
                    moving_entity.velocity.x = 0
                    moving_entity.velocity.y = 0
                    if moving_entity.ball_type == BallType.VOLLEYBALL:
                        if moving_entity.holder_id is None and not moving_entity.is_dead:
                            # volleyball going out of bounds only if not hold
                            self._start_inbounding_procedure()
                if hasattr(moving_entity, "has_ball"):
                    if moving_entity.has_ball:
                        ball = self.state.get_ball(moving_entity.has_ball)
                        if ball.ball_type == BallType.VOLLEYBALL:
                            # volleyball going out of bounds
                            print('volleyball going out of bounds at position where player out of bounds')
                            # Copy position values, don't share the same Vector2 object
                            ball.position.x = moving_entity.position.x
                            ball.position.y = moving_entity.position.y
                            moving_entity.has_ball = None
                            ball.holder_id = None
                            self._start_inbounding_procedure()
                moving_entity.position.x = new_position_x
                moving_entity.position.y = new_position_y

    
    def _start_inbounding_procedure(self):
        volleyball = self.state.get_volleyball()
        if not volleyball:
            return
        elif volleyball.inbounder is not None:
            return # volleyball already inbounded procedure
        # for other_id, distance in self._get_sorted_distances(volleyball.id).items():
        for other_id, distance in self.squared_distances.get(volleyball.id, []):
            if other_id in self.state.players.keys():
                player = self.state.players[other_id]
                if player.team != volleyball.possession: # inbounding player other team
                    if player.role == PlayerRole.CHASER or player.role == PlayerRole.KEEPER:
                        if player.inbounding is None:
                            if not player.has_ball:
                                if not player.is_knocked_out: # what happens if all chasers/keeper of team are knocked out?
                                    print(f'[GAME] Inbounding procedure started by player {player.id} for volleyball {volleyball.id}')
                                    player.inbounding = volleyball.id
                                    player.dodgeball_immunity = True # chaser/keeper immune while inbounding
                                    volleyball.inbounder = player.id
                                    volleyball.holder_id = None
                                    break

    def _inbounding_free_way(self, dt: float) -> None:
        """Moves players too close to the inbounding player and volleyball away from them."""
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
        for other_id, distance in self.squared_distances.get(inbounding_player.id, []):
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
        for other_id, distance in self.squared_distances.get(volleyball.id, []):
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
                                    print(f'Added perpendicular vector to avoid deadlock for player {other_id} during inbounding free way')
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
        volleyball = self.state.get_volleyball()
        if not volleyball:
            return
        if not volleyball.is_dead:
            return # volleyball not dead
        keeper = None
        for player in self.state.players.values():
            if player.role == PlayerRole.KEEPER and player.team == volleyball.possession:
                keeper = player
                break
        for player in self.state.players.values():
            # Check players too close to keeper
            # for other_id, distance in self._get_sorted_distances(keeper.id).items():
            for other_id, distance in self.squared_distances.get(keeper.id, []):
                if other_id in self.state.players.keys():
                    other_player = self.state.players[other_id]
                    if distance < (4 * (other_player.radius)) ** 2:
                        move_away_speed = other_player.max_speed
                        move_vector, normal = self._calculate_move_away_vector(keeper, other_player, dt, move_away_speed)
                        if move_vector is not None:
                            other_player.position.x += move_vector.x
                            other_player.position.y += move_vector.y
        

    def _calculate_move_away_vector(self, move_free_entity, move_away_entity, dt: float, move_away_speed: float) -> Optional[tuple[Vector2, Vector2]]:
        """Calculate the movement vector to move an entity away from another entity."""
        # push player away from the entity
        normal = Vector2(
            move_away_entity.position.x - move_free_entity.position.x,
            move_away_entity.position.y - move_free_entity.position.y
        )
        normal_mag = (normal.x**2 + normal.y**2) ** 0.5
        if normal_mag == 0:
            print('zero normal mag in inbounding free way') # avoid divide by zero
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

    def _move_away(self, move_free_entity, move_away_entity, dt: float, move_away_speed: float) -> None:
        """Legacy method - applies movement directly."""
        move_vector = self._calculate_move_away_vector(move_free_entity, move_away_entity, dt, move_away_speed)
        if move_vector is not None:
            move_away_entity.position.x += move_vector.x
            move_away_entity.position.y += move_vector.y                    
                



    
    @staticmethod
    def _squared_distance(pos1: Vector2, pos2: Vector2) -> float:
        """Calculate Euclidean distance between two positions."""
        dx = pos1.x - pos2.x
        dy = pos1.y - pos2.y
        return (dx**2 + dy**2)
    
    @staticmethod
    def _distance(pos1: Vector2, pos2: Vector2) -> float:
        return GameLogicSystem._squared_distance(pos1, pos2) ** 0.5
    
    def process_throw_action(self, player_id: str) -> bool:
        """
        Process a throw action by a player.
        Returns True if throw was successful.
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
    
    def process_tackle_action(self):
        pass