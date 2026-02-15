from core.game_state import GameState
from core.entities import Player, Ball, VolleyBall, DodgeBall, Vector2, PlayerRole, BallType

class VolleyballLogic:
    def __init__(self, game_state: GameState):
        self.state = game_state

    def _check_volleyball_possessions(self) -> None:
        """
        Check and process volleyball pickups by chasers and keepers.
        
        A player can pick up the volleyball if:
        - Player is a Chaser or Keeper (beaters cannot hold it)
        - Player is not knocked out
        - Player's catch cooldown after throwing has expired (so no immedate re-catch)
        - Volleyball is within collision distance (proximity check)
        - Special conditions are met:
          * Dead volleyball: Only the possessing team's keeper can pick it up
          * Live volleyball: Any chaser/keeper can pick it up (no inbounder restriction)
        
        Once picked up, volleyball follows the player's movement.
        """
        volleyball = self.state.get_volleyball()
        if not volleyball or volleyball.holder_id is not None:
            return  # Volleyball either doesn't exist or is held
        if volleyball.holder_id is not None:
            return # volleyball already in possession
        # for other_id, distance in self._get_sorted_distances(volleyball.id).items():
        for other_id, distance in self.state.squared_distances.get(volleyball.id, []):
            if other_id in self.state.players.keys():
                player = self.state.players[other_id]
                if volleyball.turnover_to_player is not None and volleyball.turnover_to_player != player.id:
                    continue # volleyball in turnover can only be picked up by designated player
                if not player.is_knocked_out:
                    if player.catch_cooldown <= 0.0:
                        if volleyball.is_dead and not (player.role == PlayerRole.KEEPER and volleyball.possession_team == player.team):
                            continue # only keeper possess dead volleyball
                        if player.role == PlayerRole.CHASER or player.role == PlayerRole.KEEPER:
                            if distance < (player.radius + volleyball.radius) ** 2:
                                if volleyball.inbounder is None or player.id == volleyball.inbounder: # no inbounding or inbounding player
                                    # Player picks up the volleyball
                                    volleyball.holder_id = player.id
                                    volleyball.possession_team = player.team
                                    player.has_ball = volleyball.id
                                    # volleyball.position = player.position
                                    if volleyball.turnover_to_player is not None:
                                        volleyball.turnover_to_player = None
                                        player.is_receiving_turnover_ball = False
                                    print(f"[GAME] Player {player.id} picked up the volleyball")
                                    break
                            else:
                                break  # Beyond pickup range, stop checking further players

    def _check_goals(self) -> None:
        """
        Check if the volleyball passes through a hoop and award points.
        
        Goal scoring process:
        1. Detect when volleyball crosses the hoop's x-coordinate from outside to inside
        2. Record crossing point if ball is at hoop height (within hoop radius)
        3. Track the crossing using 'crossed_hoop' attribute
        4. If ball is crossed back before passing through completely, reset tracking
        5. Award 10 points when entire ball has passed through the hoop
        
        After scoring:
        - Ball becomes dead and assigned to the opposing team's keeper (possession team)
        - Prevents immediate re-scoring through defensive play
        - Keeper must bring ball back into play to continue the game
        
        Dead volleyball cannot score.
        """
        volleyball = self.state.get_volleyball()
        if not volleyball:
            return  # Volleyball doesn't exist
        if volleyball.is_dead:
            return # Dead volleyball cannot score
        if volleyball.turnover_to_player is not None:
            return # volleyball in turnover cannot score
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
                            volleyball.possession_team = player.team
                            volleyball.is_dead = True
                            return
                volleyball.possession_team = None # if no keeper
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


    def make_volleyball_alive(self) -> None:
        """
        Make the dead volleyball alive when the keeper brings it back into play.
        
        The volleyball becomes alive when:
        - It is held by the keeper of the team that possesses it (was scored against) in their own half
        """
        volleyball = self.state.get_volleyball()
        if volleyball is None:
            return
        if not volleyball.is_dead:
            return  # Already alive
        if volleyball.holder_id is None:
            return  # No one holding it
        
        player = self.state.players[volleyball.holder_id]
        if player.role == PlayerRole.KEEPER and player.team == volleyball.possession_team:
            midline_x = self.state.boundaries_x[1] / 2
            # Check if keeper has crossed into opponent's half
            if player.team == self.state.team_0:
                if player.position.x > midline_x:
                    return  # Team 0 keeper must be on left side (x < midline)
            else:
                if player.position.x < midline_x:
                    return  # Team 1 keeper must be on right side (x > midline)
            
            # Keeper is in own half, ball becomes alive
            volleyball.is_dead = False