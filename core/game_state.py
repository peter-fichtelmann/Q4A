from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
import json
from .entities import Player, Ball, Hoop, Vector2, PlayerRole, BallType

@dataclass
class GameState:
    """Central repository for all game data."""
    boundaries_x: List[float] = field(default_factory=lambda: [0.0, 60])
    boundaries_y: List[float] = field(default_factory=lambda: [0.0, 33])
    keeper_zone_x_0: float = 19.0
    keeper_zone_x_1: float = 41.0
    midline_x: float = 30.0
    team_0 = 0
    team_1 = 1
    players: Dict[str, Player] = field(default_factory=dict)  # player_id -> Player
    balls: Dict[str, Ball] = field(default_factory=dict)       # ball_id -> Ball
    hoops: Dict[str, Hoop] = field(default_factory=dict)       # hoop_id -> Hoop
    score: List[int] = field(default_factory=lambda: [0, 0])  # [team0, team1]
    squared_distances: Dict[str, List[Tuple[str, float]]] = field(default_factory=dict)          # Dictionary mapping entity_id -> list of (other_entity_id, squared_distance) tuples, sorted by distance
    squared_distances_dicts: Dict[str, Dict[str, float]] = field(default_factory=dict)   # Nested dict for faster lookups: {entity_id: {other_entity_id: squared_distance}}
    game_time: float = 0.0                                    # Seconds elapsed
    delay_of_game_time_limit: float = 10.0                     # Time limit before delay of game penalty
    delay_of_game_velocity_x_threshold: float = 0.5              # Velocity threshold in x direction the volleyball must exceed to avoid delay of game
    max_delay_of_game_warnings: int = 1                        # Number of warnings before penalty per team
    delay_of_game_warnings: Dict[int|str, int] = field(default_factory=lambda: {0: 0, 1: 0})  # Track warnings for each team
    third_dodgeball: str = None # third dodgeball id if third dodgeball
    third_dodgeball_team: str = None # team which is assigned the third dodgeball
    potential_third_dodgeball_interference_kwargs: Dict[str, str] = None # third dodgeball id and player id if potential interferenece if not beat attempt

    beat_attempt_time_limit: float = 10.0
    seeker_on_pitch: bool = False                         # Seeker enters after 20 min
    set_score: Optional[int] = None                           # Snitch capture score
    game_phase: str = "waiting"  # waiting, active, ended
    seeker_floor_seconds: int = 1200  # Time before seeker can enter
    
    def add_player(self, player: Player) -> None:
        """Add a player to the game state."""
        self.players[player.id] = player
    
    def remove_player(self, player_id: str) -> None:
        """Remove a player from the game state."""
        if player_id in self.players:
            del self.players[player_id]
    
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
    
    def get_ball(self, ball_id: str) -> Optional[Ball]:
        """Retrieve a ball by ID."""
        return self.balls.get(ball_id)
    
    def get_volleyball(self) -> Optional[Ball]:
        """Get the volleyball (returns first one found)."""
        for ball in self.balls.values():
            if ball.ball_type == BallType.VOLLEYBALL:
                return ball
        return None
    
    def get_dodgeballs(self) -> List[Ball]:
        """Get all dodgeballs."""
        return [b for b in self.balls.values() if b.ball_type == BallType.DODGEBALL]
    
    def update_score(self, team: int, points: int) -> None:
        """Add points to a team's score."""
        if team in [0, 1]:
            self.score[team] += points
    
    def update_game_time(self, dt: float) -> None:
        """Update elapsed game time."""
        self.game_time += dt
        # Seeker enters after 20 minutes (1200 seconds)
        if self.game_time >= self.seeker_floor_seconds and not self.seeker_on_pitch:
            self.seeker_on_pitch = True

    def update_player(self, player: Player) -> None:
        """Update player data in the game state."""
        if player.id in self.players:
            self.players[player.id] = player
    
    def serialize(self) -> dict:
        """Convert entire game state to JSON-serializable dict."""
        return {
            "players": {pid: p.serialize() for pid, p in self.players.items()},
            "balls": {bid: b.serialize() for bid, b in self.balls.items()},
            "hoops": {hid: h.serialize() for hid, h in self.hoops.items()},
            "score": self.score,
            "game_time": self.game_time,
            "seeker_on_pitch": self.seeker_on_pitch,
            "set_score": self.set_score,
            "game_phase": self.game_phase
        }
    
    @staticmethod
    def deserialize(data: dict) -> 'GameState':
        """Reconstruct game state from serialized dict."""
        state = GameState()
        state.players = {pid: Player.deserialize(p) for pid, p in data.get("players", {}).items()}
        state.balls = {bid: Ball.deserialize(b) for bid, b in data.get("balls", {}).items()}
        state.hoops = {hid: Hoop.deserialize(h) for hid, h in data.get("hoops", {}).items()}
        state.score = data.get("score", [0, 0])
        state.game_time = data.get("game_time", 0.0)
        state.seeker_on_pitch = data.get("seeker_on_pitch", False)
        state.set_score = data.get("set_score")
        state.game_phase = data.get("game_phase", "waiting")
        return state