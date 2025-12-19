export const State = {
  gameSocket: null,
  gameState: null,
  canvas: null,
  ctx: null,
  localPlayerId: null,
  roomId: null,
  playersOrder: null,
  ballsOrder: null,
  mousePos: null,
  isTouchDevice: false,
  fullscreen: { isFullscreen: false, attempted: false, button: null },
  viewport: { enabled: false, centerX: 0, centerY: 0, worldWidth: 30, worldHeight: 16.5, offsetX: 0, offsetY: 0 },
  joystick: { active: false, centerX: 0, centerY: 0, currentX: 0, currentY: 0, maxRadius: 40, baseRadius: 32, knobRadius: 12, deadZone: 4, touchId: null, fadeTimer: null, opacity: 0.7 },
  debug: { enabled: false, stateUpdateCounter: 0, lastPositions: {}, LOG_EVERY_N: 10, POS_EPSILON: 0.05 },
};

// Initialize debug from query string
const params = new URLSearchParams(window.location.search);
State.debug.enabled = params.get('debug') === '1' || params.get('debug') === 'true';