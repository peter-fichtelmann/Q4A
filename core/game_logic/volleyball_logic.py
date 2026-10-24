import logging
import math
from core.game_state import GameState
from core.entities import Player, Ball, VolleyBall, DodgeBall, Vector2, PlayerRole, BallType

BASE_LOGGER = logging.getLogger('quadball.game_logic')

class VolleyballLogic:
    """
    Manages volleyball-specific possession, scoring, and dead-ball rules.

    Attributes:
        state: Shared GameState instance for volleyball and hoops.
        penalty_logic: Optional PenaltyLogic for stalled volleyball turnovers.
    """

    def __init__(self, game_state: GameState, penalty_logic=None, logger: logging.Logger | None = None):
        """
        Initialize volleyball rule handling.

        Args:
            game_state: The active GameState instance.
            penalty_logic: Optional PenaltyLogic dependency for stalled volleyball turnovers.
        """
        self.state = game_state
        self.penalty_logic = penalty_logic
        self.logger = logger or BASE_LOGGER

    def _check_stalled_volleyball(self, dt: float) -> None:
        """
        Turn a stalled volleyball over to the closest opponent chaser/keeper.

        The volleyball is stalled while its carrier is being tackled. A tackle is a
        single action, so the carrier counts as still tackled until
        `stalled_volleyball_tackle_grace` game seconds pass without a new one.
        After `stalled_volleyball_time_limit` game seconds of continuous tackling
        the volleyball goes to the closest opponent chaser/keeper, who cannot be
        tackled for `stalled_turnover_tackle_immunity_time` game seconds after the pickup.

        Must run before `_enforce_tackle`, which clears `tackling_player_ids`.

        Args:
            dt: Delta game time since last frame in seconds
        """
        volleyball = self.state.volleyball
        if volleyball is None:
            return
        if volleyball.turnover_to_player is None:
            self.state.is_stalled_turnover_pending = False # turnover picked up or cancelled
        holder = self.state.players.get(volleyball.holder_id) if volleyball.holder_id is not None else None
        # any release (pass, shot, beat, turnover) ends the stall; dead and inbounded volleyballs never stall
        if holder is None or volleyball.is_dead or volleyball.inbounder is not None:
            self._reset_stalled_volleyball(volleyball)
            return
        if holder.tackling_player_ids:
            volleyball.time_since_carrier_tackled = 0.0
        else:
            volleyball.time_since_carrier_tackled += dt
        if volleyball.time_since_carrier_tackled > self.state.stalled_volleyball_tackle_grace:
            volleyball.stalled_timer = 0.0 # carrier broke free
            return
        volleyball.stalled_timer += dt
        if volleyball.stalled_timer >= self.state.stalled_volleyball_time_limit:
            self.logger.info("Stalled volleyball of player %s goes to the opponents", holder.id)
            volleyball.possession_team = holder.team # turnover goes to the other team
            if self.penalty_logic is not None:
                self.penalty_logic._designate_turnover(volleyball)
                # the receiver gets a moment to move off before the tacklers can stall it again
                self.state.is_stalled_turnover_pending = volleyball.turnover_to_player is not None
                self.penalty_logic.announce_turnover('stalled_volleyball', volleyball.position, [volleyball])
            self._reset_stalled_volleyball(volleyball)

    @staticmethod
    def _reset_stalled_volleyball(volleyball: VolleyBall) -> None:
        volleyball.stalled_timer = 0.0
        volleyball.time_since_carrier_tackled = float('inf')

    def stalled_volleyball_countdown(self) -> int:
        """
        Whole game seconds left before the stalled volleyball turnover, while within
        the last `stalled_volleyball_countdown` seconds; 0 otherwise.
        """
        volleyball = self.state.volleyball
        if volleyball is None or volleyball.stalled_timer <= 0.0:
            return 0
        remaining = self.state.stalled_volleyball_time_limit - volleyball.stalled_timer
        if remaining > self.state.stalled_volleyball_countdown:
            return 0
        return max(1, math.ceil(remaining))

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
        volleyball = self.state.volleyball
        if not volleyball:
            return  # Volleyball either doesn't exist or is held
        if volleyball.holder_id is not None:
            return # volleyball already in possession
        max_pickup_dist_sq = (volleyball.radius + self.state.max_player_radius) ** 2
        # for other_id, distance in self._get_sorted_distances(volleyball.id).items():
        for other_id, distance in self.state.squared_distances_ball_player.get(volleyball.id, []):
            if distance > max_pickup_dist_sq:
                break
            player = self.state.players.get(other_id)
            if player is None:
                continue
            if volleyball.turnover_to_player is not None and volleyball.turnover_to_player != player.id:
                continue # volleyball in turnover can only be picked up by designated player
            if not player.is_knocked_out:
                if player.catch_cooldown <= 0.0:
                    if volleyball.is_dead and not (player.role == PlayerRole.KEEPER and volleyball.possession_team == player.team):
                        continue # only keeper possess dead volleyball
                    # only calculated distances for chaser-keeper pairs
                    # if player.role == PlayerRole.CHASER or player.role == PlayerRole.KEEPER:
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
                                self.state.block_turnover_throw(player.id)
                                if self.state.is_stalled_turnover_pending:
                                    self.state.is_stalled_turnover_pending = False
                                    self.state.grant_stalled_turnover_tackle_immunity(player.id)
                            self.logger.info("Player %s picked up the volleyball", player.id)
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
        volleyball = self.state.volleyball
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
                                self.logger.debug('Volleyball crossed back before fully through hoop')
                            break
        if volleyball.crossed_hoop is not None:
            hoop_id, cross_y = volleyball.crossed_hoop
            hoop = self.state.hoops[hoop_id]
            passed_squared_distance = (volleyball.position.x - hoop.position.x) ** 2 + (volleyball.position.y - cross_y) ** 2
            if passed_squared_distance > volleyball.radius ** 2: # whole ball has passed through hoop
                # Goal scored!
                if hoop.team == self.state.team_0:
                    scoring_team = self.state.team_1
                else:
                    scoring_team = self.state.team_0
                self.logger.info("Goal scored by team %s through hoop %s!", scoring_team, hoop_id)
                self.state.update_score(scoring_team, 1)
                volleyball.crossed_hoop = None
                if volleyball.holder_id is not None:
                    # if player run with ball through hoop, so no throwing afterwards should be possible
                    volleyball_holder = self.state.players[volleyball.holder_id]
                    volleyball_holder.has_ball = False
                    volleyball.holder_id = None 
                for player in self.state.players.values():
                    if player.team == hoop.team:
                        if player.role == PlayerRole.KEEPER: # only if a keeper exists dead volleyball
                            volleyball.possession_team = player.team
                            volleyball.is_dead = True
                            return
                volleyball.possession_team = None # if no keeper                

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

        A volleyball make alive counter prevents immediate alive status to prevent issues when the dead ball went out of bounds.
        """
        volleyball = self.state.volleyball
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



