from dataclasses import dataclass, field
from typing import Optional, Tuple
from enum import Enum
import json

class PlayerRole(Enum):
    """Enumeration of player roles in quadball."""
    KEEPER = "keeper"
    CHASER = "chaser"
    BEATER = "beater"
    SEEKER = "seeker"

class BallType(Enum):
    """Types of balls in quadball."""
    VOLLEYBALL = "volleyball"  # Quaffle
    DODGEBALL = "dodgeball"    # Bludger

@dataclass
class Vector2:
    """Simple 2D vector for positions and velocities."""
    x: float
    y: float
    
    def __add__(self, other: 'Vector2') -> 'Vector2':
        return Vector2(self.x + other.x, self.y + other.y)
    
    def __sub__(self, other: 'Vector2') -> 'Vector2':
        return Vector2(self.x - other.x, self.y - other.y)
    
    def __mul__(self, scalar: float) -> 'Vector2':
        return Vector2(self.x * scalar, self.y * scalar)
    
    def to_tuple(self) -> Tuple[float, float]:
        return (self.x, self.y)

    def reflect(self, normal: 'Vector2', reflect_loss: float = 0.0) -> 'Vector2':
        dot_product = self.x * normal.x + self.y * normal.y
        return Vector2(
            (self.x - 2 * dot_product * normal.x) * (1 - reflect_loss),
            (self.y - 2 * dot_product * normal.y) * (1 - reflect_loss)
        )

    @staticmethod
    def from_tuple(t: Tuple[float, float]) -> 'Vector2':
        return Vector2(t[0], t[1])
    
    def to_dict(self) -> dict:
        return {"x": self.x, "y": self.y}
    
    @staticmethod
    def from_dict(d: dict) -> 'Vector2':
        return Vector2(d["x"], d["y"])

@dataclass
class Player:
    """Represents a player in the game."""
    id: str                                    # Unique player identifier
    team: int                                   # Team 0 or 1
    role: PlayerRole                          # Keeper, Chaser, Beater, Seeker
    position: Vector2                         # Current position on field
    previous_position: Vector2 = field(default_factory=lambda: Vector2(0, 0))
    direction: Vector2 = field(default_factory=lambda: Vector2(0, 0))   # Current movement direction
    velocity: Vector2 = field(default_factory=lambda: Vector2(0, 0))
    radius: float = 0.3                  # Collision radius in meters
    is_knocked_out: bool = False             # True if knocked out by dodgeball
    has_ball: bool = False                    # True if holding a
    max_speed: float = 2               # Meters per second
    min_speed: float = 0.3               # Meters per second
    acceleration: float = 1              # Meters per second squared
    deacceleration_rate: float = 0.5          # Ratio of speed lost per second
    min_dir: float = 0.2 # of 1
    throw_velocity: float = 8         # Meters per second when throwing
    catch_cooldown: float = 0.0        # Seconds until can catch ball again
    dodgeball_immunity: bool = False      # Temporary immunity to being knocked out by dodgeballs
    inbounding: None|str = None       # if player is inbounding, if true then id of ball
    in_contact_player_ids: list[str] = field(default_factory=list)   # player ids where the player is in physical contact

    def serialize(self) -> dict:
        """Convert player to JSON-serializable dict."""
        return {
            "id": self.id,
            "team": self.team,
            "role": self.role.value,
            "position": self.position.to_dict(),
            "direction": self.direction.to_dict(),
            "velocity": self.velocity.to_dict(),
            "is_knocked_out": self.is_knocked_out,
            "has_ball": self.has_ball,
        }
    
    @staticmethod
    def deserialize(data: dict) -> 'Player':
        """Reconstruct player from serialized dict."""
        return Player(
            id=data["id"],
            team=data["team"],
            role=PlayerRole(data["role"]),
            position=Vector2.from_dict(data["position"]),
            velocity=Vector2.from_dict(data["velocity"]),
            is_knocked_out=data["is_knocked_out"],
            has_ball=data["has_ball"],
        )

@dataclass
class Ball:
    """Represents a ball in the game (quaffle, bludger, or snitch)."""
    id: str                           # Unique ball identifier
    ball_type: BallType              # Type of ball
    radius: float                    # Collision radius in meters
    position: Vector2                # Current position
    previous_position: Vector2 = field(default_factory=lambda: Vector2(0, 0))  # Previous position
    velocity: Vector2 = field(default_factory=lambda: Vector2(0, 0))
    deacceleration_rate: float = 0.0          # Deacceleration rate
    possession_team: str|int|None = None                   # None, or team who possesses the ball last
    holder_id: Optional[str] = None  # Player ID if held, None if in flight
    previous_thrower_id: Optional[str] = None  # Player ID who last threw the ball
    reflect_velocity_loss: float = 0.3  # Percentage of velocity lost on reflection with player
    turnover_to_player: Optional[str] = None  # Player ID who ball is turned over to, if any
    
    def serialize(self) -> dict:
        """Convert ball to JSON-serializable dict."""
        return {
            "id": self.id,
            "ball_type": self.ball_type.value,
            "position": self.position.to_dict(),
            "velocity": self.velocity.to_dict(),
            "holder_id": self.holder_id
        }
    
    @staticmethod
    def deserialize(data: dict) -> 'Ball':
        """Reconstruct ball from serialized dict."""
        return Ball(
            id=data["id"],
            ball_type=BallType(data["ball_type"]),
            position=Vector2.from_dict(data["position"]),
            velocity=Vector2.from_dict(data["velocity"]),
            holder_id=data.get("holder_id")
        )


class VolleyBall(Ball):
    """Represents the quaffle (volleyball) in quadball."""
    def __init__(self,
                id: str,
                radius: float,
                position: Vector2,
                crossed_hoop: Optional[Tuple[str, float]] = None,  # (hoop_id, y_position) if crossed a hoop
                inbounder: None|str = None,       # if ball is inbounded, if true then id of player
                is_dead: Optional[bool] = False,
                delay_of_game_timer: float = 0.0,
                **ball_kwargs
                ):
        super().__init__(
            id=id,
            radius=radius,
            position=position,
            ball_type=BallType.VOLLEYBALL,
            **ball_kwargs
        )
        self.crossed_hoop = crossed_hoop
        self.inbounder = inbounder
        self.is_dead = is_dead
        self.delay_of_game_timer = delay_of_game_timer


class DodgeBall(Ball):
    """Represents a dodgeball (bludger) in quadball."""
    def __init__(self,
                id: str,
                radius: float,
                position: Vector2,
                beat_attempt_time: float = 0.0,
                dead_velocity_threshold: float = 0.0,
                **ball_kwargs
                ):
        super().__init__(
            id=id,
            radius=radius,
            position=position,
            ball_type=BallType.DODGEBALL,
            **ball_kwargs
        )
        self.beat_attempt_time = beat_attempt_time
        self.dead_velocity_threshold = dead_velocity_threshold

@dataclass
class Hoop:
    """Represents a goal hoop."""
    id: str              # Unique hoop identifier
    team: int           # Team this hoop belongs to
    position: Vector2    # Center position of hoop
    radius: float        # Collision radius in meters
    thickness: float = 0.1  # Thickness of hoop ring
    
    def serialize(self) -> dict:
        """Convert hoop to JSON-serializable dict."""
        return {
            "id": self.id,
            "team": self.team,
            "position": self.position.to_dict(),
            "radius": self.radius,
            "thickness": self.thickness
        }

    @staticmethod
    def deserialize(data: dict) -> 'Hoop':
        return Hoop(
            id=data.get("id"),
            team=data.get("team"),
            position=Vector2.from_dict(data.get("position", {"x": 0, "y": 0})),
            radius=data.get("radius", 0.0),
            thickness=data.get("thickness", 0.1)
        )
