from computer_player.moves.then_drive import ThenDrive
from computer_player.moves.volleyball_crossing import VolleyballCrossing


class VolleyballCrossingDrive(ThenDrive):
    """
    Attack move: a VolleyballCrossing, followed by a VolleyballDrive of the holder after the exit run.

    Start: the start condition of the crossing. The drive starts only when the crossing's exit run
    ends with the volleyball (after a pass or a dummy) and the drive's start condition holds.

    Success: the drive succeeds, or the team scores during the crossing.
    Failure: the crossing fails, the drive cannot start after it, or the drive fails.
    Aborted: the running phase is aborted.
    The timeouts are those of the phases.
    """
    name = "volleyball_crossing_drive"
    first_phase_class = VolleyballCrossing
    first_phase_key = "crossing"
    chain_reasons = frozenset({"pass_exit_done", "dummy_exit_done"})
