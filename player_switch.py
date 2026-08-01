"""Let a human hand control of their player to a CPU teammate and take another over.

Two modes, both restricted to the human's own team:

* `switch_same_position` walks the same-role teammates in a stable rotation, so
  repeated presses visit every eligible player and then loop back around.
* `switch_next_position` walks the position cycle chaser -> keeper -> beater ->
  seeker -> chaser and takes the highest-priority candidate at the first position
  that has one.

A player is eligible only when no connection currently controls it, i.e. when it
is CPU-driven. Everything here runs synchronously between game ticks (there is no
`await` between reading and mutating), so no locking is needed.
"""

import logging
from typing import Dict, List, Optional

from config import Config
from core.entities import BallType, Player, PlayerRole
from core.game_logic.utility_logic import UtilityLogic

logger = logging.getLogger('quadball')

# Order the `next_position` button walks through.
ROLE_CYCLE = [PlayerRole.CHASER, PlayerRole.KEEPER, PlayerRole.BEATER, PlayerRole.SEEKER]

SAME_POSITION = 'same_position'
NEXT_POSITION = 'next_position'


# ---- control registry helpers ----

def apply_human_tuning(player: Player) -> None:
    """Give a player the responsiveness a human needs (dead zone + minimum speed)."""
    player.min_speed = Config.PLAYER_MIN_SPEED
    player.min_dir = Config.PLAYER_MIN_DIR


def apply_cpu_tuning(player: Player) -> None:
    """Give a player the CPU tuning: no dead zone, no minimum speed."""
    player.min_speed = Config.COMPUTER_PLAYER_MIN_SPEED
    player.min_dir = Config.COMPUTER_PLAYER_MIN_DIR


def stop(player: Player) -> None:
    """Zero a player's steering input in place.

    Mutating rather than rebinding keeps the same Vector2 the websocket handler
    and the CPU write into.
    """
    player.direction.x = 0.0
    player.direction.y = 0.0


def apply_switch(room, connection_player_id: str, old_player_id: str, new_player_id: str) -> None:
    """Move a connection's control from `old_player_id` to `new_player_id`.

    The released player would otherwise coast on the human's last direction until
    the CPU next writes to it (up to `COMPUTER_PLAYER_TICK_RATE` ticks later), so
    both players are stopped.
    """
    state = room.game_state
    old_player = state.get_player(old_player_id)
    new_player = state.get_player(new_player_id)

    room.controlled_player_by_player[connection_player_id] = new_player_id

    if old_player is not None:
        apply_cpu_tuning(old_player)
        stop(old_player)
    if new_player is not None:
        apply_human_tuning(new_player)
        stop(new_player)


# ---- eligibility ----

def _controlled_ids(room) -> set:
    """Ids currently driven by a human connection."""
    return set(room.controlled_player_by_player.values())


def _role_available(state, role: PlayerRole) -> bool:
    """Seekers can only be taken over once they are actually on the pitch."""
    if role == PlayerRole.SEEKER:
        return bool(state.seeker_on_pitch)
    return True


def _candidates(room, team: int, role: PlayerRole) -> List[Player]:
    """CPU-driven players of `team` at `role`, in game state insertion order."""
    if not _role_available(room.game_state, role):
        return []
    controlled = _controlled_ids(room)
    return [
        player for player in room.game_state.players.values()
        if player.team == team and player.role == role and player.id not in controlled
    ]


# ---- priority ranking ----

def _squared_distance_to_own_center_hoop(state, player: Player) -> float:
    hoop = state.hoops.get(f'hoop_{player.team}_center')
    if hoop is None:
        return 0.0
    return UtilityLogic._squared_distance(player.position, hoop.position)


def _nearest_to_volleyball(state, players: List[Player]) -> Optional[Player]:
    volleyball = state.volleyball
    if volleyball is None or not players:
        return None
    return min(players, key=lambda p: UtilityLogic._squared_distance(p.position, volleyball.position))


def _nearest_to_own_center_hoop(state, players: List[Player]) -> Optional[Player]:
    if not players:
        return None
    return min(players, key=lambda p: _squared_distance_to_own_center_hoop(state, p))


def _holds_dodgeball(state, player: Player) -> bool:
    """True when the player carries a dodgeball (`has_ball` stores the ball id)."""
    if not player.has_ball:
        return False
    ball = state.get_ball(player.has_ball)
    return ball is not None and ball.ball_type == BallType.DODGEBALL


def _rank_chaser_keeper(state, candidates: List[Player]) -> Optional[Player]:
    """Closest to the volleyball; if every candidate is off stick, closest to own hoop."""
    on_stick = [p for p in candidates if not p.is_knocked_out]
    return _nearest_to_volleyball(state, on_stick) or _nearest_to_own_center_hoop(state, candidates)


def _rank_beater(state, candidates: List[Player]) -> Optional[Player]:
    """Loaded beaters go for the volleyball, empty ones for a free dodgeball."""
    on_stick = [p for p in candidates if not p.is_knocked_out]

    loaded = [p for p in on_stick if _holds_dodgeball(state, p)]
    best_loaded = _nearest_to_volleyball(state, loaded)
    if best_loaded is not None:
        return best_loaded

    free_dodgeballs = [ball for ball in state.dodgeballs if ball.holder_id is None]
    if on_stick and free_dodgeballs:
        return min(
            on_stick,
            key=lambda p: min(
                UtilityLogic._squared_distance(p.position, ball.position) for ball in free_dodgeballs
            ),
        )

    return _nearest_to_own_center_hoop(state, on_stick or candidates)


def _rank_seeker(state, candidates: List[Player]) -> Optional[Player]:
    """Closest to the flag runner; if every candidate is off stick, closest to own hoop."""
    on_stick = [p for p in candidates if not p.is_knocked_out]
    flag_runner = state.flag_runner
    if on_stick and flag_runner is not None:
        return min(
            on_stick,
            key=lambda p: UtilityLogic._squared_distance(p.position, flag_runner.position),
        )
    return _nearest_to_own_center_hoop(state, candidates)


_RANKERS = {
    PlayerRole.CHASER: _rank_chaser_keeper,
    PlayerRole.KEEPER: _rank_chaser_keeper,
    PlayerRole.BEATER: _rank_beater,
    PlayerRole.SEEKER: _rank_seeker,
}


def _best_candidate(state, role: PlayerRole, candidates: List[Player]) -> Optional[Player]:
    ranker = _RANKERS.get(role)
    if ranker is None or not candidates:
        return None
    return ranker(state, candidates)


# ---- the two switch modes ----

def switch_same_position(room, current_player_id: str) -> Optional[str]:
    """Return the next same-team, same-role CPU player, or None if there is none.

    The rotation is over `game_state.players` insertion order and starts from the
    player currently controlled, so pressing the button repeatedly cycles through
    every eligible teammate and wraps around. A distance ranking would reorder
    every tick and could revisit the same player.
    """
    current = room.game_state.get_player(current_player_id)
    if current is None:
        return None
    if not _role_available(room.game_state, current.role):
        return None

    same_position = [
        player for player in room.game_state.players.values()
        if player.team == current.team and player.role == current.role
    ]
    if len(same_position) < 2:
        return None

    controlled = _controlled_ids(room)
    start = next((i for i, p in enumerate(same_position) if p.id == current_player_id), None)
    if start is None:
        return None

    for offset in range(1, len(same_position)):
        candidate = same_position[(start + offset) % len(same_position)]
        if candidate.id not in controlled:
            return candidate.id
    return None


def switch_next_position(room, current_player_id: str) -> Optional[str]:
    """Return the best CPU player at the next position that has one, else None.

    Walks the role cycle forward; a position with no eligible player is skipped.
    Arriving back at the current position means the switch failed.
    """
    state = room.game_state
    current = state.get_player(current_player_id)
    if current is None or current.role not in ROLE_CYCLE:
        return None

    start = ROLE_CYCLE.index(current.role)
    # range stops before the full cycle: reaching the current position again is a failure.
    for offset in range(1, len(ROLE_CYCLE)):
        role = ROLE_CYCLE[(start + offset) % len(ROLE_CYCLE)]
        candidates = _candidates(room, current.team, role)
        best = _best_candidate(state, role, candidates)
        if best is not None:
            return best.id
    return None


_SWITCHERS = {
    SAME_POSITION: switch_same_position,
    NEXT_POSITION: switch_next_position,
}


def request_switch(room, connection_player_id: str, current_player_id: str, mode: str) -> Optional[str]:
    """Resolve and apply a switch request. Returns the new player id, or None on failure.

    Failure is a normal outcome (no eligible teammate, switching disabled) and is
    logged at INFO so the client's forbidden sign has a matching server-side trace.
    """
    switcher = _SWITCHERS.get(mode)
    if switcher is None:
        logger.info("Player switch rejected: unknown mode %r (room=%s)", mode, room.room_id)
        return None

    if not getattr(room, 'player_switch_enabled', True):
        logger.info(
            "Player switch (%s) rejected: switching is disabled in room=%s",
            mode, room.room_id,
        )
        return None

    if current_player_id is None or room.game_state.get_player(current_player_id) is None:
        logger.info(
            "Player switch (%s) rejected: no controlled player (room=%s connection=%s)",
            mode, room.room_id, connection_player_id,
        )
        return None

    new_player_id = switcher(room, current_player_id)
    if new_player_id is None:
        logger.info(
            "Player switch (%s) found no eligible player for %s (room=%s)",
            mode, current_player_id, room.room_id,
        )
        return None

    apply_switch(room, connection_player_id, current_player_id, new_player_id)
    logger.info(
        "Player switch (%s): %s -> %s (room=%s)",
        mode, current_player_id, new_player_id, room.room_id,
    )
    return new_player_id


# ---- connection lifecycle ----

def claim(room, connection_player_id: str, player_id: str) -> None:
    """Mark `player_id` as human-driven for this connection."""
    room.controlled_player_by_player[connection_player_id] = player_id
    player = room.game_state.get_player(player_id)
    if player is not None:
        apply_human_tuning(player)


def release_to_connection_player(room, connection_player_id: str) -> None:
    """Undo any switches for this connection when it goes away.

    The connection's own player stays human-owned (an unconnected human is a
    statue today, and this keeps that behaviour), while a player it had taken
    over is handed back to the CPU.
    """
    controlled: Dict[str, str] = room.controlled_player_by_player
    current_id = controlled.get(connection_player_id)
    if current_id is None or current_id == connection_player_id:
        return
    apply_switch(room, connection_player_id, current_id, connection_player_id)
