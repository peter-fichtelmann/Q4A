from computer_player.moves.then_drive import ThenDrive
from computer_player.moves.volleyball_shift import VolleyballShift


class VolleyballShiftDrive(ThenDrive):
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
    first_phase_class = VolleyballShift
    first_phase_key = "shift"
    chain_reasons = frozenset({"second_pass_caught"})
