from typing import TYPE_CHECKING, Dict, FrozenSet, Optional, Set

from computer_player.base_strategy import StepContext
from computer_player.moves.move import Move, MoveStatus
from computer_player.moves.volleyball_drive import VolleyballDrive

if TYPE_CHECKING:
    from computer_player.computer_player_orchestrator import ComputerPlayerOrchestrator


class ThenDrive(Move):
    """
    Attack move: a first move, followed by a VolleyballDrive of the then carrier.

    Subclasses set the first move (`first_phase_class`), its config key and end-reason prefix
    (`first_phase_key`), and the end reasons of the first move that start the drive (`chain_reasons`).

    Start: the start condition of the first move. The drive starts only when the first move
    succeeds with one of the chain reasons and the drive's start condition holds for the carrier.

    Success: the drive succeeds, or the first move succeeds with another reason (e.g. a goal).
    Failure: the first move fails, the drive cannot start after it, or the drive fails.
    Aborted: the running phase is aborted.
    The timeouts are those of the phases.
    """
    side = "attack"
    exclusive_group = "volleyball_carrier"
    first_phase_class: type = Move
    first_phase_key: str = "first"
    chain_reasons: FrozenSet[str] = frozenset()

    def __init__(self,
                 orchestrator: 'ComputerPlayerOrchestrator',
                 team: int,
                 first: Move,
                 drive_params: Dict,
                 logger=None):
        """Wrap the started first move; the drive is started later with `drive_params`."""
        # phases time out on their own, so the combined move only needs an upper bound
        max_duration = first.max_duration + drive_params.get('max_duration', 15)
        super().__init__(orchestrator, team, list(first.participant_ids), first.start_time, max_duration, logger)
        self.first = first
        self.drive: Optional[VolleyballDrive] = None
        self.drive_params = drive_params

    @property
    def phase(self) -> Move:
        """The running phase."""
        return self.drive if self.drive is not None else self.first

    @classmethod
    def try_start(cls,
                  orchestrator: 'ComputerPlayerOrchestrator',
                  ctx: StepContext,
                  team: int,
                  available_cpu_ids: Set[str],
                  drive: Optional[Dict] = None,
                  logger=None,
                  **params) -> Optional['ThenDrive']:
        """Start if the first move can start (its config is the `first_phase_key` entry of `params`)."""
        first_params = params.get(cls.first_phase_key) or {}
        first_move = cls.first_phase_class.try_start(orchestrator, ctx, team, available_cpu_ids, logger=logger, **first_params)
        if first_move is None:
            return None
        return cls(orchestrator, team, first_move, dict(drive or {}), logger=logger)

    def _start_drive(self, ctx: StepContext) -> bool:
        """Start the drive for the current carrier. Returns False if its start condition does not hold."""
        taken_ids = set()
        for move in self.orchestrator.active_moves:
            if move is not self:
                taken_ids |= set(move.participant_ids)
        available_cpu_ids = {player_id for player_id in ctx.cpu_player_id_set if player_id not in taken_ids}
        self.drive = VolleyballDrive.try_start(self.orchestrator, ctx, self.team, available_cpu_ids, logger=self.logger, **self.drive_params)
        if self.drive is None:
            return False
        self.participant_ids = list(self.drive.participant_ids)
        self.logger.info("%s starts drive: team=%s carrier=%s", type(self).__name__, self.team, self.drive.carrier_id[-4:])
        return True

    def _update_status(self, ctx: StepContext) -> None:
        """Advance the running phase and switch from the first move to the drive on a chain reason."""
        status = self.phase.update_status(ctx)
        if status == MoveStatus.RUNNING:
            return
        if self.drive is not None:
            self.end(status, f"drive:{self.drive.end_reason}")
            return
        if status == MoveStatus.SUCCESS and self.first.end_reason in self.chain_reasons:
            if not self._start_drive(ctx):
                self.end(MoveStatus.FAILURE, "drive_not_startable")
            return
        self.end(status, f"{self.first_phase_key}:{self.first.end_reason}")

    def controlled_player_ids(self, ctx: StepContext) -> Set[str]:
        """Players of the running phase."""
        if self.status != MoveStatus.RUNNING:
            return set()
        return self.phase.controlled_player_ids(ctx)

    def step(self, ctx: StepContext) -> None:
        """Step the running phase and adopt its end."""
        if self.status != MoveStatus.RUNNING:
            return
        phase = self.phase
        phase.step(ctx)
        if phase.status != MoveStatus.RUNNING:
            # e.g. the shift found no good pass option; reported at the next status check
            self.end(phase.status, f"{'drive' if phase is self.drive else self.first_phase_key}:{phase.end_reason}")

    def describe(self) -> str:
        """Both phases."""
        text = f"{self.first_phase_key}[{self.first.describe()}]"
        if self.drive is not None:
            text += f" drive[{self.drive.describe()}]"
        return text
