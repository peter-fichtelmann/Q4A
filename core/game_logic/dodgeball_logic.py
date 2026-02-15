from core.game_state import GameState
from core.entities import Player, Ball, VolleyBall, DodgeBall, Vector2, PlayerRole, BallType

class DodgeballLogic:
    """
    Handles dodgeball pickups, beats, and third-dodgeball enforcement.

    Attributes:
        state: Shared GameState instance for entities and rules.
        penalty_logic: Optional PenaltyLogic for third-dodgeball penalties.
    """

    def __init__(self, game_state: GameState, penalty_logic=None):
        """
        Initialize dodgeball rule handling.

        Args:
            game_state: The active GameState instance.
            penalty_logic: Optional PenaltyLogic dependency for penalties.
        """
        self.state = game_state
        self.penalty_logic = penalty_logic

    def _check_dodgeball_possession_of_player(self, player: Player, dodgeball: Ball) -> bool:
        """
        Attempt to assign a dodgeball to a player (beater only).
        
        A player can pick up a dodgeball if:
        - The player is a Beater
        - The player is not currently holding a ball (one per beater)
        - The player's catch cooldown has expired (prevents immediate re-catches after throwing)
        
        Args:
            player: The player attempting to pick up the dodgeball
            dodgeball: The dodgeball to pick up
            
        Returns:
            True if pickup was successful, False otherwise
        """
        if player.catch_cooldown <= 0.0:
            if player.role == PlayerRole.BEATER:
                if not player.has_ball:
                    if self.state.third_dodgeball == dodgeball.id and self.state.third_dodgeball_team != player.team:
                        # third dodgeball and player in already dodgeball possesing team
                        self.penalty_logic._third_dodgeball_interference(player, dodgeball)
                    else:
                    # Player picks up dodgeball
                        dodgeball.holder_id = player.id
                        dodgeball.possession_team = player.team
                        player.has_ball = dodgeball.id
                        if dodgeball.turnover_to_player is not None:
                            dodgeball.turnover_to_player = None
                            player.is_receiving_turnover_ball = False
                        print(f"[GAME] Player {player.id} picked up a dodgeball")
                    return True
        return False

    def _check_dodgeball_interactions(self) -> None:
        """
        Check and handle all dodgeball interactions with players.
        
        For each dodgeball, processes interactions with nearby players:
        - Dead/slow dodgeballs: Allow pickup by beaters
        - Fast moving dodgeballs: Check if they hit opponent players (beats)
        
        Collision detection uses precomputed distances sorted nearest-first
        for efficiency. Stops checking a dodgeball once an interaction occurs.
        """
        dodgeballs = self.state.get_dodgeballs()
        if len(dodgeballs) == 0:
            return  # No dodgeballs exist
        for dodgeball in dodgeballs:
            # for other_id, distance in self._get_sorted_distances(dodgeball.id).items():
            for other_id, distance in self.state.squared_distances.get(dodgeball.id, []):
                if other_id in self.state.players.keys():
                    player = self.state.players[other_id]
                    if not player.is_knocked_out:
                        if distance < (player.radius + dodgeball.radius) ** 2:
                            if dodgeball.turnover_to_player is not None and dodgeball.turnover_to_player != player.id:
                                continue # dodgeball in turnover can only be picked up by designated player
                            else:
                                # check if loose dead dodgeball or beater of same team
                                if dodgeball.possession_team is None or (
                                    dodgeball.possession_team == player.team and player.role == PlayerRole.BEATER
                                    ) or (
                                    dodgeball.turnover_to_player is not None and dodgeball.possession_team != player.team and player.is_receiving_turnover_ball
                                    ): # ball pickup with dead dodgeball or beater own team or ball in turnover to other team
                                    if self._check_dodgeball_possession_of_player(player, dodgeball):
                                        break
                                else: # beat checks
                                    self._check_beats(player, dodgeball)
                                    # if self._check_beats(player, dodgeball):
                                        # break only one beat allowed?


    def _check_beats(self, player: Player, dodgeball: Ball) -> bool:
        """
        Check if a dodgeball hits (beats) a player and handle the knockout.
        
        A beat occurs when a thrown dodgeball hits an opponent player who:
        - Is not knocked out
        - Is not immune (immune during inbounding or in keeper zone)
        - Is on the opposing team
        - Is not the player who just threw the ball (catch cooldown active)
        
        On a successful beat:
        - Player is marked as knocked out
        - Any held ball is dropped
        - Dodgeball is reflected off the player
        - Team possession of dodgeball is cleared
        
        On a reflection (same team or immunity):
        - Dodgeball is reflected but possession is not cleared
        
        Args:
            player: The player that might be hit
            dodgeball: The dodgeball that might hit the player
            
        Returns:
            True if player was knocked out, False otherwise
        """
        if dodgeball.holder_id is not None: # only thrown dodgeballs can beat
            return False
        if player.team == dodgeball.possession_team or player.dodgeball_immunity: # no friendly beats or immune
            if player.id == dodgeball.previous_thrower_id and player.catch_cooldown > 0.0:
                return False # beater still throwing dodgeball
            dodgeball.possession_team = None
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
            if player.has_ball: # drop ball if holding one
                ball = self.state.get_ball(player.has_ball)
                ball.holder_id = None
                ball.velocity.x = 0
                ball.velocity.y = 0
                ball.possession_team = None
                print(f"[GAME] Player {player.id} dropped ball {ball.id} due to knockout")
                player.has_ball = None
            # dodgeball.possession_team = None # Only one beat at once?
            normal = Vector2(
                dodgeball.position.x - player.position.x,
                dodgeball.position.y - player.position.y
            )
            normal_mag = (normal.x**2 + normal.y**2) ** 0.5
            normal.x /= normal_mag
            normal.y /= normal_mag
            dodgeball.velocity = dodgeball.velocity.reflect(normal, dodgeball.reflect_velocity_loss)
            print(f"[GAME] Player {player.id} was knocked out by dodgeball {dodgeball.id}")
            for dodgeball in self.state.get_dodgeballs():
                dodgeball.beat_attempt_time = 0.0 # reset beat attempt time
            self.state.potential_third_dodgeball_interference_kwargs = None # reset third dodgeball interference kwargs
            self.state.third_dodgeball = None
            self.state.third_dodgeball_team = None
            return True
        

    # def _check_ball_collisions(self) -> None:
    #     """Check if players can pick up nearby balls."""

    #                     elif other_id in self.state.balls.keys():
    #                         ball = self.state.balls[other_id]
    #                         # Ignore ball-ball collisions for now
    #                         continue

    def _is_dodgeball_third(self, dodgeballs_per_team) -> bool:
        """
        Determine whether the free dodgeball becomes a third-dodgeball.

        Args:
            dodgeballs_per_team: Precomputed mapping of dodgeball ownership states.

        Returns:
            True if a third-dodgeball situation exists, False otherwise.
        """
        if len(dodgeballs_per_team['dead_dodgeballs']) == 1:
            if len(dodgeballs_per_team[f'hold_dodgeballs_{self.state.team_0}']) == 2 and len(dodgeballs_per_team[f'hold_dodgeballs_{self.state.team_1}']) == 0:
                self.state.third_dodgeball_team = self.state.team_1
                return True
            elif len(dodgeballs_per_team[f'hold_dodgeballs_{self.state.team_0}']) == 0 and len(dodgeballs_per_team[f'hold_dodgeballs_{self.state.team_1}']) == 2:
                self.state.third_dodgeball_team = self.state.team_0
                return True
        return False

    def _check_third_dodgeball(self, dt) -> None:
        """
        Enforce the rule that only 2 dodgeballs can be held by one team at once.
        
        When 3 dodgeballs exist and one team holds 2 of them:
        - The third (free) dodgeball is automatically assigned to the other team
        - This prevents one team from accumulating all balls and denying the other team play
        - The assigned possession lasts until a player picks it up or game state changes
        """

        def is_still_third_dodgeball(dodgeballs_per_team):
            if len(dodgeballs_per_team[f'hold_dodgeballs_{self.state.third_dodgeball_team}'] + dodgeballs_per_team[f'thrown_dodgeballs_{self.state.third_dodgeball_team}']) > 0:
                # team without dodgeball got one
                return False
            else:
                if self.state.third_dodgeball_team == self.state.team_0:
                    dodgeball_possessing_team = self.state.team_1
                else:
                    dodgeball_possessing_team = self.state.team_0
                # if len(dodgeballs_per_team[dodgeball_possessing_team]) == 0:
                #     # not holding dodgeballs anymore. Is it really loosing third dodgeball after rulebook? -> No third dodgeball still exists
                #     return False
                # when thrown still possesion
                thrown_dodgeball_ids = dodgeballs_per_team[f'thrown_dodgeballs_{dodgeball_possessing_team}']
                for thrown_dodgeball_id in thrown_dodgeball_ids:
                    thrown_dodgeball = self.state.balls[thrown_dodgeball_id]
                    if thrown_dodgeball.holder_id is None: # thrown
                        if thrown_dodgeball.beat_attempt_time == 0.0:
                            # "initialize" beat_attempt_time
                            thrown_dodgeball.beat_attempt_time = dt
                            print(f'Initiating beat attempt time for {thrown_dodgeball.id}')

                
                    # reasonable beat attempt 
                    # get thrown bludger in dodgeball_team possesion
                    # 
                    #  and check if throw line to certain length close enough to nearest chaser
                    # option 1: check distance throw to chaser positions at throw
                    # option 2: include their current velocity at throw
                    ## favorite option 3: monitor closest distance until beat or velocity below threshold
                    pass
            return True

        dodgeballs = self.state.get_dodgeballs()
        # if len(dodgeballs) == 0:
        #     return # no dodgeball exist
        if len(dodgeballs) == 3:
        # potential_number_third_dodgeballs = len(dodgeballs) // 2
            
        # check for third dodgeballs
            dodgeballs_per_team = {
                f'hold_dodgeballs_{self.state.team_0}': [],
                f'hold_dodgeballs_{self.state.team_1}': [],
                f'thrown_dodgeballs_{self.state.team_0}': [],
                f'thrown_dodgeballs_{self.state.team_1}': [],
                'dead_dodgeballs': [],
                }
            for dodgeball in dodgeballs:
                if dodgeball.beat_attempt_time > 0:
                    dodgeball.beat_attempt_time += dt
                    if dodgeball.beat_attempt_time > self.state.beat_attempt_time_limit:
                        if self.state.potential_third_dodgeball_interference_kwargs is not None:
                            # third dodgeball interference
                            player = self.state.players[self.state.potential_third_dodgeball_interference_kwargs['player_id']]
                            # reset beat attempt times
                            dodgeball = self.state.balls[self.state.potential_third_dodgeball_interference_kwargs['dodgeball_id']]
                            # set beat attempt time to 0 to allow interference
                            dodgeball.beat_attempt_time = 0.0
                            self.penalty_logic._third_dodgeball_interference(player, dodgeball)
                if dodgeball.possession_team is None:
                    dodgeballs_per_team['dead_dodgeballs'].append(dodgeball.id)
                elif dodgeball.holder_id is not None:
                    holder = self.state.players[dodgeball.holder_id]
                    dodgeballs_per_team[f'hold_dodgeballs_{holder.team}'].append(dodgeball.id)
                else:
                    dodgeballs_per_team[f'thrown_dodgeballs_{dodgeball.possession_team}'].append(dodgeball.id)
            if self.state.third_dodgeball is None:
                if self._is_dodgeball_third(dodgeballs_per_team):
                    third_dodgeball_id = dodgeballs_per_team['dead_dodgeballs'][0]
                    # third_dodgeball = self.state.balls[third_dodgeball_id]
                    self.state.third_dodgeball = third_dodgeball_id
                    print(f'[GAME] Third dodgeball {third_dodgeball_id} assigned to team {self.state.third_dodgeball_team}')
            else:
                # third dodgeball exists
                # checks if still third dodgeball
                if not is_still_third_dodgeball(dodgeballs_per_team):
                    self.state.third_dodgeball = None
                    self.state.third_dodgeball_team = None
                    # reset beat attempt times and potential interference
                    for dodgeball in dodgeballs:
                        dodgeball.beat_attempt_time = 0.0
                    self.state.potential_third_dodgeball_interference_kwargs = None
                    print('[GAME] No longer third dodgeball situation')


            # -> check for other events:



