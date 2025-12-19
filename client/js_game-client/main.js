import { Config } from './config.js';
import { State } from './state.js';
import * as Viewport from './viewport.js';
import * as Fullscreen from './fullscreen.js';
import * as Network from './network.js';
import * as Input from './input.js';
import * as Rendering from './rendering.js';

function gameLoop() { Rendering.renderGame(); requestAnimationFrame(gameLoop); }

export function initializeCanvas() {
  State.canvas = document.getElementById('gameCanvas');
  State.ctx = State.canvas.getContext('2d');
  State.isTouchDevice = Input.detectTouchDevice();

  document.addEventListener('fullscreenchange', Fullscreen.updateState);
  document.addEventListener('webkitfullscreenchange', Fullscreen.updateState);
  document.addEventListener('msfullscreenchange', Fullscreen.updateState);
  document.addEventListener('mozfullscreenchange', Fullscreen.updateState);
  document.addEventListener('fullscreen-toggle', () => Fullscreen.toggle());

  if (State.isTouchDevice) {
    let tapCount = 0; let tapTimer = null;
    State.canvas.addEventListener('touchend', (e) => {
      const touch = e.changedTouches[0];
      const rect = State.canvas.getBoundingClientRect();
      const posX = touch.clientX - rect.left;
      if (posX > Config.CANVAS_WIDTH * 0.6) {
        tapCount++;
        if (tapCount === 1) { tapTimer = setTimeout(() => { tapCount = 0; }, 300); }
        else if (tapCount === 2) { clearTimeout(tapTimer); tapCount = 0; Fullscreen.toggle(); }
      }
    });
  }

  Viewport.resizeCanvasToFit();
  window.addEventListener('resize', () => { Viewport.resizeCanvasToFit(); });

  if (!State.isTouchDevice) {
    State.canvas.addEventListener('mousemove', (e) => {
      const rect = State.canvas.getBoundingClientRect();
      const px = e.clientX - rect.left; const py = e.clientY - rect.top;
      State.mousePos = { x: Math.max(0, Math.min(px, State.canvas.width)), y: Math.max(0, Math.min(py, State.canvas.height)) };
    });
    State.canvas.addEventListener('mouseleave', () => { State.mousePos = null; });
    State.canvas.addEventListener('click', (e) => { e.preventDefault(); Network.sendThrow(); });
  }

  if (State.isTouchDevice) {
    State.canvas.addEventListener('touchstart', (e) => {
      for (let i = 0; i < e.changedTouches.length; i++) {
        const touch = e.changedTouches[i];
        const rect = State.canvas.getBoundingClientRect();
        const pos = { x: touch.clientX - rect.left, y: touch.clientY - rect.top };
        let joystickStarted = false; let throwConducted = false;
        if (!joystickStarted && pos.x <= Config.CANVAS_WIDTH / 3) { Input.joystickStart(pos.x, pos.y, touch.identifier); joystickStarted = true; }
        if (!throwConducted && pos.x > Config.CANVAS_WIDTH / 3) { Network.sendThrow(); throwConducted = true; }
      }
    });
    State.canvas.addEventListener('touchmove', (e) => {
      e.preventDefault();
      for (let i = 0; i < e.changedTouches.length; i++) {
        const touch = e.changedTouches[i];
        if (State.joystick.active && touch.identifier === State.joystick.touchId) {
          const rect = State.canvas.getBoundingClientRect();
          const pos = { x: touch.clientX - rect.left, y: touch.clientY - rect.top };
          Input.joystickUpdate(pos.x, pos.y); break;
        }
      }
    });
    State.canvas.addEventListener('touchend', (e) => {
      e.preventDefault();
      for (let i = 0; i < e.changedTouches.length; i++) {
        const touch = e.changedTouches[i];
        if (State.joystick.active && touch.identifier === State.joystick.touchId) { Input.joystickEnd(); break; }
      }
    });
    State.canvas.addEventListener('touchcancel', (e) => {
      e.preventDefault();
      for (let i = 0; i < e.changedTouches.length; i++) {
        const touch = e.changedTouches[i];
        if (State.joystick.active && touch.identifier === State.joystick.touchId) { Input.joystickEnd(); break; }
      }
    });
  }

  Network.connectGame();
  gameLoop();
  setInterval(Input.update, 50);
}

// Global event listeners (keyboard)
window.addEventListener('keydown', Input.onKeyDown);
window.addEventListener('keyup', Input.onKeyUp);

// Optional: expose namespace for debugging
window.GameClient = { Config, State, Viewport, Fullscreen, Network, Input, Rendering, initializeCanvas };

// Initialize on load
window.addEventListener('load', initializeCanvas);
