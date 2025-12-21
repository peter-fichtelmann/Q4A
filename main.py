import asyncio
import uuid
import json
import secrets
try:
    import orjson as _orjson  # optional fast, compact serializer
except Exception:
    _orjson = None
from typing import Dict, Set, Optional
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Response
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from datetime import datetime, timedelta
import os
import struct
import time
from collections import deque

# Import your game modules
from core.game_state import GameState
from core.entities import Player, VolleyBall, DodgeBall, Vector2, PlayerRole, BallType, Hoop
from core.game_logic import GameLogicSystem
from config import Config
import logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger('quadball')

app = FastAPI(title="Quadball Game Server")

# Serve static files
app.mount("/client", StaticFiles(directory="client"), name="client")

# ==================== DATA MODELS ====================

class Room(BaseModel):
    room_id: str
    passkey: str
    creator_id: str
    creator_name: str
    players: Dict[str, Dict] = {}
    game_started: bool = False
    max_players: int = 12
    created_at: datetime = None
    
    class Config:
        arbitrary_types_allowed = True

class GameRoom:
    """Manages a single game room"""
    def __init__(self, room_id: str, passkey: str, creator_id: str, creator_name: str):
        self.room_id = room_id
        self.passkey = passkey
        self.creator_id = creator_id
        self.creator_name = creator_name
        self.players: Dict[str, Dict] = {}
        self.game_started = False
        self.max_players = 12
        self.created_at = datetime.now()
        
        # Game state for this room
        self.game_state = GameState()
        self.game_state.boundaries_x = [0, Config.PITCH_LENGTH]
        self.game_state.boundaries_y = [0, Config.PITCH_WIDTH]
        self.game_state.keeper_zone_x_0 = Config.KEEPER_ZONE_X
        self.game_state.keeper_zone_x_1 = Config.PITCH_LENGTH - Config.KEEPER_ZONE_X
        self.game_state.midline_x = Config.PITCH_LENGTH / 2
        self.game_state.seeker_floor_seconds = Config.SEEKER_FLOOR_REAL_SECONDS / Config.GAME_TIME_TO_REAL_TIME_RATIO
        self.game_state.delay_of_game_time_limit = Config.DELAY_OF_GAME_TIME_LIMIT
        self.game_state.delay_of_game_velocity_x_threshold = Config.DELAY_OF_GAME_VELOCITY_X_THRESHOLD
        self.game_state.max_delay_of_game_warnings = Config.MAX_DELAY_OF_GAME_WARNINGS
        self.game_logic = GameLogicSystem(self.game_state)
        self.client_connections: Dict[str, WebSocket] = {}
        self.player_to_client: Dict[str, str] = {}
        # Lobby websocket connections (for waiting-room updates)
        self.lobby_connections: Dict[str, WebSocket] = {}
        # Bandwidth counters (bytes/messages sent by server for this room)
        self.bytes_sent_total: int = 0
        self.messages_sent_total: int = 0
        # recent sends for rolling-rate calculation: deque of (timestamp, bytes)
        self.recent_sends: deque[tuple] = deque()
        # how long to keep history (seconds)
        self.max_history_seconds: int = 120
        # internal counter for broadcast logging
        self._broadcast_count = 0

        self._initialize_field()
    
    def _initialize_field(self):
        """Initialize game field with hoops"""
        # Add hoops for team 0
        self.game_state.hoops["hoop_0_left"] = Hoop(
            id="hoop_0_left", team=0, position=Vector2(Config.HOOP_X, Config.PITCH_WIDTH / 2 + Config.HOOP_DISTANCES), thickness=Config.HOOP_THICKNESS, radius=Config.HOOP_RADIUS
        )
        self.game_state.hoops["hoop_0_center"] = Hoop(
            id="hoop_0_center", team=0, position=Vector2(Config.HOOP_X, Config.PITCH_WIDTH / 2), thickness=Config.HOOP_THICKNESS, radius=Config.HOOP_RADIUS
        )
        self.game_state.hoops["hoop_0_right"] = Hoop(
            id="hoop_0_right", team=0, position=Vector2(Config.HOOP_X, Config.PITCH_WIDTH / 2 - Config.HOOP_DISTANCES), thickness=Config.HOOP_THICKNESS, radius=Config.HOOP_RADIUS
        )
        
        # Add hoops for team 1
        self.game_state.hoops["hoop_1_left"] = Hoop(
            id="hoop_1_left", team=1, position=Vector2(Config.PITCH_LENGTH - Config.HOOP_X, Config.PITCH_WIDTH / 2 + Config.HOOP_DISTANCES), thickness=Config.HOOP_THICKNESS, radius=Config.HOOP_RADIUS
        )
        self.game_state.hoops["hoop_1_center"] = Hoop(
            id="hoop_1_center", team=1, position=Vector2(Config.PITCH_LENGTH - Config.HOOP_X, Config.PITCH_WIDTH / 2), thickness=Config.HOOP_THICKNESS, radius=Config.HOOP_RADIUS
        )
        self.game_state.hoops["hoop_1_right"] = Hoop(
            id="hoop_1_right", team=1, position=Vector2(Config.PITCH_LENGTH - Config.HOOP_X, Config.PITCH_WIDTH / 2 - Config.HOOP_DISTANCES), thickness=Config.HOOP_THICKNESS, radius=Config.HOOP_RADIUS
        )
        
        # Add quaffle
        volleyball = VolleyBall(
            id="volleyball",
            position=Vector2(Config.PITCH_LENGTH / 2, Config.PITCH_WIDTH / 2),
            radius=Config.VOLLEYBALL_RADIUS,
            deacceleration_rate=Config.BALL_DEACCELERATION_RATE,
            reflect_velocity_loss=Config.BALL_REFLECT_VELOCITY_LOSS
        )
        self.game_state.add_ball(volleyball)

        # Add 3 bludgers
        for i, position in enumerate([
            (Config.PITCH_LENGTH / 2, Config.VOLLEYBALL_RUNNER_STARTING_Y),
            (Config.KEEPER_ZONE_X, Config.PITCH_WIDTH / 2), 
            (Config.PITCH_LENGTH - Config.KEEPER_ZONE_X, Config.PITCH_WIDTH / 2)
            ]):
            dodgeball = DodgeBall(
                id=f"dodgeball_{i}",
                position=Vector2(position[0], position[1]),
                radius=Config.DODGEBALL_RADIUS,
                deacceleration_rate=Config.BALL_DEACCELERATION_RATE,
                reflect_velocity_loss=Config.BALL_REFLECT_VELOCITY_LOSS
            )
            self.game_state.add_ball(dodgeball)

# ==================== LOBBY STATE ====================

class LobbyManager:
    def __init__(self):
        self.rooms: Dict[str, GameRoom] = {}
        self.waiting_connections: Dict[str, Dict] = {}  # temp storage for connections
    
    def create_room(self, creator_id: str, creator_name: str) -> tuple[str, str]:
        """Create a new room, returns (room_id, passkey)"""
        room_id = str(uuid.uuid4())[:8]
        # We no longer require a passkey; keep the field for compatibility but leave empty
        passkey = ""

        room = GameRoom(room_id, passkey, creator_id, creator_name)
        self.rooms[room_id] = room
        return room_id, passkey
    
    def get_room(self, room_id: str) -> Optional[GameRoom]:
        """Get room by ID"""
        return self.rooms.get(room_id)
    
    def join_room(self, room_id: str, passkey: Optional[str] = None) -> bool:
        """Join room by id. Passkey is ignored for now (kept for compatibility)."""
        room = self.rooms.get(room_id)
        return room is not None
    
    def list_available_rooms(self) -> list:
        """List all non-started rooms"""
        available = []
        for room_id, room in self.rooms.items():
            if not room.game_started and len(room.players) < room.max_players:
                available.append({
                    "room_id": room_id,
                    "creator_name": room.creator_name,
                    "players_count": len(room.players),
                    "max_players": room.max_players
                })
        return available

lobby_manager = LobbyManager()

# ==================== HTTP ROUTES ====================

@app.get("/")
async def root():
    """Serve lobby page"""
    return FileResponse("client/lobby.html")

@app.get("/game")
async def game():
    """Serve game page"""
    return FileResponse("client/game.html")

@app.get("/api/rooms")
async def list_rooms():
    """List available rooms"""
    return {"rooms": lobby_manager.list_available_rooms()}


@app.get("/api/rooms/{room_id}/bandwidth")
async def room_bandwidth(room_id: str):
    """Return bandwidth usage statistics for a room.

    Returns total bytes and messages sent by the server for this room.
    """
    room = lobby_manager.get_room(room_id)
    if not room:
        return {"error": "room_not_found"}
    return {
        "room_id": room_id,
        "bytes_sent_total": getattr(room, 'bytes_sent_total', 0),
        "messages_sent_total": getattr(room, 'messages_sent_total', 0),
        "broadcast_count": getattr(room, '_broadcast_count', 0),
        "connected_clients": len(getattr(room, 'client_connections', {})),
        "recent_history_seconds": getattr(room, 'max_history_seconds', 0)
    }


@app.get("/api/rooms/{room_id}/bandwidth_rate")
async def room_bandwidth_rate(room_id: str, window: Optional[float] = 5.0):
    """Return bandwidth rate for last `window` seconds (bytes/sec and messages/sec).

    Query param `window` is seconds (float). Defaults to 5.0 seconds.
    """
    room = lobby_manager.get_room(room_id)
    if not room:
        return {"error": "room_not_found"}

    now = time.time()
    window_seconds = float(window) if window is not None else 5.0
    threshold = now - window_seconds

    # purge old entries beyond max_history_seconds to keep deque bounded
    try:
        max_age = getattr(room, 'max_history_seconds', 120)
        cutoff = now - max_age
        while room.recent_sends and room.recent_sends[0][0] < cutoff:
            room.recent_sends.popleft()
    except Exception:
        pass

    bytes_in_window = 0
    msgs_in_window = 0
    for ts, b in room.recent_sends:
        if ts >= threshold:
            bytes_in_window += b
            msgs_in_window += 1

    bytes_per_sec = bytes_in_window / window_seconds if window_seconds > 0 else 0.0
    msgs_per_sec = msgs_in_window / window_seconds if window_seconds > 0 else 0.0

    return {
        "room_id": room_id,
        "window_seconds": window_seconds,
        "bytes_last_window": bytes_in_window,
        "bytes_per_second": bytes_per_sec,
        "messages_last_window": msgs_in_window,
        "messages_per_second": msgs_per_sec,
        "connected_clients": len(getattr(room, 'client_connections', {}))
    }

# ==================== WEBSOCKET HANDLERS ====================

@app.websocket("/ws/lobby")
async def websocket_lobby(websocket: WebSocket):
    """Handle lobby connections"""
    await websocket.accept()
    client_id = str(uuid.uuid4())

    
    try:
        while True:
            try:
                data = await websocket.receive_text()
            except WebSocketDisconnect:
                # Client disconnected normally
                break
            except Exception as e:
                logger.exception(f"Error receiving text from websocket for client={client_id}: {e}")
                break

            try:
                message = json.loads(data)
            except Exception as e:  
                logger.exception(f"Failed to parse JSON from client={client_id}: {e} data={data}")
                # skip invalid message and continue
                continue

            message_type = message.get("type")
            
            if message_type == "create_room":
                player_name = message.get("player_name", "Player")
                room_id, passkey = lobby_manager.create_room(client_id, player_name)
                # Add the creator as a player in the room so they appear in the waiting list
                room = lobby_manager.get_room(room_id)
                creator_player_id = str(uuid.uuid4())
                room.players[creator_player_id] = {
                    "id": creator_player_id,
                    "name": player_name,
                    "team": 0,
                    "role": "chaser"
                }

                # Also create a Player entity in the room's game state so they'll render in-game
                try:
                    # place creator near left side in metres
                    y_offset = len(room.game_state.get_players_by_team(0)) * 1.5
                    player_entity = Player(
                        id=creator_player_id,
                        team=0,  # numerical team for game logic (0 = left/A)
                        role=PlayerRole("chaser"),
                        radius=Config.PLAYER_RADIUS,
                        position=Vector2(25, Config.PITCH_WIDTH / 2 + y_offset),
                        max_speed=Config.PLAYER_MAX_SPEED,
                        min_speed=Config.PLAYER_MIN_SPEED,
                        acceleration=Config.PLAYER_ACCELERATION,
                        deacceleration_rate=Config.PLAYER_DEACCELERATION_RATE,
                        min_dir=Config.PLAYER_MIN_DIR,
                        throw_velocity=Config.PLAYER_THROW_VELOCITY
                    )
                    room.game_state.add_player(player_entity)
                except Exception:
                    pass

                # Track this websocket as a lobby connection for the room and map player->client
                room.lobby_connections[client_id] = websocket
                room.player_to_client[creator_player_id] = client_id

                await websocket.send_json({
                    "type": "room_created",
                    "room_id": room_id,
                    "passkey": passkey,
                    "player_id": creator_player_id,
                    "players": list(room.players.values())
                })
            
            elif message_type == "list_rooms":
                rooms = lobby_manager.list_available_rooms()
                await websocket.send_json({
                    "type": "rooms_list",
                    "rooms": rooms
                })
            
            elif message_type == "join_room":
                room_id = message.get("room_id")
                passkey = message.get("passkey")
                player_name = message.get("player_name", "Player")
                team = message.get("team", 'A')
                role = message.get("role", "chaser")
                
                if lobby_manager.join_room(room_id, passkey):
                    room = lobby_manager.get_room(room_id)
                    
                    # Add player to room
                    player_id = str(uuid.uuid4())
                    room.players[player_id] = {
                        "id": player_id,
                        "name": player_name,
                        "team": team,
                        "role": role
                    }
                    # Track this websocket as a lobby connection for the room and map player->client
                    room.lobby_connections[client_id] = websocket
                    room.player_to_client[player_id] = client_id
                    # Also create a Player entity in the room's game state so they'll render in-game
                    try:
                        player_entity = Player(
                            id=player_id,
                            team=(0 if team in (0, '0', 'A', 'a') else 1),
                            role=PlayerRole(role),
                            radius=Config.PLAYER_RADIUS,
                            position=Vector2(
                                5 if team in (0, '0', 'A', 'a') else (Config.PITCH_LENGTH - 5),
                                Config.PITCH_WIDTH / 2 + (len(room.game_state.get_players_by_team(0 if team in (0, '0', 'A', 'a') else 1)) * 1.5),
                            ),
                            max_speed=Config.PLAYER_MAX_SPEED,
                            min_speed=Config.PLAYER_MIN_SPEED,
                            acceleration=Config.PLAYER_ACCELERATION,
                            deacceleration_rate=Config.PLAYER_DEACCELERATION_RATE,
                            min_dir=Config.PLAYER_MIN_DIR,
                            throw_velocity=Config.PLAYER_THROW_VELOCITY
                        )
                        room.game_state.add_player(player_entity)
                    except Exception:
                        pass
                    
                    await websocket.send_json({
                        "type": "join_successful",
                        "room_id": room_id,
                        "player_id": player_id,
                        "players": list(room.players.values())
                    })
                    # Notify other lobby connections in the room about the new player
                    await broadcast_lobby(room, {
                        "type": "players_updated",
                        "room_id": room_id,
                        "players": list(room.players.values())
                    })
                else:
                    await websocket.send_json({
                        "type": "join_failed",
                        "error": "Invalid room ID or passkey"
                    })

            elif message_type == "update_player":
                # Update a player's team/role inside a room
                room_id = message.get("room_id")
                player_id = message.get("player_id")
                team = message.get("team")
                role = message.get("role")

                room = lobby_manager.get_room(room_id)
                if not room:
                    await websocket.send_json({"type": "update_failed", "error": "Room not found"})
                else:
                    player = room.players.get(player_id)
                    if not player:
                        await websocket.send_json({"type": "update_failed", "error": "Player not found in room"})
                    else:
                        # Update fields in the room players dict
                        if team is not None:
                            player["team"] = team
                        if role is not None:
                            player["role"] = role

                        # Also update or create the player entity in the game state so rendering works
                        try:
                            p_ent = room.game_state.get_player(player_id)
                            if p_ent:
                                if team is not None:
                                    p_ent.team = int(team)
                                if role is not None:
                                    p_ent.role = PlayerRole(role)
                                room.game_state.update_player(p_ent)
                            else:
                                new_ent = Player(
                                    id=player_id,
                                    team=int(team) if team is not None else 0,
                                    role=PlayerRole(role) if role is not None else PlayerRole("chaser"),
                                    radius=Config.PLAYER_RADIUS,
                                    position=Vector2(
                                        200 if (team is None or int(team) == 0) else 1100,
                                        360 + (len(room.game_state.get_players_by_team(int(team) if team is not None else 0)) * 60)
                                    ),
                                    max_speed=Config.PLAYER_MAX_SPEED,
                                    min_speed=Config.PLAYER_MIN_SPEED,
                                    acceleration=Config.PLAYER_ACCELERATION,
                                    deacceleration_rate=Config.PLAYER_DEACCELERATION_RATE,
                                    min_dir=Config.PLAYER_MIN_DIR,
                                    throw_velocity=Config.PLAYER_THROW_VELOCITY
                                )
                                room.game_state.add_player(new_ent)
                        except Exception:
                            pass

                        # Broadcast updated players list to lobby connections
                        await broadcast_lobby(room, {
                            "type": "players_updated",
                            "room_id": room_id,
                            "players": list(room.players.values())
                        })

            elif message_type == "start_game":
                # Room creator requests to start the game
                room_id = message.get("room_id")
                room = lobby_manager.get_room(room_id)
                if not room:
                    await websocket.send_json({"type": "start_failed", "error": "Room not found"})
                elif client_id != room.creator_id:
                    await websocket.send_json({"type": "start_failed", "error": "Only the room creator can start the game"})
                else:
                    # Ensure the creator has a player entry; create one if missing
                    creator_player_id = None
                    for pid, pdata in room.players.items():
                        # try to match by creator name as a heuristic
                        if pdata.get("name") == room.creator_name:
                            creator_player_id = pid
                            break

                    if not creator_player_id:
                        creator_player_id = str(uuid.uuid4())
                        room.players[creator_player_id] = {
                            "id": creator_player_id,
                            "name": room.creator_name,
                            "team": 0,
                            "role": "chaser"
                        }

                    room.game_started = True
                    # reinitialize game logic system with all players and balls
                    room.game_logic = GameLogicSystem(room.game_state)

                    # Broadcast start to all lobby connections in the room so every client
                    # receives their assigned player_id (if any) and can open the game page.
                    try:
                        for cid, ws in list(room.lobby_connections.items()):
                            # find player_id(s) associated with this client id
                            pids = [pid for pid, mapped_cid in room.player_to_client.items() if mapped_cid == cid]
                            # choose first player id if present, else None
                            pid = pids[0] if pids else None
                            try:
                                await ws.send_json({
                                    "type": "start_successful",
                                    "room_id": room_id,
                                    "player_id": pid,
                                    "players": list(room.players.values())
                                })
                            except Exception:
                                # ignore send failures; cleanup will happen on disconnect
                                pass
                    except Exception:
                        # Fallback: at least reply to requester
                        await websocket.send_json({
                            "type": "start_successful",
                            "room_id": room_id,
                            "player_id": creator_player_id,
                            "players": list(room.players.values())
                        })
    
    except WebSocketDisconnect:
        # Clean up lobby connection mappings for this websocket/client
        try:
            for r in list(lobby_manager.rooms.values()):
                if hasattr(r, 'lobby_connections') and client_id in r.lobby_connections:
                    try:
                        del r.lobby_connections[client_id]
                    except KeyError:
                        pass

                # remove any player->client mappings that pointed to this client_id
                to_remove = [pid for pid, cid in getattr(r, 'player_to_client', {}).items() if cid == client_id]
                for pid in to_remove:
                    try:
                        del r.player_to_client[pid]
                    except KeyError:
                        pass
        except Exception:
            pass


async def broadcast_lobby(room: GameRoom, message: dict):
    """Send a message to all lobby websocket connections for a room."""
    disconnected = set()
    for cid, ws in getattr(room, 'lobby_connections', {}).items():
        try:
            await ws.send_json(message)
        except Exception:
            disconnected.add(cid)

    for cid in disconnected:
        try:
            del room.lobby_connections[cid]
        except KeyError:
            pass

@app.websocket("/ws/game/{room_id}/{player_id}")
async def websocket_game(websocket: WebSocket, room_id: str, player_id: str):
    """Handle game connections"""
    await websocket.accept()

    room = lobby_manager.get_room(room_id)
    if not room:
        await websocket.close(code=1000, reason="Room not found")
        return

    client_id = str(uuid.uuid4())
    room.client_connections[client_id] = websocket

    try:
        # Send initial game state
        await websocket.send_json({
            "type": "initial_state",
                "game_state": room.game_state.serialize(),
                # send ordered id lists so clients can map binary updates to entities
                "players_order": list(room.game_state.players.keys()),
                "balls_order": list(room.game_state.balls.keys()),
            "players": list(room.players.values()),
            # expose a small subset of server-side config so clients render to scale
            "config": {
                "pitch_length": Config.PITCH_LENGTH,
                "pitch_width": Config.PITCH_WIDTH,
                "keeper_zone_x": Config.KEEPER_ZONE_X,
                "hoop_radius": Config.HOOP_RADIUS * 2,  # convert to diameter-like value
                "hoop_thickness": Config.HOOP_THICKNESS,
                "player_radius": Config.PLAYER_RADIUS,
                "volleyball_radius": Config.VOLLEYBALL_RADIUS,
                "dodgeball_radius": Config.DODGEBALL_RADIUS,
            }
        })

        while True:
            try:
                raw = await websocket.receive()
            except WebSocketDisconnect:
                # Client disconnected normally
                break
            except Exception as e:
                logger.exception(f"Error receiving from websocket for room={room_id} player={player_id}: {e}")
                break
            # Text messages remain JSON commands
            if raw.get('type') == 'websocket.receive' and 'text' in raw and raw['text'] is not None:
                try:
                    message = json.loads(raw['text'])
                except Exception:
                    continue

                message_type = message.get("type")

                if message_type == "player_input":
                    direction_x = message.get("direction_x", 0)
                    direction_y = message.get("direction_y", 0)

                    # Apply input
                    player = room.game_state.get_player(player_id)
                    if player:
                        # log input for debugging
                        logger.debug(f"player_input room={room_id} player={player_id} dir=({direction_x},{direction_y})")
                        player.direction.x = float(direction_x)
                        player.direction.y = float(direction_y)

                elif message_type == "throw":
                    success = room.game_logic.process_throw_action(player_id)
                    if success:
                        # Broadcast updated state
                        await broadcast_to_room(room, {
                            "type": "state_update",
                            "game_state": room.game_state.serialize()
                        })

            # Binary frames: treat as player input packed as two float16 values (little-endian)
            elif raw.get('type') == 'websocket.receive' and 'bytes' in raw and raw['bytes'] is not None:
                try:
                    b = raw['bytes']
                    # expect at least 4 bytes: two float16 halves
                    if len(b) >= 4:
                        dx = struct.unpack('<e', b[0:2])[0]
                        dy = struct.unpack('<e', b[2:4])[0]
                        player = room.game_state.get_player(player_id)
                        if player:
                            player.direction.x = float(dx)
                            player.direction.y = float(dy)
                except Exception:
                    logger.exception(f"Failed to parse binary player input for room={room_id} player={player_id}")

    except WebSocketDisconnect:
        if client_id in room.client_connections:
            del room.client_connections[client_id]

async def broadcast_to_room(room: GameRoom, message: dict):
    """Broadcast message to all clients in a room"""
    # If there are no connected clients in this room, skip work early.
    # This avoids building binary payloads every tick for empty rooms.
    try:
        if not getattr(room, 'client_connections', None):
            return
    except Exception:
        # If anything odd happens, fall back to normal behavior.
        pass
    # increment per-room broadcast counter and occasionally log summary for debugging
    try:
        room._broadcast_count += 1
    except Exception:
        # if room doesn't have the attribute for any reason, silently continue
        pass

    # log a summary every N broadcasts to avoid spamming the logs
    LOG_EVERY = 40
    try:
        if message.get('type') == 'state_update' and (getattr(room, '_broadcast_count', 0) % LOG_EVERY == 0):
            gs = message.get('game_state', {}) or {}
            players = gs.get('players', {})
            sample_info = ''
            if players:
                # take first player sample
                try:
                    first = next(iter(players.values()))
                    pos = first.get('position') or first.get('pos') or {}
                    sample_info = f" sample_player_pos=({pos.get('x')},{pos.get('y')})"
                except Exception:
                    sample_info = ''
            # logger.info(f"broadcast state_update room={room.room_id} clients={len(room.client_connections)} count={getattr(room, '_broadcast_count', 0)}{sample_info}")
    except Exception:
        logger.exception('Error while logging broadcast summary')

    disconnected = set()
    # For frequent `state_update` messages we send a compact binary payload
    def build_binary_state(r: GameRoom) -> bytes:
        """Build a compact binary representation of dynamic entities.

        Format (little-endian):
        - uint8: version (1)
        - uint8: player_count
        - uint8: ball_count
        - float16: game_time
        - for each player: float16 x, float16 y, float16 vx, float16 vy, uint8 flags
            flags bit0 = is_knocked_out, bit1 = has_ball
        - for each ball: float16 x, float16 y, float16 vx, float16 vy, uint8 holder_flag
        

        Clients must use the `players_order` and `balls_order` arrays sent in the
        initial_state message to map these items to entity ids.

        Note: this uses the struct 'e' format (half-precision). Requires Python
        3.6+ where 'e' is supported by the `struct` module.
        """
        gs = r.game_state
        players = list(gs.players.values())
        balls = list(gs.balls.values())

        buf = bytearray()
        # header
        buf += struct.pack('<B', 1)
        buf += struct.pack('<B', len(players))
        buf += struct.pack('<B', len(balls))
        buf += struct.pack('<e', float(gs.game_time))
        # include current score for both teams as two uint8 values
        try:
            score_list = getattr(gs, 'score', None)
            if score_list and len(score_list) >= 2:
                s0 = int(score_list[0])
                s1 = int(score_list[1])
            else:
                s0 = 0
                s1 = 0
        except Exception:
            s0 = 0
            s1 = 0
        buf += struct.pack('<BB', s0, s1)

        # players: x,y,vx,vy + flags
        for p in players: # TODO: send only updates when changed, also in game-client
            px = float(getattr(p.position, 'x', 0.0))
            py = float(getattr(p.position, 'y', 0.0))
            vx = float(getattr(p.velocity, 'x', 0.0))
            vy = float(getattr(p.velocity, 'y', 0.0))
            buf += struct.pack('<eeee', px, py, vx, vy)
            flags = (1 if getattr(p, 'is_knocked_out', False) else 0) | ((1 if getattr(p, 'has_ball', False) else 0) << 1)
            buf += struct.pack('<B', flags)

        # balls: x,y,vx,vy + holder_flag
        for b in balls:
            bx = float(getattr(b.position, 'x', 0.0))
            by = float(getattr(b.position, 'y', 0.0))
            bvx = float(getattr(b.velocity, 'x', 0.0))
            bvy = float(getattr(b.velocity, 'y', 0.0))
            buf += struct.pack('<eeee', bx, by, bvx, bvy)
            buf += struct.pack('<B', 1 if getattr(b, 'holder_id', None) else 0)
            buf += struct.pack('<B', 1 if getattr(b, 'is_dead', None) else 0)

        return bytes(buf)

    # Precompute payload once and send to all clients; track bytes per successful send
    if message.get('type') == 'state_update':
        payload_bytes = build_binary_state(room)
        for client_id, websocket in list(room.client_connections.items()):
            try:
                await websocket.send_bytes(payload_bytes)
                # update counters per successful send
                try:
                                room.bytes_sent_total += len(payload_bytes)
                                room.messages_sent_total += 1
                                # record recent send for rolling-window stats
                                try:
                                    room.recent_sends.append((time.time(), len(payload_bytes)))
                                except Exception:
                                    pass
                except Exception:
                    pass
            except Exception:
                disconnected.add(client_id)
    else:
        # other messages are infrequent; send JSON text and count bytes
        try:
            # prefer compact serialization for non-state messages
            if _orjson is not None:
                text_bytes = _orjson.dumps(message)
            else:
                text_bytes = json.dumps(message, separators=(',', ':'), ensure_ascii=False).encode('utf-8')
        except Exception:
            # fallback to simple encoding
            text_bytes = json.dumps(message).encode('utf-8')

        for client_id, websocket in list(room.client_connections.items()):
            try:
                # use send_json for non-state messages to preserve JSON semantics
                await websocket.send_json(message)
                # increment counters using compact text bytes length
                try:
                                room.bytes_sent_total += len(text_bytes)
                                room.messages_sent_total += 1
                                try:
                                    room.recent_sends.append((time.time(), len(text_bytes)))
                                except Exception:
                                    pass
                except Exception:
                    pass
            except Exception:
                disconnected.add(client_id)

    for client_id in disconnected:
        try:
            del room.client_connections[client_id]
        except KeyError:
            pass

@app.on_event("startup")
async def startup_event():
    """Start game loops for active rooms"""
    asyncio.create_task(game_loop_manager())

@app.get("/health-check")
async def health_check():
    return Response(content='{"status": "ok"}', status_code=200)

async def game_loop_manager():
    """Manage game loops for all active rooms"""
    clock_tick = 1.0 / Config.FPS
    clock_tick_game = clock_tick * Config.GAME_TIME_TO_REAL_TIME_RATIO
    while True:
        start_time = time.monotonic()
        if len(list(lobby_manager.rooms.items())) == 0:
            # no rooms, sleep longer
            await asyncio.sleep(1.0)
            continue
        for room_id, room in list(lobby_manager.rooms.items()):
            if room.game_started:
                # Update game logic
                room.game_logic.update(clock_tick_game)

                # Broadcast state
                await broadcast_to_room(room, {
                    "type": "state_update",
                    "game_state": room.game_state.serialize()
                })
        elapsed_time = time.monotonic() - start_time
        to_sleep = max(0.0, clock_tick - elapsed_time)  
        # print(clock_tick, elapsed_time, to_sleep)     
        await asyncio.sleep(to_sleep) # all rooms sleep for remaining tick duration -> controlled FPS
        


if __name__ == "__main__":
    import uvicorn
    port = int(os.getenv("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)