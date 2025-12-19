import { Config } from './config.js';
import { State } from './state.js';
import { sendPlayerInput, sendThrow } from './network.js';

export const keys = {};

export function detectTouchDevice() {
  return ('ontouchstart' in window) || (navigator.maxTouchPoints > 0) || (navigator.msMaxTouchPoints > 0);
}

export function onKeyDown(e) {
  keys[e.key] = true;
  if (e.key === ' ') { e.preventDefault(); sendThrow(); }
  if (e.key === 'f' || e.key === 'F') { e.preventDefault(); document.dispatchEvent(new CustomEvent('fullscreen-toggle')); }
}

export function onKeyUp(e) { keys[e.key] = false; }

export function update() {
  let dirX = 0, dirY = 0;
  let actualDirX = 0, actualDirY = 0;
  if (keys['ArrowUp'] || keys['w']) dirY = -1;
  if (keys['ArrowDown'] || keys['s']) dirY = 1;
  if (keys['ArrowLeft'] || keys['a']) dirX = -1;
  if (keys['ArrowRight'] || keys['d']) dirX = 1;

  if (dirX === 0 && dirY === 0 && State.joystick.active) {
    const dx = State.joystick.currentX - State.joystick.centerX;
    const dy = State.joystick.currentY - State.joystick.centerY;
    const dist = Math.hypot(dx, dy);
    if (dist > State.joystick.deadZone) {
      const nx = dx / State.joystick.maxRadius;
      const ny = dy / State.joystick.maxRadius;
      dirX = nx * 3; dirY = ny * 3;
      sendPlayerInput(dirX, dirY);
      actualDirX = dirX; actualDirY = dirY;
    }
  } else if (dirX === 0 && dirY === 0 && !State.isTouchDevice && State.mousePos && State.gameState && State.localPlayerId && State.gameState.players && State.gameState.players[State.localPlayerId]) {
    try {
      let mx, my;
      if (State.viewport.enabled) {
        const xScale = Config.CANVAS_WIDTH / State.viewport.worldWidth;
        const yScale = Config.CANVAS_HEIGHT / State.viewport.worldHeight;
        mx = (State.mousePos.x - State.viewport.offsetX) / xScale;
        my = (State.mousePos.y - State.viewport.offsetY) / yScale;
      } else {
        const xScale = Config.CANVAS_WIDTH / Config.PITCH_LENGTH;
        const yScale = Config.CANVAS_HEIGHT / Config.PITCH_WIDTH;
        mx = State.mousePos.x / xScale;
        my = State.mousePos.y / yScale;
      }
      const p = State.gameState.players[State.localPlayerId];
      const pp = p.position || p.pos || p;
      let dx = mx - (pp.x || 0);
      let dy = my - (pp.y || 0);
      sendPlayerInput(dx, dy);
      actualDirX = dx; actualDirY = dy;
    } catch (err) { if (State.debug.enabled) console.warn('mouse input compute error', err); }
  } else if (dirX !== 0 || dirY !== 0) {
    sendPlayerInput(dirX, dirY);
    actualDirX = dirX; actualDirY = dirY;
  }

  if (State.gameState && State.gameState.players && State.gameState.players[State.localPlayerId]) {
    if (!State.gameState.players[State.localPlayerId].direction) State.gameState.players[State.localPlayerId].direction = { x: 0, y: 0 };
    State.gameState.players[State.localPlayerId].direction.x = actualDirX;
    State.gameState.players[State.localPlayerId].direction.y = actualDirY;
  }
}

export function getTouchPos(touch) {
  const rect = State.canvas.getBoundingClientRect();
  return { x: touch.clientX - rect.left, y: touch.clientY - rect.top };
}

export function joystickStart(x, y, touchId) {
  State.joystick.active = true;
  State.joystick.centerX = x;
  State.joystick.centerY = y;
  State.joystick.currentX = x;
  State.joystick.currentY = y;
  State.joystick.touchId = touchId;
  State.joystick.opacity = 0.7;
  if (State.joystick.fadeTimer) { clearTimeout(State.joystick.fadeTimer); State.joystick.fadeTimer = null; }
  return true;
}

export function joystickUpdate(x, y) {
  if (!State.joystick.active) return;
  const dx = x - State.joystick.centerX;
  const dy = y - State.joystick.centerY;
  const dist = Math.hypot(dx, dy);
  if (dist <= State.joystick.maxRadius) { State.joystick.currentX = x; State.joystick.currentY = y; }
  else { const a = Math.atan2(dy, dx); State.joystick.currentX = State.joystick.centerX + Math.cos(a) * State.joystick.maxRadius; State.joystick.currentY = State.joystick.centerY + Math.sin(a) * State.joystick.maxRadius; }
}

export function joystickEnd() {
  if (!State.joystick.active) return;
  State.joystick.active = false; State.joystick.touchId = null;
  const fadeOut = () => {
    State.joystick.opacity -= 0.05;
    if (State.joystick.opacity > 0) { State.joystick.fadeTimer = setTimeout(fadeOut, 50); }
    else { State.joystick.opacity = 0; State.joystick.fadeTimer = null; }
  };
  State.joystick.fadeTimer = setTimeout(fadeOut, 500);
}