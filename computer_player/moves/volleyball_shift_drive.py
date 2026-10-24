from typing import TYPE_CHECKING, Dict, Optional, Set

from computer_player.base_strategy import StepContext
from computer_player.moves.move import Move, MoveStatus
from computer_player.moves.volleyball_drive import VolleyballDrive
from computer_player.moves.volleyball_shift import VolleyballShift

if TYPE_CHECKING:
    from computer_player.computer_player_orchestrator import ComputerPlayerOrchestrator


class VolleyballShiftDrive(Move):
    """
    Attack move: a VolleyballShift, followed by a VolleyballDrive of the new carrier.

    Start: the start condition of the shift. The drive starts only when the shift succeeds with
    its second pass caught and the drive's start condition holds for the new carrier.

    Success: the drive succeeds, or the team scores during the shift.
    Failure: the shift fails, the drive cannot start after the shift, or the drive fails.
    Aborted: the running phase is aborted.
    The timeouts are those of the phases.
    """
    name = "volleyball_shift_drive"
    side = "attack"
    exclusive_group = "volleyball_carrier"

    def __init__(self,
                 orchestrator: 'ComputerPlayerOrchestrator',
                 team: int,
                 shift: VolleyballShift,
                 drive_params: Dict,
                 logger=None):
        """Wrap the started shift; the drive is started later with `drive_params`."""
        # phases time out on their own, so the combined move only needs an upper bound
        max_duration = shift.max_duration + drive_params.get('max_duration', 15)
        super().__init__(orchestrator, team, list(shift.participant_ids), shift.start_time, max_duration, logger)
        self.shift = shift
        self.drive: Optional[VolleyballDrive] = None
        self.drive_params = drive_params

    @property
    def phase(self) -> Move:
        """The running phase."""
        return self.drive if self.drive is not None else self.shift

    @classmethod
    def try_start(cls,
                  orchestrator: 'ComputerPlayerOrchestrator',
                  ctx: StepContext,
                  team: int,
                  available_cpu_ids: Set[str],
                  shift: Optional[Dict] = None,
                  drive: Optional[Dict] = None,
                  logger=None,
                  **params) -> Optional['VolleyballShiftDrive']:
        """Start if the shift can start."""
        shift_move = VolleyballShift.try_start(orchestrator, ctx, team, available_cpu_ids, logger=logger, **(shift or {}))
        if shift_move is None:
            return None
        return cls(orchestrator, team, shift_move, dict(drive or {}), logger=logger)

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
        self.logger.info("VolleyballShiftDrive starts drive: team=%s carrier=%s", self.team, self.drive.carrier_id[-4:])
        return True

    def _update_status(self, ctx: StepContext) -> None:
        """Advance the running phase and switch from the shift to the drive on a caught second pass."""
        status = self.phase.update_status(ctx)
        if status == MoveStatus.RUNNING:
            return
        if self.drive is not None:
            self.end(status, f"drive:{self.drive.end_reason}")
            return
        if status == MoveStatus.SUCCESS and self.shift.end_reason == "second_pass_caught":
            if not self._start_drive(ctx):
                self.end(MoveStatus.FAILURE, "drive_not_startable")
            return
        self.end(status, f"shift:{self.shift.end_reason}")

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
            self.end(phase.status, f"{'drive' if phase is self.drive else 'shift'}:{phase.end_reason}")

    def describe(self) -> str:
        """Both phases."""
        text = f"shift[{self.shift.describe()}]"
        if self.drive is not None:
            text += f" drive[{self.drive.describe()}]"
        return text
