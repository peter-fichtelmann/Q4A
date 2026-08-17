// Two floating buttons that hand control to a CPU teammate: one cycles through
// the same position, one walks to the next position. Built the same way as the
// fullscreen button (created in JS, inline styles) and stacked below it.
//
// Imports only state.js on purpose: network.js imports this module to mount the
// buttons, so importing network.js back would create a module cycle. The socket
// is reached through State instead.

import { State } from './state.js';
import { onActivate } from './utils.js';

export const SAME_POSITION = 'same_position';
export const NEXT_POSITION = 'next_position';

const FORBIDDEN_MS = 5000;

// Server-side failure reasons (see player_switch.py).
const REASON_DISABLED = 'disabled';
const REASON_MESSAGES = {
  [REASON_DISABLED]: 'Stick with your current player for now.',
};

const BUTTONS = [
  {
    mode: SAME_POSITION,
    id: 'switchSamePositionButton',
    // Leftwards arrow over rightwards arrow.
    glyph: '⇆',
    title: 'Switch player, same position (Q)',
    top: 58,
  },
  {
    mode: NEXT_POSITION,
    id: 'switchNextPositionButton',
    // Upwards arrow beside downwards arrow.
    glyph: '⇅',
    title: 'Switch to the next position (E)',
    top: 106,
  },
];

// Matches the fullscreen button's look; fixed box so the button stack lines up.
// Exported because audio.js hangs the mute button off the bottom of the same stack.
export function buttonStyle(top) {
  return 'position: fixed; top: ' + top + 'px; right: 10px; z-index: 1000; '
    + 'width: 44px; height: 40px; display: flex; align-items: center; justify-content: center; '
    + 'background: rgba(0,0,0,0.7); color: white; border: 2px solid rgba(255,255,255,0.3); '
    + 'border-radius: 8px; padding: 0; font-size: 18px; cursor: pointer; font-family: monospace; '
    + 'transition: all 0.3s ease; user-select: none; touch-action: manipulation;';
}

export function sendSwitch(mode) {
  const socket = State.gameSocket;
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: 'switch_player', mode }));
  }
}

export function ensureButtons() {
  for (const spec of BUTTONS) {
    if (State.playerSwitch.buttons[spec.mode]) continue;
    const btn = document.createElement('button');
    btn.id = spec.id;
    btn.innerHTML = spec.glyph;
    btn.title = spec.title;
    btn.style.cssText = buttonStyle(spec.top);
    btn.addEventListener('mouseenter', () => {
      btn.style.borderColor = 'rgba(255,255,255,0.6)';
      btn.style.transform = 'scale(1.05)';
    });
    btn.addEventListener('mouseleave', () => {
      btn.style.borderColor = 'rgba(255,255,255,0.3)';
      btn.style.transform = 'scale(1)';
    });
    onActivate(btn, () => sendSwitch(spec.mode));
    document.body.appendChild(btn);
    State.playerSwitch.buttons[spec.mode] = btn;
  }
}

// Circle with a 45-degree rotated cross, drawn as SVG so it looks the same
// everywhere (the 🚫 emoji renders very differently across platforms).
function forbiddenOverlay() {
  const overlay = document.createElement('span');
  overlay.className = 'switch-forbidden';
  overlay.style.cssText = 'position: absolute; inset: 0; display: flex; align-items: center; '
    + 'justify-content: center; pointer-events: none;';
  overlay.innerHTML = '<svg viewBox="0 0 24 24" width="30" height="30" aria-hidden="true">'
    + '<circle cx="12" cy="12" r="9" fill="none" stroke="#ff4d4d" stroke-width="2.5"/>'
    + '<line x1="5.6" y1="18.4" x2="18.4" y2="5.6" stroke="#ff4d4d" stroke-width="2.5"/>'
    + '</svg>';
  return overlay;
}

// Explains *why* a switch was refused, next to the button that refused it.
// Sits left of the button column so it never covers the forbidden sign.
function messageElement(text, top) {
  const note = document.createElement('div');
  note.className = 'switch-message';
  note.textContent = text;
  note.style.cssText = 'position: fixed; top: ' + top + 'px; right: 62px; z-index: 1000; '
    + 'max-width: 210px; background: rgba(0,0,0,0.8); color: white; '
    + 'border: 1px solid rgba(255,255,255,0.25); border-radius: 8px; padding: 6px 10px; '
    + 'font-size: 13px; font-family: sans-serif; line-height: 1.3; text-align: right; '
    + 'pointer-events: none; user-select: none;';
  return note;
}

/**
 * Mark a switch as refused: show the forbidden sign over its button for 5s,
 * plus a short explanation when the server gave a reason we have copy for.
 */
export function showForbidden(mode, reason) {
  const button = State.playerSwitch.buttons[mode];
  if (!button) return;

  const timers = State.playerSwitch.forbiddenTimers;
  if (timers[mode]) {
    clearTimeout(timers[mode].timer);
    timers[mode].overlay.remove();
    if (timers[mode].note) timers[mode].note.remove();
  }

  const overlay = forbiddenOverlay();
  button.appendChild(overlay);

  let note = null;
  const text = REASON_MESSAGES[reason];
  if (text) {
    const spec = BUTTONS.find((entry) => entry.mode === mode);
    note = messageElement(text, spec ? spec.top : 58);
    document.body.appendChild(note);
  }

  timers[mode] = {
    overlay,
    note,
    timer: setTimeout(() => {
      overlay.remove();
      if (note) note.remove();
      delete timers[mode];
    }, FORBIDDEN_MS),
  };
}
