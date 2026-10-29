from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import json
from .entities import Player, Ball, Hoop, Vector2, PlayerRole, BallType, VolleyBall, DodgeBall, FlagRunner

@dataclass
class ThrowCharge:
    """A throw being charged: the ball leaves once `ticks` reaches `release_ticks`, or earlier when a human lets go."""
    ball_id: str
    release_ticks: int                          # ticks of charging until the throw is released
    ticks: int = 0                              # ticks charged so far; strength ratio = ticks / throw_charge_full_ticks
    direction: Optional[Vector2] = None         # fixed throw direction (computer players); None: the player's direction at release
    target_id: Optional[str] = None             # player or hoop a computer player aims at, to re-aim during the charge

    def copy(self) -> 'ThrowCharge':
        return ThrowCharge(self.ball_id, self.release_ticks, self.ticks,
                           self.direction.copy() if self.direction is not None else None, self.target_id)

@dataclass
class GameState:
    """Central repository for all game data."""
    is_game_live: bool = True
    is_game_over: bool = False
    boundaries_x: List[float] = field(default_factory=lambda: [0.0, 60])
    boundaries_y: List[float] = field(default_factory=lambda: [0.0, 33])
    keeper_zone_x_0: float = 19.0
    keeper_zone_x_1: float = 41.0
    midline_x: float = 30.0
    team_0 = 0
    team_1 = 1
    players: Dict[str, Player] = field(default_factory=dict)  # player_id -> Player
    keeper_team_0: Player = None
    keeper_team_1: Player = None
    balls: Dict[str, Ball] = field(default_factory=dict)       # ball_id -> Ball
    volleyball: VolleyBall = None
    dodgeballs: List[DodgeBall] = field(default_factory=list)
    hoops: Dict[str, Hoop] = field(default_factory=dict)       # hoop_id -> Hoop
    flag_runner: FlagRunner = None
    score: List[int] = field(default_factory=lambda: [0, 0])  # [team0, team1]
    max_player_radius: float = 0.35
    squared_distances_player_player_dicts: Dict[str, Dict[str, float]] = field(default_factory=dict)   # Nested dict for faster lookups: {entity_id: {other_entity_id: squared_distance}}
    squared_distances_ball_ball_dicts: Dict[str, Dict[str, float]] = field(default_factory=dict)     # Nested dict for player-ball distances: {player_id: {ball_id: squared_distance}}
    squared_distances_ball_player_dicts: Dict[str, Dict[str, float]] = field(default_factory=dict)   # Nested dict for player-ball distances: {ball_id: {player_id: squared_distance}}
    squared_distances_player_player: Dict[str, List[Tuple[str, float]]] = field(default_factory=dict)          # Dictionary mapping entity_id -> list of (other_entity_id, squared_distance) tuples, sorted by distance
    squared_distances_ball_player: Dict[str, List[Tuple[str, float]]] = field(default_factory=dict)          # Dictionary mapping entity_id -> list of (other_entity_id, squared_distance) tuples, sorted by distance
    min_squared_distance_player_player_calculation: float = 4 # only calculate and store distances for player pairs that are within this squared distance to save on calculations and memory, since distant players won't interact with each other
    game_time: float = 0.0                                    # Seconds elapsed
    delay_of_game_time_limit: float = 10.0                     # Time limit before delay of game penalty
    delay_of_game_velocity_x_threshold: float = 0.5              # Velocity threshold in x direction the volleyball must exceed to avoid delay of game
    max_delay_of_game_warnings: int = 1                        # Number of warnings before penalty per team
    delay_of_game_warnings: Dict[int|str, int] = field(default_factory=lambda: {0: 0, 1: 0})  # Track warnings for each team
    no_delay_of_game_opponent_chaser_squared_distance_threshold: float = 4
    no_delay_of_game_opponent_beater_squared_distance_threshold: float = 16
    stalled_volleyball_time_limit: float = 10.0                # Game seconds a tackled carrier keeps the volleyball before it goes to the closest opponent chaser/keeper
    stalled_volleyball_countdown: float = 5.0                  # Last game seconds of the stalled volleyball limit counted down on the client
    stalled_volleyball_tackle_grace: float = 2.0               # Game seconds without a new tackle after which the carrier counts as no longer tackled
    turnover_throw_block_time: float = 3.0                     # Game seconds a player receiving a turnover ball cannot throw it
    throw_blocked_until: Dict[str, float] = field(default_factory=dict)  # player id -> game time until which throwing is blocked
    throw_charge_full_ticks: int = 10                          # ticks of charging until a throw has full strength
    throw_charges: Dict[str, ThrowCharge] = field(default_factory=dict)  # player id -> throw being charged
    stalled_turnover_tackle_immunity_time: float = 1.5         # Game seconds the player receiving a stalled volleyball turnover cannot be tackled
    is_stalled_turnover_pending: bool = False                  # True while the volleyball in turnover was turned over for being stalled
    tackle_immune_until: Dict[str, float] = field(default_factory=dict)  # player id -> game time until which the player cannot be tackled
    third_dodgeball: str = None # third dodgeball id if third dodgeball
    third_dodgeball_team: str = None # team which is assigned the third dodgeball
    potential_third_dodgeball_interference_kwargs: Dict[str, str] = field(default_factory=lambda: {'player_id': None, 'dodgeball_id': None}) # third dodgeball id and player id if potential interferenece if not beat attempt
    beat_attempt_time_limit: float = 10.0
    flag_runner_floor_seconds: int = 1140  # Time before flag runner can enter
    seeker_floor_seconds: int = 1200  # Time before seeker can enter
    flag_runner_on_pitch: bool = False                         # Flag runner enters after 19 min
    seeker_on_pitch: bool = False                         # Seeker enters after 20 min
    is_overtime: bool = False                          # True if game is in overtime
    set_score: Optional[int] = None                           # Snitch capture score
    flag_catched_team: Optional[int|str] = None               # Team that catched the flag
    flag_catch_continue_timer: float = 60                     # Game seconds left of the catch-resolution pause
    flag_catch_continue_timer_total: float = 60                # Length of that pause, so clients can stage their catch message on it
    
    def add_player(self, player: Player) -> None:
        """Add a player to the game state."""
        self.players[player.id] = player
        if player.role == PlayerRole.KEEPER:
            if player.team == self.team_0:
                self.keeper_team_0 = player
            elif player.team == self.team_1:
                self.keeper_team_1 = player
    
    def remove_player(self, player_id: str) -> None:
        """Remove a player from the game state."""
        if player_id in self.players:
            del self.players[player_id]
            if self.keeper_team_0.id == player_id:
                self.keeper_team_0 = None
            elif self.keeper_team_1.id == player_id:
                self.keeper_team_1 = None
    
    def get_player(self, player_id: str) -> Optional[Player]:
        """Retrieve a player by ID."""
        return self.players.get(player_id)
    
    def get_players_by_team(self, team: int) -> List[Player]:
        """Get all players on a specific team."""
        return [p for p in self.players.values() if p.team == team]
    
    def get_players_by_role(self, role: PlayerRole, team: Optional[int] = None) -> List[Player]:
        """Get players with a specific role, optionally filtered by team."""
        players = [p for p in self.players.values() if p.role == role]
        if team is not None:
            players = [p for p in players if p.team == team]
        return players
    
    def add_ball(self, ball: Ball) -> None:
        """Add a ball to the game state."""
        self.balls[ball.id] = ball

    def add_volleyball(self, volleyball: VolleyBall) -> None:
        """Add the volleyball to the game state."""
        self.volleyball = volleyball
        self.balls[volleyball.id] = volleyball

    def add_dodgeball(self, dodgeball: DodgeBall) -> None:
        """Add a dodgeball to the game state."""
        self.dodgeballs.append(dodgeball)
        self.balls[dodgeball.id] = dodgeball
    
    def get_ball(self, ball_id: str) -> Optional[Ball]:
        """Retrieve a ball by ID."""
        return self.balls.get(ball_id)

    def add_flag_runner(self, flag_runner: FlagRunner) -> None:
        """Add a flag runner to the game state."""  
        self.flag_runner = flag_runner

    def update_score(self, team: int, points: int) -> None:
        """Add points to a team's score."""
        if team in [0, 1]:
            self.score[team] += points
        # check if set score is reached and game is over
        if self.is_overtime and self.score[team] >= self.set_score:
            self.is_game_over = True
            self.is_game_live = False
    
    def block_turnover_throw(self, player_id: str) -> None:
        """Block throwing for a player who just picked up a turnover ball."""
        self.throw_blocked_until[player_id] = self.game_time + self.turnover_throw_block_time

    def grant_stalled_turnover_tackle_immunity(self, player_id: str) -> None:
        """Protect a player who just picked up a stalled volleyball turnover from tackles."""
        self.tackle_immune_until[player_id] = self.game_time + self.stalled_turnover_tackle_immunity_time

    def update_game_time(self, dt: float) -> None:
        """Update elapsed game time."""
        self.game_time += dt
        # Seeker enters after 20 minutes (1200 seconds)
        if self.is_overtime:
            return
        if self.game_time >= self.flag_runner_floor_seconds:
            self.flag_runner_on_pitch = True
        if self.game_time >= self.seeker_floor_seconds:
            self.seeker_on_pitch = True

    def update_player(self, player: Player) -> None:
        """Update player data in the game state."""
        if player.id in self.players:
            previous_player = self.players[player.id]
            if previous_player.role == PlayerRole.KEEPER:
                if previous_player.team == self.team_0:
                    self.keeper_team_0 = None
                elif previous_player.team == self.team_1:
                    self.keeper_team_1 = None
            if player.role == PlayerRole.KEEPER:
                if player.team == self.team_0:
                    self.keeper_team_0 = player
                elif player.team == self.team_1:
                    self.keeper_team_1 = player
            self.players[player.id] = player

    def copy(self) -> 'GameState':
        return GameState(
            is_game_live=self.is_game_live,
            is_game_over=self.is_game_over,
            boundaries_x=self.boundaries_x,
            boundaries_y=self.boundaries_y,
            keeper_zone_x_0=self.keeper_zone_x_0,
            keeper_zone_x_1=self.keeper_zone_x_1,
            midline_x=self.midline_x,
            players={pid: player.copy() for pid, player in self.players.items()},
            balls={bid: ball.copy() for bid, ball in self.balls.items()},
            volleyball=self.volleyball.copy(),
            dodgeballs=[dodgeball.copy() for dodgeball in self.dodgeballs],
            hoops=self.hoops,
            flag_runner=self.flag_runner.copy() if self.flag_runner is not None else None,
            flag_runner_on_pitch=self.flag_runner_on_pitch,
            score=self.score,
            max_player_radius=self.max_player_radius,
            game_time=self.game_time,
            delay_of_game_time_limit=self.delay_of_game_time_limit,
            delay_of_game_velocity_x_threshold=self.delay_of_game_velocity_x_threshold,
            max_delay_of_game_warnings=self.max_delay_of_game_warnings,
            delay_of_game_warnings=self.delay_of_game_warnings.copy(),
            stalled_volleyball_time_limit=self.stalled_volleyball_time_limit,
            stalled_volleyball_countdown=self.stalled_volleyball_countdown,
            stalled_volleyball_tackle_grace=self.stalled_volleyball_tackle_grace,
            turnover_throw_block_time=self.turnover_throw_block_time,
            throw_blocked_until=self.throw_blocked_until.copy(),
            throw_charge_full_ticks=self.throw_charge_full_ticks,
            throw_charges={player_id: charge.copy() for player_id, charge in self.throw_charges.items()},
            stalled_turnover_tackle_immunity_time=self.stalled_turnover_tackle_immunity_time,
            is_stalled_turnover_pending=self.is_stalled_turnover_pending,
            tackle_immune_until=self.tackle_immune_until.copy(),
            third_dodgeball=self.third_dodgeball,
            third_dodgeball_team=self.third_dodgeball_team,
            potential_third_dodgeball_interference_kwargs=(
                self.potential_third_dodgeball_interference_kwargs.copy()
                if self.potential_third_dodgeball_interference_kwargs is not None
                else None
            ),
            beat_attempt_time_limit=self.beat_attempt_time_limit,
            seeker_on_pitch=self.seeker_on_pitch,
            set_score=self.set_score,
            seeker_floor_seconds=self.seeker_floor_seconds,
            flag_runner_floor_seconds=self.flag_runner_floor_seconds,
            is_overtime=self.is_overtime,
            flag_catched_team=self.flag_catched_team,
            flag_catch_continue_timer=self.flag_catch_continue_timer,
            flag_catch_continue_timer_total=self.flag_catch_continue_timer_total
        )

    def __copy__(self) -> 'GameState':
        return self.copy()

    def __deepcopy__(self, memo: dict[int, object]) -> 'GameState':
        copied = self.copy()
        memo[id(self)] = copied
        return copied
    
    def serialize_dynamic_attributes(self) -> dict:
        """
        Serialize only the dynamic attributes (modified by game_logic) of the game state.
        In addition the squared distance dictionaries are not included. Their main purpose is to speed up calculations in game_logic,
        but they do not contain any additional information.

        This allows more efficient logging.
        """
        # RoomJsonlLogger encodes this dict positionally and RoomJsonlStateReader decodes it by
        # these same keys. Append new keys at the end: removing or moving a key invalidates
        # already written state logs.
        return {
            "is_game_live": self.is_game_live,
            "is_game_over": self.is_game_over,
            # "boundaries_x": self.boundaries_x,
            # "boundaries_y": self.boundaries_y,
            # "keeper_zone_x_0": self.keeper_zone_x_0,
            # "keeper_zone_x_1": self.keeper_zone_x_1,
            # "midline_x": self.midline_x,
            # "team_0": self.team_0,
            # "team_1": self.team_1,
            "players": self.players,
            "balls": self.balls,
            "volleyball": self.volleyball,
            "dodgeballs": self.dodgeballs,
            "score": self.score,
            "game_time": self.game_time,
            "delay_of_game_warnings": self.delay_of_game_warnings,
            "third_dodgeball": self.third_dodgeball,
            "third_dodgeball_team": self.third_dodgeball_team,
            "potential_third_dodgeball_interference_kwargs": self.potential_third_dodgeball_interference_kwargs,
            "seeker_on_pitch": self.seeker_on_pitch,
            "set_score": self.set_score,
            # Appended at the end on purpose: RoomJsonlLogger encodes this dict positionally,
            # so inserting anywhere else would misalign already written state logs.
            "flag_runner": self.flag_runner,
            "flag_runner_on_pitch": self.flag_runner_on_pitch,
            "is_overtime": self.is_overtime,
            "flag_catched_team": self.flag_catched_team,
            "flag_catch_continue_timer": self.flag_catch_continue_timer
        }

    def serialize_to_broadcast(self) -> dict:
        """Convert entire game state to JSON-serializable dict."""
        return {
            "is_game_live": self.is_game_live,
            "is_game_over": self.is_game_over,
            "players": {pid: p.serialize() for pid, p in self.players.items()},
            "balls": {bid: b.serialize() for bid, b in self.balls.items()},
            "hoops": {hid: h.serialize() for hid, h in self.hoops.items()},
            "flag_runner": self.flag_runner.serialize() if self.flag_runner is not None else None,
            "score": self.score,
            "game_time": self.game_time,
            "flag_runner_on_pitch": self.flag_runner_on_pitch,
            "seeker_on_pitch": self.seeker_on_pitch,
            "set_score": self.set_score,
            "is_overtime": self.is_overtime,
            "flag_catched_team": self.flag_catched_team,
            "flag_catch_continue_timer": self.flag_catch_continue_timer,
            # Static, but the client needs it to know where half of the pause is.
            "flag_catch_continue_timer_total": self.flag_catch_continue_timer_total
            # "game_phase": self.game_phase
        }