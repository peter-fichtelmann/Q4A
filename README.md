
# Q4A - Quadball for All

Welcome to the Q4A (Quadball for All) repository — a lightweight, server-authoritative online implementation of quadball (formerly Quidditch). Play with friends or against computer players, right in your browser on PC or mobile.

Play the game on [https://q4a.onrender.com/](https://q4a.onrender.com/)

## Local Installation Guide on your own PC

This guide will help you set up and run Q4A on your computer, even if you're new to programming.

### Prerequisites

You'll need to install a few tools first:

#### 1. Install Git (if you don't have it)
- **Windows**: Download from [git-scm.com](https://git-scm.com/download/win) and run the installer
- **macOS**: Download from [git-scm.com](https://git-scm.com/download/mac) or install via Homebrew: `brew install git`
- **Linux**: Use your package manager, e.g., `sudo apt install git` (Ubuntu/Debian) or `sudo yum install git` (CentOS/RHEL)

#### 2. Install Python 3.12 (if you don't have it)
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
From the repository root (the `Q4A` folder):
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
3. Create or join a room, pick your team and role in the room lobby, and start the game!
4. New to quadball? Click **Play the Tutorial** in the main lobby — Donatella will guide you through the rules step by step.

### Stopping the Server
Press `Ctrl+C` in the terminal where the server is running to stop it.

## Project Structure

**Game Mechanics Diagram**
![Light version](images/explanation_game_mechanics_light_mode.png#gh-light-mode-only)
![Dark version](images/explanation_game_mechanics_dark_mode.png#gh-dark-mode-only)

- **Server-authoritative:** the server owns the one true version of the game. Clients only send inputs and display what the server tells them.
- **GameState:** holds every entity on the pitch (players, volleyball, dodgeballs, hoops, flag runner) along with attributes such as position, velocity and whether a player is knocked out.
- **GameLogic:** the server runs the rules and physics on the GameState in each frame (`Config.FPS`, 20 per second by default). It moves players and balls, resolves collisions, beats and scoring, and then writes the updated GameState back.
- **Player actions (client → server):** each client sends its player's inputs, such as moving, throwing and tackling, over a WebSocket.
- **State updates (server → clients):** after each frame, the server broadcasts the new positions, velocities and knockouts to every client in the room.
- **Render:** each client draws the GameState it receives on a canvas. Every player sees the same game, no matter how many clients are connected.

- `main.py` — FastAPI server: HTTP routes, lobby/game WebSockets, room management and the fixed-tick game loop
- `config.py` — runtime configuration constants (physics, timings, team sizes, motion model, logging)
- `player_switch.py` — lets a human hand their player to a CPU teammate and take over another one
- `room_jsonl_logger.py` — per-room JSONL logging of game states (written to `game_data/logs/`)
- `requirements.txt` / `render.yaml` — Python dependencies and Render deployment config
- `core/` — domain models, state and game rules/physics
	- `entities.py` — `Player`, `VolleyBall`, `DodgeBall`, `FlagRunner`, `Hoop`, `Vector2`, ...
	- `game_state.py` — `GameState` container for the game entities and helper functions
	- `game_logic/` — game rules, split by topic and orchestrated by `game_logic.py` each tick
		- `basic_logic.py` — movement, velocity and position integration
		- `boundary_logic.py` — pitch boundaries and hoop blockage
		- `volleyball_logic.py` — possession, passing, scoring, inbounding
		- `dodgeball_logic.py` — beats, keeper immunity, third-dodgeball claiming
		- `flag_runner_logic.py` — flag runner movement, flag catches and overtime
		- `physical_contact_logic.py` — player collisions and tackles
		- `penalty_logic.py` — delay of game, turnovers, third-dodgeball interference
		- `process_action_logic.py` — player action inputs (throw, tackle, ...)
		- `utility_logic.py` — shared geometry helpers
- `computer_player/` — AI for CPU-controlled players
	- `computer_player.py` — random and rule-based computer players
	- `diamond_attack.py`, `hoop_defence.py`, `seeker_director.py` — team tactics for attack, defence and seekers
	- `computer_player_utility/` — kinematics, interception calculation, moving around hoop blockage
- `tutorial/` — server side of the interactive tutorial (tutorial rooms, director, scripted CPU players)
- `client/` — browser client served at `/client`
	- `lobby.html` / `lobby_client.js` — main lobby: create, join or browse rooms
	- `room.html` / `room_client.js` — room lobby: assign teams, roles and spectators before starting
	- `game.html` — in-game canvas UI (loads `js_game-client/main.js` as an ES module)
	- `styles.css`, `client_palette.js` — shared styles and colors
	- `js_game-client/` — ES module game client
		- `main.js` — entrypoint wiring inputs, sockets, loop, fullscreen
		- `network.js` — WebSocket connect, binary state parsing, input/throw send
		- `input.js` — keyboard/mouse/touch/joystick handling
		- `rendering.js` — pitch, players, balls and HUD rendering
		- `audio.js` — pitch atmosphere and event sounds
		- `claim.js` — third-dodgeball claim button
		- `player_switch.js` — switching the controlled player
		- `match_popups.js` — match event popups (goals, flag catch, overtime, ...)
		- `config.js`, `state.js`, `utils.js`, `viewport.js`, `fullscreen.js` — constants, runtime state, helpers, canvas sizing, fullscreen
	- `tutorial/` — client side of the tutorial (Donatella guide, speech bubbles, tutorial steps)
- `assets/` — sound effects
- `images/` — graphics for this README

**Implemented Features**
- Server-authoritative game loop with compact binary state updates over WebSockets (FastAPI).
- Quadball rules and physics:
	- Player movement with acceleration/deceleration and position integration
	- Volleyball handling: holding, passing, throwing, interception, scoring and inbounding
	- Dodgeballs: beats, immune keeper with shield animation, third-dodgeball claiming
	- Seekers and a flag runner, released after the seeker floor; flag catches and overtime
	- Tackles and player collisions
	- Penalties: delay of game, turnovers, third-dodgeball interference
	- Field boundary enforcement and hoop blockage to prevent goaltending
- Computer players with tactics for attack (diamond), hoop defence and seeking, so games can be filled with CPUs.
- Switching your controlled player to another one in your own team.
- Interactive tutorial with Donatella as a guide, covering movement, passing, scoring, beats, claiming and more.
- Browser client:
	- main lobby to create, join or browse rooms by ID, and a room lobby to set up teams and roles
	- 2D canvas rendering of the game with HUD, match popups and pitch sounds
	- mouse/keyboard controls on PC and joystick/touch controls on mobile devices
	- fullscreen and viewport for better visibility

**Upcoming Features / Roadmap**
- Lobby music, player strengths/weaknesses adjustment
- Game UX improvements: player names, replays
- Saving and loading of games

**Development Notes**
- For development work, follow the installation guide above.
- Most tuning knobs (physics, timings, team sizes, logging, motion model) live in `config.py`.
- Game states are logged as JSONL to `game_data/logs/` when `Config.JSONL_LOGGING_ENABLED` is set (the folder is git-ignored).
- The server listens on port 8000 by default; set the `PORT` environment variable to change it.

**How to Contribute**
- File an issue for bugs or feature requests.
- Fork and open a pull request for code changes; keep changes small and focused.
- Contact the developer team with your ideas.

Enjoy hacking on Q4A — ping me what you'd like next.
