from core.game_state import GameState
from core.entities import Player, Ball, VolleyBall, DodgeBall, Vector2, PlayerRole, BallType

class PhysicalContactLogic:
    def __init__(self, game_state: GameState):
        self.state = game_state

    def _check_player_collisions(self) -> None:
        """
        Detect and resolve collisions between players.
        
        When two active (non-knocked-out) players of similar positions collide:
        - Separates their velocity components along and perpendicular to collision normal
        - Averages the velocity component along the collision line
        - Preserves each player's perpendicular (tangential) velocity
        
        This creates realistic elastic collisions where players don't stick together
        but bounce off each other naturally.
        """
        # reset in contact player ids from last update (in separate loop because in other loop attributes of other players set)
        for player in self.state.players.values():
            player.in_contact_player_ids = []
        for i, player in enumerate(list(self.state.players.values())[:-1]):
            if player.is_knocked_out:
                continue
            # for other_id, distance in self._get_sorted_distances(player.id).items():
            for other_id, distance in self.state.squared_distances.get(player.id, []):
                if other_id in list(self.state.players.keys())[i+1:]: # only check each pair once
                    other_player = self.state.players[other_id]
                    if other_player.is_knocked_out:
                        continue
                    collision_dist_sq = (player.radius + other_player.radius) ** 2
                    if distance < collision_dist_sq:
                        # Collision occurred
                        player.in_contact_player_ids.append(other_player.id)
                        other_player.in_contact_player_ids.append(player.id)
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
                        if dot_player > 0 and dot_other > 0: # player moves towards other player
                            mag_player_vel_along_normal = (player_velocity_along_normal.x**2 + player_velocity_along_normal.y**2) ** 0.5
                            mag_other_vel_along_normal = (other_velocity_along_normal.x**2 + other_velocity_along_normal.y**2) ** 0.5
                            if mag_player_vel_along_normal < mag_other_vel_along_normal: # player slower than other so no pushing
                                continue
                        elif dot_player < 0 and dot_other < 0: # other player moves towards player
                            mag_player_vel_along_normal = (player_velocity_along_normal.x**2 + player_velocity_along_normal.y**2) ** 0.5
                            mag_other_vel_along_normal = (other_velocity_along_normal.x**2 + other_velocity_along_normal.y**2) ** 0.5
                            if mag_player_vel_along_normal > mag_other_vel_along_normal: # other player slower than player so no pushing
                                continue
                         # else both moving towards each other or one stationary
                        combined_velocity_along_normal = Vector2(
                            (player_velocity_along_normal.x + other_velocity_along_normal.x) / 2,
                            (player_velocity_along_normal.y + other_velocity_along_normal.y) / 2
                        )
                        player.velocity.x = combined_velocity_along_normal.x + player_velocity_perpendicular.x
                        player.velocity.y = combined_velocity_along_normal.y + player_velocity_perpendicular.y
                        other_player.velocity.x = combined_velocity_along_normal.x + other_velocity_perpendicular.x
                        other_player.velocity.y = combined_velocity_along_normal.y + other_velocity_perpendicular.y
                        # add contact_player_id for potential reset when enforcing hoop blockage or boundary


                        # print('player vel along normal', player_velocity_along_normal.x, player_velocity_along_normal.y)
                        # print('player vel perp', player_velocity_perpendicular.x, player_velocity_perpendicular.y)
                        # print('other vel along normal', other_velocity_along_normal.x, other_velocity_along_normal.y)
                        # print('other vel perp', other_velocity_perpendicular.x, other_velocity_perpendicular.y)
                        # print('combined vel along normal', combined_velocity_along_normal.x, combined_velocity_along_normal.y)


                        # print('payer new vel', player.velocity.x, player.velocity.y)
                        # print('other new vel', other_player.velocity.x, other_player.velocity.y)
                        # TODO: deal with boundaries close to players
