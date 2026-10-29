export const State = {
  gameSocket: null,
  gameState: null,
  ballVelocities: {},
  canvas: null,
  ctx: null,
  // The entity we currently steer. Starts as the connection's own player and
  // follows player switches, so rendering, camera and input all track it.
  localPlayerId: null,
  // The player id the game socket is bound to; never changes.
  connectionPlayerId: null,
  roomId: null,
  playersOrder: null,
  ballsOrder: null,
  network: { tickSeconds: 0, lastUpdateAtMs: 0 },
  // Game paused for everybody (someone has the settings menu open).
  paused: false,
  pausedAtMs: 0,
  isTutorial: false,
  // Display names of team 0 and team 1, set in the room lobby.
  teamNames: ['Team A', 'Team B'],
  // Entity id -> name of the human steering it; drawn above the player when showNames is on.
  humanNames: {},
  showNames: true,
  mousePos: null,
  // Charged throw of the steered player: bars filled so far (one per server tick) out of fullTicks.
  // pressed: the throw action (space, mouse button, right-side touch) is held down.
  throwCharge: { ticks: 0, fullTicks: 10, pressed: false, touchId: null },
  isTouchDevice: false,
  fullscreen: { isFullscreen: false, attempted: false, button: null },
  playerSwitch: { buttons: {}, forbiddenTimers: {} },
  viewport: { enabled: false, centerX: 0, centerY: 0, worldWidth: 30, worldHeight: 16.5, offsetX: 0, offsetY: 0 },
  joystick: { active: false, centerX: 0, centerY: 0, currentX: 0, currentY: 0, maxRadius: 40, baseRadius: 32, knobRadius: 12, deadZone: 4, touchId: null, fadeTimer: null, opacity: 0.7 },
  debug: { enabled: false, stateUpdateCounter: 0, lastPositions: {}, LOG_EVERY_N: 10, POS_EPSILON: 0.05 },
};

// Initialize debug from query string
const params = new URLSearchParams(window.location.search);
State.debug.enabled = params.get('debug') === '1' || params.get('debug') === 'true';