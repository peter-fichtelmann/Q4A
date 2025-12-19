
# Q4A - Quadball for All

Welcome to the Q4A (Quadball for All) repository — a lightweight, server-authoritative online implementation of quadball (formerly Quidditch).

Play the game on [https://q4a.onrender.com/](https://q4a.onrender.com/)

## Local Installation Guide on youor own PC

This guide will help you set up and run Q4A on your computer, even if you're new to programming.

### Prerequisites

You'll need to install a few tools first:

#### 1. Install Git (if you don't have it)
- **Windows**: Download from [git-scm.com](https://git-scm.com/download/win) and run the installer
- **macOS**: Download from [git-scm.com](https://git-scm.com/download/mac) or install via Homebrew: `brew install git`
- **Linux**: Use your package manager, e.g., `sudo apt install git` (Ubuntu/Debian) or `sudo yum install git` (CentOS/RHEL)

#### 2. Install Python 3.12.2 (if you don't have it)
- Download from [python.org](https://www.python.org/downloads/)
- **Important**: During installation, make sure to check "Add Python to PATH"
- To verify installation, open a terminal/command prompt and run: `python --version`

### Setup Instructions

#### Step 1: Clone the Repository
Open a terminal/command prompt and run:
```bash
git clone https://github.com/peter-fichtelmann/Q4A.git
cd Q4A
```

#### Step 2: Create a Python Virtual Environment
This keeps the project dependencies separate from your system Python:

**Windows:**
```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS/Linux:**
```bash
python -m venv .venv
source .venv/bin/activate
```

You should see `(.venv)` at the beginning of your command prompt, indicating the virtual environment is active.

#### Step 3: Install Dependencies
```bash
cd quadball
```
```bash
pip install -r requirements.txt
```

#### Step 4: Start the Server
```bash
python main.py
```

You should see output indicating the server is running. The game will be available at `http://localhost:8000`

#### Step 5: Play the Game
1. Open your web browser
2. Go to `http://localhost:8000`
3. Create or join a room to start playing!

### Stopping the Server
Press `Ctrl+C` in the terminal where the server is running to stop it.

## Project Structure

**Game Mechanics Diagram**
![Light version](images/explanation_game_mechanics_light_mode.png#gh-light-mode-only)
![Dark version](images/explanation_game_mechanics_dark_mode.png#gh-dark-mode-only)
<!-- <img src="explanation_game_mechanics.png" alt="Game mechanics overview" width="860" /> -->

- `quadball/` — main application package and server entry points
	- `main.py` — FastAPI server and game loop manager
	- `config.py` — runtime configuration constants
	- `requirements.txt` — Python dependencies
	- `client/` — browser client assets served at `/client`
		- `styles.css` — shared styles for lobby and game
		- `lobby.html` — lobby page (loads `lobby_client.js`)
		- `lobby_client.js` — client for interaction with lobby page
		- `game.html` — in-game canvas UI entry (loads `js_game-client/main.js` as an ES module)
		- `js_game-client/` — ES module client
			- `main.js` — entrypoint wiring inputs, sockets, loop, fullscreen
			- `config.js` — pitch/canvas constants (server may override on initial state)
			- `state.js` — runtime mutable state (socket, gameState, viewport, joystick, debug)
			- `utils.js` — query params and screen-size helpers
			- `viewport.js` — canvas sizing and world-to-screen transforms
			- `fullscreen.js` — fullscreen toggle, button UI, state updates
			- `network.js` — WebSocket connect, binary parsing, state merge, input/throw send
			- `input.js` — keyboard/mouse/touch/joystick handling
			- `rendering.js` — pitch, players, balls, heads-up-display (HUD) rendering
	- `core/` — domain models, state and game rules/physics
		- `entities.py` — `Player`, `Ball`, `Vector2`, `Hoop`, objects used in the game_state
		- `game_state.py` — `GameState` container for the game entities and helper functions
		- `game_logic_system.py` — core game rules, collisions, scoring: updating game_state in each timestep
	- `images/` — graphics for explanation

**Implemented Features**
- Server-authoritative game loop implemented in `main.py`.
- Domain model for players, balls and hoops in `core/entities.py`.
- Basic physics and game rules in `systems/game_logic_system.py`:
	- Player movement, velocity update and position integration
	- Ball handling (holding/throwing), basic reflections, volleyball inbounding procedure
	- Beats, immune keeper
	- Collision checks (players, balls)
	- Goal detection and scoring hooks
	- Field boundary enforcement
	- Hoop blockage enforcement for chasers own hoops to prevent goaltending
- WebSocket-based lobby and game endpoints (FastAPI) serving client state updates.
- Browser client (in `client/`) that renders the pitch and receives state updates:
	- a lobby system to join a room via an ID
	- a 2D rendering of the game on a canvas
	- mouse/keyboard controls on a PC and joystick/touch controls on mobile devices
	- fullscreen and viewport for better visability

**Upcoming Features / Roadmap**
- Adding other rules and physics
    - Third dodgeball interference
    - Tackling
	- Delay of game
- Improve client-side interpolation / prediction for smoother rendering under lag.
- More advanced lobby with tutorial, lobby music, player strengths/weaknesses adjustment
- Game UX improvements: HUD, player names, replays, spectator mode.
- Saving and loading of games

**Development Notes**
- For development work, follow the installation guide above
- The server runs in debug mode by default when started with `python main.py`

**How to Contribute**
- File an issue for bugs or feature requests.
- Fork and open a pull request for code changes; keep changes small and focused.
- Contact the developper team with your ideas

Enjoy hacking on Q4A — ping me what you'd like next.


