from computer_player.moves.then_drive import ThenDrive
from computer_player.moves.volleyball_block import VolleyballBlock


class VolleyballBlockDrive(ThenDrive):
    """
    Attack move: a VolleyballBlock, followed by a VolleyballDrive of the carrier once the defender is passed.

    Start: the start condition of the block. The drive starts only when the block succeeds because the
    defender is passed or knocked out, and the drive's start condition holds.

    Success: the drive succeeds, or the team scores during the block.
    Failure: the block fails, the drive cannot start after it, or the drive fails.
    Aborted: the running phase is aborted.
    The timeouts are those of the phases.
    """
    name = "volleyball_block_drive"
    first_phase_class = VolleyballBlock
    first_phase_key = "block"
    chain_reasons = frozenset({"defender_passed", "defender_gone"})
