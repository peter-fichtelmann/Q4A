import asyncio
import uuid
import json
import websockets
from typing import Dict, Set
from core.game_state import GameState
from core.entities import Player, Ball, Vector2, PlayerRole, BallType, Hoop
from quadball.core.game_logic import GameLogicSystem
from network.protocol import (
    NetworkMessage, MessageType, create_full_state_update_message, create_goal_scored_message
)

class QuadballGameServer:
    """Authoritative game server for multiplayer quadball."""
    
    def __init__(self):
        self.game_state = GameState()
        self.game_logic = GameLogicSystem(self.game_state)
        self.clients: Dict[str, websockets.WebSocketServerProtocol] = {}
        self.player_to_client: Dict[str, str] = {}  # player_id -> client_id
        self.running = False
        
        # Initialize game field
        self._initialize_field()
    
    def _initialize_field(self):
        """Set up initial field with hoops."""
        # Add hoops for team 0 (goal at x=100)
        self.game_state.hoops["hoop_0_left"] = Hoop(
            id="hoop_0_left", team=0, position=Vector2(100, 200), height=91
        )
        self.game_state.hoops["hoop_0_center"] = Hoop(
            id="hoop_0_center", team=0, position=Vector2(100, 360), height=137
        )
        self.game_state.hoops["hoop_0_right"] = Hoop(
            id="hoop_0_right", team=0, position=Vector2(100, 520), height=183
        )
        
        # Add hoops for team 1 (goal at x=1180)
        self.game_state.hoops["hoop_1_left"] = Hoop(
            id="hoop_1_left", team=1, position=Vector2(1180, 200), height=91
        )
        self.game_state.hoops["hoop_1_center"] = Hoop(
            id="hoop_1_center", team=1, position=Vector2(1180, 360), height=137
        )
        self.game_state.hoops["hoop_1_right"] = Hoop(
            id="hoop_1_right", team=1, position=Vector2(1180, 520), height=183
        )
        
        # Add quaffle (starts in center)
        quaffle = Ball(
            id="quaffle",
            ball_type=BallType.QUAFFLE,
            position=Vector2(640, 360)
        )
        self.game_state.add_ball(quaffle)
        
        # Add 3 bludgers
        for i in range(3):
            bludger = Ball(
                id=f"bludger_{i}",
                ball_type=BallType.BLUDGER,
                position=Vector2(640 + i*50, 360 + i*30)
            )
            self.game_state.add_ball(bludger)
    
    async def handle_client_wrapper(self, websocket):
        client_id = str(uuid.uuid4())
        await self.handle_client(websocket, client_id)

    async def handle_client(self, websocket, client_id):
        """Handle a connected client."""
        self.clients[client_id] = websocket
        
        try:
            async for message_json in websocket:
                try:
                    message = NetworkMessage.from_json(message_json)
                    await self.process_message(client_id, message)
                except json.JSONDecodeError:
                    print(f"[SERVER] Invalid JSON from {client_id}")
        
        except websockets.exceptions.ConnectionClosed:
            print(f"[SERVER] Client {client_id} disconnected")
        
        finally:
            # Remove client and associated player
            if client_id in self.clients:
                del self.clients[client_id]
            
            # Remove player from game state
            for player_id, pid in list(self.player_to_client.items()):
                if pid == client_id:
                    self.game_state.remove_player(player_id)
                    del self.player_to_client[player_id]
    
    async def process_message(self, client_id: str, message: NetworkMessage):
        """Process incoming message from client."""
        
        if message.type == MessageType.PLAYER_JOIN:
            await self._handle_player_join(client_id, message)
        
        elif message.type == MessageType.PLAYER_INPUT:
            await self._handle_player_input(client_id, message)
        
        elif message.type == MessageType.THROW:
            await self._handle_throw_action(client_id, message)
    
    async def _handle_player_join(self, client_id: str, message: NetworkMessage):
        """Handle player joining the game."""
        data = message.data
        player_id = data["player_id"]
        player_name = data["player_name"]
        team = data["team"]
        role = data["role"]
        
        # Create player entity
        player = Player(
            id=player_id,
            team=team,
            role=PlayerRole[role.upper()],
            position=Vector2(
                200 if team == 0 else 1100,
                360 + (len(self.game_state.get_players_by_team(team)) * 60)
            )
        )
        
        self.game_state.add_player(player)
        self.player_to_client[player_id] = client_id
        
        print(f"[SERVER] {player_name} ({player_id}) joined Team {team} as {role}")
        
        # Send full state to the client
        state_msg = create_full_state_update_message(
            self.game_state.serialize()
        )
        await self.clients[client_id].send(state_msg.to_json())
    
    async def _handle_player_input(self, client_id: str, message: NetworkMessage):
        """
        Handle player input from client.
        Server VALIDATES the input before applying it.
        """
        data = message.data
        player_id = data["player_id"]
        direction_x, direction_y = data["direction"]
        
        # Validate input on server
        if not self.game_logic.validate_player_input(player_id, (direction_x, direction_y)):
            print(f"[SERVER] Invalid input from {player_id}")
            return
        
        # Apply validated input to local player state
        player = self.game_state.get_player(player_id)
        if not player:
            return
        
        # Update player direction
        player.direction.x = direction_x
        player.direction.y = direction_y

    
    async def _handle_throw_action(self, client_id: str, message: NetworkMessage):
        """Handle throw action from client."""
        player_id = message.data.get("player_id")
        
        # Validate and process on server
        success = self.game_logic.process_throw_action(player_id)
        
        if success:
            # Broadcast updated ball state
            quaffle = self.game_state.get_quaffle()
            if quaffle:
                state_msg = create_full_state_update_message(
                    self.game_state.serialize()
                )
                await self.broadcast(state_msg)
    
    async def game_loop(self):
        """Main server game loop - runs at 15 Hz."""
        self.running = True
        FPS = 25
        clock_tick = 1.0 / FPS
        
        while self.running:
            # Update game logic
            self.game_logic.update(clock_tick)
            
            # Broadcast full state periodically (every 0.1 seconds)
            state_msg = create_full_state_update_message(
                self.game_state.serialize()
            )
            await self.broadcast(state_msg)
            
            await asyncio.sleep(clock_tick)
    
    async def broadcast(self, message: NetworkMessage):
        """Send message to all connected clients."""
        if not self.clients:
            return
        
        message_json = message.to_json()
        
        # Send to all clients
        disconnected = set()
        for client_id, websocket in self.clients.items():
            try:
                await websocket.send(message_json)
            except websockets.exceptions.ConnectionClosed:
                disconnected.add(client_id)
        
        # Remove disconnected clients
        for client_id in disconnected:
            del self.clients[client_id]
    
    async def start(self, host="0.0.0.0", port=8001):
        """Start the WebSocket server."""
        print(f"[SERVER] Starting quadball server on {host}:{port}")
        
        async with websockets.serve(self.handle_client_wrapper, host, port):
            # Run game loop and server concurrently
            await asyncio.gather(
                self.game_loop()
            )

# Start server
if __name__ == "__main__":
    server = QuadballGameServer()
    asyncio.run(server.start())