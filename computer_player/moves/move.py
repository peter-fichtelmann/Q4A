from abc import ABC, abstractmethod
from enum import Enum
import logging
from typing import TYPE_CHECKING, List, Optional, Set

from computer_player.base_strategy import StepContext

if TYPE_CHECKING:
    from computer_player.computer_player_orchestrator import ComputerPlayerOrchestrator


class MoveStatus(Enum):
    RUNNING = "running"
    SUCCESS = "success"
    FAILURE = "failure"
    ABORTED = "aborted" # ended for reasons outside the move, e.g. human takeover or a restart


class Move(ABC):
    """
    A team play that makes a subset of a team's players behave differently from the base strategy.

    The orchestrator samples moves with a probability per second. A move starts when its
    start condition holds (`try_start`), steers its `controlled_player_ids` instead of the
    base strategies, and ends when `update_status` returns anything but RUNNING.
    """
    name: str = "move"
    side: str = "attack" # 'attack' or 'defence'
    exclusive_group: Optional[str] = None # moves of the same group never run at the same time for one team

    def __init__(self,
                 orchestrator: 'ComputerPlayerOrchestrator',
                 team: int,
                 participant_ids: List[str],
                 start_time: float,
                 max_duration: float,
                 logger: Optional[logging.Logger] = None):
        """Store the team, the participating players and the timeout."""
        self.orchestrator = orchestrator
        self.logic = orchestrator.logic
        self.team = team
        self.participant_ids = participant_ids
        self.start_time = start_time
        self.max_duration = max_duration # game seconds
        self.logger = logger or logging.getLogger("computer_player")
        self.status = MoveStatus.RUNNING
        self.end_reason: Optional[str] = None

    def end(self, status: MoveStatus, reason: str) -> None:
        """Stop the move; the orchestrator removes it at the next status check."""
        if self.status == MoveStatus.RUNNING:
            self.status = status
            self.end_reason = reason

    def update_status(self, ctx: StepContext) -> MoveStatus:
        """Check the timeout and the move's own stop criteria. Called at the start of every step."""
        if self.status == MoveStatus.RUNNING:
            if ctx.game_time - self.start_time > self.max_duration:
                self.end(MoveStatus.FAILURE, "timeout")
            else:
                self._update_status(ctx)
        return self.status

    @classmethod
    @abstractmethod
    def try_start(cls,
                  orchestrator: 'ComputerPlayerOrchestrator',
                  ctx: StepContext,
                  team: int,
                  available_cpu_ids: Set[str],
                  **params) -> Optional['Move']:
        """Return a new move if its start condition holds for `team`, otherwise None."""
        pass

    @abstractmethod
    def _update_status(self, ctx: StepContext) -> None:
        """Call `end` when a success or failure criterion is met."""
        pass

    @abstractmethod
    def controlled_player_ids(self, ctx: StepContext) -> Set[str]:
        """Players the base strategies must not steer in this step."""
        pass

    @abstractmethod
    def step(self, ctx: StepContext) -> None:
        """Steer, pass and score for the controlled players. Runs after the base strategies."""
        pass

    def describe(self) -> str:
        """Short summary for the move-ended log line."""
        return ""
