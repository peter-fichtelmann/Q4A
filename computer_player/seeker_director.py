import math
from typing import List, Optional

from core.entities import Player, Vector2
from core.game_state import GameState

class SeekerDirector:
    """
    The SeekerDirector class is responsible for managing the behavior of the seeker player in the game.
    It determines the seeker's actions based on the current game state, including the positions of other players,
    the flag, and the overall game dynamics.

    Without `pursuit_lead_cap` a seeker runs at the flag runner's position one CPU step ahead.
    With it, the seeker leads the flag runner by the time it needs to get there (at most
    `pursuit_lead_cap` game seconds), and once in contact (`contact_factor` times the touching
    distance) it matches the flag runner's velocity to keep the contact the catch needs.
    """
    def __init__(self, state: GameState, pursuit_lead_cap: Optional[float] = None, contact_factor: float = 1.2):
        self.state = state
        self.pursuit_lead_cap = pursuit_lead_cap
        self.contact_factor = contact_factor

    def update_seeker_direction(self, dt: float, cpu_seekers: List[Player]) -> None:
        """Steer the CPU-controlled seekers only.

        `cpu_seekers` is supplied per call so a seeker a human has taken over is
        never re-steered here.
        """
        if self.state.seeker_on_pitch and self.state.flag_runner_on_pitch:
            for player in cpu_seekers:
                if not player.is_knocked_out:
                    if self.state.flag_runner is not None:
                        if self.pursuit_lead_cap is not None:
                            self._pursue(player, self.state.flag_runner)
                            continue
                        # move towards the flag runner's nextposition
                        next_flag_runner_position = Vector2(
                            self.state.flag_runner.position.x + self.state.flag_runner.velocity.x * dt,
                            self.state.flag_runner.position.y + self.state.flag_runner.velocity.y * dt
                        )
                        player.direction.x = next_flag_runner_position.x - player.position.x
                        player.direction.y = next_flag_runner_position.y - player.position.y

    def _pursue(self, seeker: Player, flag_runner) -> None:
        """Lead the flag runner, or stay with it while in contact."""
        dx = flag_runner.position.x - seeker.position.x
        dy = flag_runner.position.y - seeker.position.y
        distance = math.hypot(dx, dy)
        if distance <= self.contact_factor * (seeker.radius + flag_runner.radius):
            # keep the contact: run with the flag runner and lean into it
            seeker.direction = Vector2(
                flag_runner.velocity.x / seeker.max_speed + dx / max(distance, 1e-6),
                flag_runner.velocity.y / seeker.max_speed + dy / max(distance, 1e-6),
            )
            return
        lead_time = min(self.pursuit_lead_cap, distance / seeker.max_speed) if seeker.max_speed > 0 else 0.0
        seeker.direction = Vector2(dx + flag_runner.velocity.x * lead_time, dy + flag_runner.velocity.y * lead_time)
