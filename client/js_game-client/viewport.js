import { Config } from './config.js';
import { State } from './state.js';
import { screenTooSmallRatio } from './utils.js';

export function resizeCanvasToFit() {
  const canvas = State.canvas;
  if (!canvas) return;

  const ratio = screenTooSmallRatio();
  State.viewport.enabled = ratio < 1.0;
  if (State.viewport.enabled) {
    State.viewport.worldWidth = Math.max(30, Config.PITCH_LENGTH * ratio);
    State.viewport.worldHeight = Math.max(16.5, Config.PITCH_WIDTH * ratio);
  } else {
    State.viewport.worldWidth = 30;
    State.viewport.worldHeight = 16.5;
  }

  const maxWidth = window.innerWidth;
  const maxHeight = window.innerHeight;
  let targetRatio = State.viewport.enabled
    ? State.viewport.worldWidth / State.viewport.worldHeight
    : (Config.PITCH_WIDTH > 0 ? (Config.PITCH_LENGTH / Config.PITCH_WIDTH) : (60 / 33));

  let newWidth = maxWidth;
  let newHeight = newWidth / targetRatio;
  if (newHeight > maxHeight) {
    newHeight = maxHeight;
    newWidth = newHeight * targetRatio;
  }

  Config.CANVAS_WIDTH = Math.round(newWidth);
  Config.CANVAS_HEIGHT = Math.round(newHeight);

  canvas.width = Config.CANVAS_WIDTH;
  canvas.height = Config.CANVAS_HEIGHT;
  canvas.style.width = `${Config.CANVAS_WIDTH}px`;
  canvas.style.height = `${Config.CANVAS_HEIGHT}px`;

  State.ctx = canvas.getContext('2d');
}

export function updateViewport() {
  const gs = State.gameState;
  if (!State.viewport.enabled || !gs || !State.localPlayerId || !gs.players || !gs.players[State.localPlayerId]) return;

  const player = gs.players[State.localPlayerId];
  const pos = player.position || player.pos || player;
  State.viewport.centerX = pos.x || 0;
  State.viewport.centerY = pos.y || 0;

  const halfWorldWidth = State.viewport.worldWidth / 2;
  const halfWorldHeight = State.viewport.worldHeight / 2;
  State.viewport.centerX = Math.max(halfWorldWidth, Math.min(Config.PITCH_LENGTH - halfWorldWidth, State.viewport.centerX));
  State.viewport.centerY = Math.max(halfWorldHeight, Math.min(Config.PITCH_WIDTH - halfWorldHeight, State.viewport.centerY));

  const xScale = Config.CANVAS_WIDTH / State.viewport.worldWidth;
  const yScale = Config.CANVAS_HEIGHT / State.viewport.worldHeight;
  State.viewport.offsetX = -State.viewport.centerX * xScale + Config.CANVAS_WIDTH / 2;
  State.viewport.offsetY = -State.viewport.centerY * yScale + Config.CANVAS_HEIGHT / 2;
}

export function worldToScreen(wx, wy, xScale, yScale, offsetX, offsetY) {
  return { x: wx * xScale + offsetX, y: wy * yScale + offsetY };
}

export function isVisible(wx, wy, margin, xScale, yScale, offsetX, offsetY) {
  if (!State.viewport.enabled) return true;
  const screen = worldToScreen(wx, wy, xScale, yScale, offsetX, offsetY);
  const m = margin ?? 2;
  return (
    screen.x >= -m && screen.x <= Config.CANVAS_WIDTH + m &&
    screen.y >= -m && screen.y <= Config.CANVAS_HEIGHT + m
  );
}