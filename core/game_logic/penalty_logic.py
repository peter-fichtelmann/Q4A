import logging
import random
from core.game_state import GameState
from core.entities import Player, Ball, VolleyBall, DodgeBall, Vector2, PlayerRole, BallType

logger = logging.getLogger('quadball.game_logic')

class PenaltyLogic:
    """
    Enforces penalties, turnovers, and delay-of-game rules.

    Attributes:
        state: Shared GameState instance for rule evaluation and updates.
    """

    def __init__(self, game_state: GameState):
        """
        Initialize penalty rule handling.

        Args:
            game_state: The active GameState instance.
        """
        self.state = game_state

    def _check_delay_of_game(self, dt: float) -> None:
        """
        Check if volleyball not advanced enough in own half and enforce delay of game penalty.
        
        Args:
            dt: Delta game time since last frame in seconds
        """
        volleyball = self.state.get_volleyball()

        def _check_delay_velocity(volleyball: VolleyBall) -> bool|float:
            """
            Check if the volleyball is causing a delay of game.
             Returns True if delay of game conditions are met, False otherwise.

             Args:
                 volleyball: The volleyball to check
            
             Returns:
                 True if delay of game conditions are met, False otherwise.
            """
            if not volleyball:
                return 0
            if volleyball.is_dead:
                return  0 # Dead volleyball cannot incur delay of game
            if volleyball.inbounder is not None:
                return 0 # Inbounding volleyball cannot incur delay of game
            if volleyball.turnover_to_player is not None:
                return 0 # volleyball in turnover cannot incur delay of game
            if volleyball.possession_team is None:
                return 0 # So far unpossessed volleyball cannot incur delay of game
            if volleyball.possession_team == self.state.team_0 and volleyball.position.x < self.state.midline_x: # if volleyball in own half
                if volleyball.velocity.x > self.state.delay_of_game_velocity_x_threshold: # if volleyball moving forward enough
                    return 0
            elif volleyball.possession_team == self.state.team_1 and volleyball.position.x > self.state.midline_x: # if volleyball in own half
                if volleyball.velocity.x < -self.state.delay_of_game_velocity_x_threshold: # if volleyball moving forward enough + use the inverse for team 1 
                    return 0
            else:
                 return 0 # volleyball not in own half
            for other_id, distance in self.state.squared_distances[volleyball.id]:
                if other_id in self.state.players.keys():
                    player = self.state.players[other_id]
                    if player.team != volleyball.possession_team:
                        if player.role == PlayerRole.CHASER or player.role == PlayerRole.KEEPER:
                            if distance < 2:
                                return 0 # opponent player close enough to volleyball to prevent delay of game
                        elif player.role == PlayerRole.BEATER and player.has_ball is not None:
                            if distance < 4:
                                return 0 # opponent loaded beater close enough to volleyball to prevent delay of game
                            else:
                                break # no need to check further players
            if volleyball.possession_team == self.state.team_0:
                delay_velocity = self.state.delay_of_game_velocity_x_threshold - volleyball.velocity.x
            else:
                delay_velocity = self.state.delay_of_game_velocity_x_threshold + volleyball.velocity.x
            return delay_velocity # return how much below threshold the volleyball is
        # delay velocity as weighting factor how severve the delay of game is
        delay_velocity = _check_delay_velocity(volleyball)
        if delay_velocity > 0:
            volleyball.delay_of_game_timer += dt * delay_velocity
            if volleyball.delay_of_game_timer >= self.state.delay_of_game_time_limit:
                if self.state.delay_of_game_warnings.get(volleyball.possession_team) is None:
                    self.state.delay_of_game_warnings[volleyball.possession_team] = 0
                self.state.delay_of_game_warnings[volleyball.possession_team] += 1
                if self.state.delay_of_game_warnings[volleyball.possession_team] <= self.state.max_delay_of_game_warnings:
                    logger.warning(f"Warning {self.state.delay_of_game_warnings[volleyball.possession_team]} for delay of game on team {volleyball.possession_team}")
                else:
                    # Delay of game penalty
                    logger.warning(f"Delay of game penalty on team {volleyball.possession_team}")
                    # initiate volleyball turnover
                    self._designate_turnover(volleyball)
                    # TODO implement blue card penalty
                volleyball.delay_of_game_timer = 0.0
        else:
            if volleyball is not None:
                possessing_player = self.state.players.get(volleyball.holder_id)
                # check if protected keeper, if yes no reset of timer (protected keeper has to advance directly)
                protected_keeper = False
                if possessing_player is not None:
                    if possessing_player.role == PlayerRole.KEEPER:
                        if possessing_player.dodgeball_immunity:
                            protected_keeper = True
                if not protected_keeper:
                    volleyball.delay_of_game_timer = 0.0

    def _designate_turnover(self, ball: Ball) -> None:
        """
        Designate a turnover for the ball to the opposing team.
        
        Selects the nearest eligible opposing player (volleyball: chaser or keeper, dodgeball: beater) to receive
        the ball as a turnover. The selected player must not be knocked out
        and must not already hold a ball.
        
        Args:
            ball: The ball to designate turnover for
        """
        for other_id, distance in self.state.squared_distances.get(ball.id, []):
            if other_id in self.state.players.keys():
                player = self.state.players[other_id]
                if player.team != ball.possession_team:
                    if ball.ball_type == BallType.VOLLEYBALL:
                        if player.role == PlayerRole.CHASER or player.role == PlayerRole.KEEPER:
                            if not player.has_ball:
                                ball.turnover_to_player = player.id
                                if ball.holder_id is not None:
                                    holder = self.state.players.get(ball.holder_id)
                                    holder.has_ball = False
                                    ball.holder_id = None
                                break
                    elif ball.ball_type == BallType.DODGEBALL:
                        if player.role == PlayerRole.BEATER:
                            if not player.has_ball:
                                if not player.is_receiving_turnover_ball: # prevent multiple turnover balls to same player
                                    ball.turnover_to_player = player.id
                                    player.is_receiving_turnover_ball = True
                                    if ball.holder_id is not None:
                                        holder = self.state.players.get(ball.holder_id)
                                        holder.has_ball = False
                                        ball.holder_id = None
                                    break
        # if no egliglibe player: no turnover

    def _third_dodgeball_interference(self, player, dodgeball):
        """
        Apply third-dodgeball interference rules for an illegal pickup.

        Depending on beat-attempt timing, either schedules a potential
        interference penalty or immediately applies a turnover and knockout.

        Args:
            player: The player committing interference.
            dodgeball: The dodgeball involved in the interference.
        """
        if dodgeball.beat_attempt_time > 0:
            self.state.potential_third_dodgeball_interference_kwargs = {
                'dodgeball_id': dodgeball.id,
                'player_id': player.id,
            }
            logger.warning(f"Potential third dodgeball interference if beat attempt not successful")
        else:
            logger.warning(f"Third dodgeball interference by team {player.team} of player {player.id} with dodgeball {dodgeball.id}")
            volleyball = self.state.get_volleyball()
            # Back to hoops for player
            player.is_knocked_out = True
            second_dodgeball_priority = {}
            for second_dodgeball in self.state.get_dodgeballs():
                if second_dodgeball.id == dodgeball.id:
                    continue
                priority = 0.0
                if second_dodgeball.possession_team is None: # slight priority turnover
                    priority += 1
                elif second_dodgeball.possession_team != player.team: # dodgeball already in possession other team, high priority turnover
                    priority += 2
                if second_dodgeball.holder_id is None: # dodgeball not hold very slight priority turnover
                    priority += 0.5
                second_dodgeball_priority[second_dodgeball.id] = priority
            second_dodgeball_priority_values = list(second_dodgeball_priority.values())
            second_dodgeball_priority_keys = list(second_dodgeball_priority.keys())
            if len(second_dodgeball_priority_values) < 2:
                raise ValueError('Missing second dodgeball in third dodgeball interference.')
            if second_dodgeball_priority_values[0] > second_dodgeball_priority_values[1]:
                dodgeball_to_turnover_id = second_dodgeball_priority_keys[0]
            elif second_dodgeball_priority_values[0] < second_dodgeball_priority_values[1]:
                dodgeball_to_turnover_id = second_dodgeball_priority_keys[1]
            else: #same priority: random assignment
                random_index = random.randint(0, 1)
                dodgeball_to_turnover_id = second_dodgeball_priority_keys[random_index]
             # Volleyball and double dodgeball turnover
            dodgeball_to_turnover = self.state.balls[dodgeball_to_turnover_id]
            if volleyball is not None:
                volleyball.possession_team = player.team # turnover volleyball to other team
                self._designate_turnover(volleyball)
            dodgeball.possession_team = player.team # turnover dodgeball to other team
            dodgeball_to_turnover.possession_team = player.team # turnover dodgeball to other team
            self._designate_turnover(dodgeball)
            self._designate_turnover(dodgeball_to_turnover)
            logger.info("Back to hoops, volleyball, and double dodgeball turnover")
            self.state.third_dodgeball = None
            self.state.third_dodgeball_team = None
            self.state.potential_third_dodgeball_interference_kwargs = None
            for dodgeball in self.state.get_dodgeballs():
                dodgeball.beat_attempt_time = 0.0 # reset beat attempt time