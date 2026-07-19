import logging
import time

from tutorial.scripted_computer_player import ScriptedComputerPlayer
from tutorial.tutorial_director import TutorialDirector

logger = logging.getLogger('quadball.tutorial')

# How long an unconnected tutorial room survives. Page navigations
# (lobby -> room -> game) and refreshes briefly leave the room with zero
# connections, so deletion must never be immediate.
TUTORIAL_ABANDON_GRACE_SECONDS = 30


def setup_tutorial_room(room):
    """Mark a freshly created room as a tutorial room with scripted AI and a director."""
    room.is_tutorial = True
    room.computer_player_class = ScriptedComputerPlayer
    room.tutorial_director = TutorialDirector(room)
    room.tutorial_abandoned_at = None
    logger.info("Tutorial room created: %s", room.room_id)


def mark_tutorial_room_abandoned(room):
    """Start the abandonment grace timer when a tutorial room loses its last connection."""
    if not getattr(room, 'is_tutorial', False):
        return
    if getattr(room, 'client_connections', None) or getattr(room, 'lobby_connections', None):
        return
    if getattr(room, 'tutorial_abandoned_at', None) is None:
        room.tutorial_abandoned_at = time.time()
        logger.info("Tutorial room %s has no connections; will be removed in %ss unless reattached",
                    room.room_id, TUTORIAL_ABANDON_GRACE_SECONDS)


def sweep_abandoned_tutorial_rooms(lobby_manager, grace_seconds: float = TUTORIAL_ABANDON_GRACE_SECONDS):
    """Delete tutorial rooms that have had no connections for longer than the grace period."""
    now = time.time()
    for room_id, room in list(lobby_manager.rooms.items()):
        if not getattr(room, 'is_tutorial', False):
            continue
        if getattr(room, 'client_connections', None) or getattr(room, 'lobby_connections', None):
            room.tutorial_abandoned_at = None
            continue
        abandoned_at = getattr(room, 'tutorial_abandoned_at', None)
        if abandoned_at is None:
            room.tutorial_abandoned_at = now
        elif now - abandoned_at > grace_seconds:
            del lobby_manager.rooms[room_id]
            logger.info("Tutorial room removed (abandoned): %s", room_id)
