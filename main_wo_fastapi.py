import asyncio
import argparse
import pygame
from older_version_relics.client import NetworkClient
from network.protocol import MessageType, NetworkMessage
from systems.input_system import InputSystem, MovementSystem
from core.game_state import GameState

class QuadballGameClient:
    """Client-side game for a single player."""
    
    def __init__(self, server_url: str, player_name: str, team: int, role: str):
        pygame.init()
        self.screen = pygame.display.set_mode((1280, 720), vsync=1)
        pygame.display.set_caption(f"Quadball - {player_name}")
        self.clock = pygame.time.Clock()
        self.running = True
        
        # Network
        self.network = NetworkClient(player_name)
        self.server_url = server_url
        self.team = team
        self.role = role
        
        # Game state
        self.game_state = GameState()
        
        # Systems
        self.input_system = InputSystem()
        self.movement_system = MovementSystem()
        
        # Local player reference
        self.local_player_id = self.network.player_id
    
    async def game_loop(self):
        """Main game loop"""
        FPS = 25
        while self.running:
            dt = self.clock.tick(FPS) / 1000.0

            # Handle pygame events
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self.running = False
            
            # Get local input
            input_state = self.input_system.process(pygame.event.get())
            
            # Send input to server
            await self.network.send_player_input(
                input_state["direction"][0],
                input_state["direction"][1],
                input_state["action"]
            )
            
            # Receive and apply network updates
            message = await self.network.get_message()
            if message:
                if message.type == MessageType.FULL_STATE_UPDATE:
                    # Update local game state from server
                    self.game_state = GameState.deserialize(message.data)
            print('Main game state players:', [(player.id, player.position.x, player.position.y) for player in self.game_state.players.values()])
            # Render
            self._render()
            
            # Cooperative yield to network loop
            await asyncio.sleep(0)
    
    async def network_loop(self):
        """Network receive loop."""
        # Connect to server
        connected = await self.network.connect(self.server_url)
        if not connected:
            self.running = False
            return
        
        # Send join message
        await self.network.send_player_join(self.team, self.role)
        
        # Receive messages continuously
        await self.network.receive_messages()
    
    def _render(self):
        """Render the game."""
        # Clear screen
        self.screen.fill((34, 139, 34))  # Green field
        
        # Draw all players
        for player in self.game_state.players.values():
            color = (255, 255, 255) if player.team == 0 else (0, 0, 0)
            pygame.draw.circle(
                self.screen, color,
                (int(player.position.x), int(player.position.y)),
                15
            )
            
            # Highlight local player
            if player.id == self.local_player_id:
                pygame.draw.circle(
                    self.screen, (255, 0, 0),
                    (int(player.position.x), int(player.position.y)),
                    20, 2
                )
        
        # Draw balls
        for ball in self.game_state.balls.values():
            if ball.ball_type.value == "quaffle":
                color = (255, 128, 0)  # Orange
                size = 8
            elif ball.ball_type.value == "bludger":
                color = (0, 0, 0)
                size = 6
            else:
                color = (255, 255, 0)  # Yellow snitch
                size = 5
            
            pygame.draw.circle(
                self.screen, color,
                (int(ball.position.x), int(ball.position.y)),
                size
            )
        
        # Draw hoops
        for hoop in self.game_state.hoops.values():
            color = (128, 128, 255) if hoop.team == 0 else (255, 128, 128)
            pygame.draw.circle(
                self.screen, color,
                (int(hoop.position.x), int(hoop.position.y)),
                int(hoop.radius), 2
            )
        
        # Draw score
        font = pygame.font.Font(None, 36)
        score_text = f"Team 0: {self.game_state.score[0]} | Team 1: {self.game_state.score[1]}"
        text_surface = font.render(score_text, True, (255, 255, 255))
        self.screen.blit(text_surface, (20, 20))
        
        pygame.display.flip()
    
    async def run(self):
        """Run the game client."""
        await asyncio.gather(
            self.game_loop(),
            self.network_loop()
        )

def parse_args():
    parser = argparse.ArgumentParser(description="Quadball Game Client")
    parser.add_argument("--name", required=True, help="Player name")
    parser.add_argument("--team", type=int, required=True, choices=[0,1], help="Team number (0 or 1)")
    parser.add_argument("--role", required=True, choices=["keeper", "chaser", "beater", "seeker"], help="Player role")
    parser.add_argument("--server", required=True, help="WebSocket server URL (e.g. ws://localhost:8001)")
    return parser.parse_args()

async def main():
    args = parse_args()
    client = QuadballGameClient(
        server_url=args.server,
        player_name=args.name,
        team=args.team,
        role=args.role
    )
    await client.run()

if __name__ == "__main__":
    asyncio.run(main())
