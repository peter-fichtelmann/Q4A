// In-game settings menu. Opening it pauses the game for everybody; it offers this
// player's audio volume, the throw assist toggle and a way into the room lobby (positions and teams, spectating).
//
// Imports no network.js (network.js imports this module); the socket is reached
// through State, like player_switch.js does.

import { State } from './state.js';
import { onActivate } from './utils.js';
import { buttonStyle } from './player_switch.js';
import * as Audio from './audio.js';

// Continues the fullscreen / switch / mute button column.
const SETTINGS_BUTTON_TOP = 202;

let settingsButton = null;
let panel = null;
let lobbyFrame = null;
let pausedBanner = null;
let menuOpen = false;

// Throw assist (server rotates throws by a few degrees onto a pass, beat or shot); on by default, kept across games.
const THROW_ASSIST_STORAGE_KEY = 'q4a_throw_assist';
let throwAssist = true;
try {
  throwAssist = localStorage.getItem(THROW_ASSIST_STORAGE_KEY) !== 'off';
} catch (e) {}

// Names of the human players drawn above their players; on by default, kept across games.
const SHOW_NAMES_STORAGE_KEY = 'q4a_show_names';
try {
  State.showNames = localStorage.getItem(SHOW_NAMES_STORAGE_KEY) !== 'off';
} catch (e) {}

function setShowNames(enabled) {
  State.showNames = enabled;
  try { localStorage.setItem(SHOW_NAMES_STORAGE_KEY, enabled ? 'on' : 'off'); } catch (e) {}
}

function send(type, fields = {}) {
  const socket = State.gameSocket;
  if (socket && socket.readyState === WebSocket.OPEN) socket.send(JSON.stringify({ type, ...fields }));
}

/** Tell the server this player's throw assist setting (on connect and on change). */
export function sendThrowAssist() {
  send('throw_assist', { enabled: throwAssist });
}

function setThrowAssist(enabled) {
  throwAssist = enabled;
  try { localStorage.setItem(THROW_ASSIST_STORAGE_KEY, enabled ? 'on' : 'off'); } catch (e) {}
  sendThrowAssist();
}

function el(tag, css, text) {
  const node = document.createElement(tag);
  if (css) node.style.cssText = css;
  if (text !== undefined) node.textContent = text;
  return node;
}

const OVERLAY_CSS = 'position: fixed; inset: 0; z-index: 2000; display: flex; align-items: center; '
  + 'justify-content: center; background: rgba(0,0,0,0.65); font-family: sans-serif; color: white;';
const CARD_CSS = 'background: #1c2233; border: 2px solid rgba(255,255,255,0.25); border-radius: 12px; '
  + 'padding: 20px 24px; width: min(420px, 92vw); max-height: 92vh; overflow: auto; box-sizing: border-box;';
const BTN_CSS = 'display: block; width: 100%; margin-top: 12px; padding: 10px 14px; font-size: 16px; '
  + 'color: white; background: #2f3b5c; border: 1px solid rgba(255,255,255,0.3); border-radius: 8px; cursor: pointer;';

function buildPanel() {
  panel = el('div', OVERLAY_CSS);
  panel.id = 'settingsPanel';
  const card = el('div', CARD_CSS);
  card.appendChild(el('h2', 'margin: 0 0 14px 0;', 'Settings'));

  card.appendChild(el('div', 'margin-bottom: 6px;', 'Volume'));
  const slider = el('input', 'width: 100%;');
  slider.type = 'range';
  slider.min = '0';
  slider.max = '100';
  slider.value = String(Math.round(Audio.getMasterVolume() * 100));
  slider.addEventListener('input', () => Audio.setMasterVolume(Number(slider.value) / 100));
  card.appendChild(slider);

  const assistLabel = el('label', 'display: flex; align-items: center; gap: 8px; margin-top: 14px; cursor: pointer;');
  const assistBox = el('input', 'width: 18px; height: 18px;');
  assistBox.type = 'checkbox';
  assistBox.checked = throwAssist;
  assistBox.addEventListener('change', () => setThrowAssist(assistBox.checked));
  assistLabel.appendChild(assistBox);
  assistLabel.appendChild(el('span', '', 'Throw assist (corrects passes, beats and shots by a few degrees)'));
  card.appendChild(assistLabel);

  const namesLabel = el('label', 'display: flex; align-items: center; gap: 8px; margin-top: 10px; cursor: pointer;');
  const namesBox = el('input', 'width: 18px; height: 18px;');
  namesBox.type = 'checkbox';
  namesBox.checked = State.showNames;
  namesBox.addEventListener('change', () => setShowNames(namesBox.checked));
  namesLabel.appendChild(namesBox);
  namesLabel.appendChild(el('span', '', 'Show names of human players above their players'));
  card.appendChild(namesLabel);

  const lobbyBtn = el('button', BTN_CSS, 'Change game room (teams & positions)');
  lobbyBtn.addEventListener('click', showLobby);
  card.appendChild(lobbyBtn);

  const resumeBtn = el('button', BTN_CSS + 'background: #2e7d4f;', 'Resume game');
  resumeBtn.addEventListener('click', closeMenu);
  card.appendChild(resumeBtn);

  const leaveBtn = el('button', BTN_CSS, 'Leave game');
  leaveBtn.addEventListener('click', () => {
    if (State.gameSocket) State.gameSocket.close();
    window.location.href = '/';
  });
  card.appendChild(leaveBtn);

  panel.appendChild(card);
  document.body.appendChild(panel);
}

function showLobby() {
  if (!panel || lobbyFrame) return;
  const card = panel.firstChild;
  card.style.display = 'none';
  const wrap = el('div', CARD_CSS + 'width: min(1000px, 96vw); height: 90vh; padding: 10px; display: flex; flex-direction: column;');
  wrap.id = 'settingsLobbyWrap';
  const back = el('button', BTN_CSS + 'width: auto; margin: 0 0 8px 0; align-self: flex-start;', '← Back to settings');
  back.addEventListener('click', () => {
    wrap.remove();
    lobbyFrame = null;
    card.style.display = '';
  });
  wrap.appendChild(back);
  lobbyFrame = el('iframe', 'flex: 1; width: 100%; border: 0; border-radius: 8px; background: #101626;');
  lobbyFrame.src = `/room?room_id=${encodeURIComponent(State.roomId)}&player_id=${encodeURIComponent(State.connectionPlayerId)}&ingame=1`;
  wrap.appendChild(lobbyFrame);
  panel.appendChild(wrap);
}

function openMenu() {
  if (menuOpen || State.isTutorial) return;
  menuOpen = true;
  buildPanel();
  send('settings_open');
}

function closeMenu() {
  if (!menuOpen) return;
  menuOpen = false;
  lobbyFrame = null;
  if (panel) { panel.remove(); panel = null; }
  send('settings_close');
}

function toggleMenu() { if (menuOpen) closeMenu(); else openMenu(); }

/** Server says who has a settings menu open; show a banner to everybody else. */
export function applyPauseState(message) {
  const paused = !!message.paused;
  if (paused && !State.paused) State.pausedAtMs = performance.now();
  State.paused = paused;
  if (!paused) {
    if (pausedBanner) { pausedBanner.remove(); pausedBanner = null; }
    return;
  }
  if (menuOpen) return;
  const who = (message.by && message.by.length) ? message.by.join(', ') : 'A player';
  if (!pausedBanner) {
    pausedBanner = el('div', OVERLAY_CSS + 'pointer-events: auto; font-size: 22px; text-align: center;');
    pausedBanner.id = 'pausedBanner';
    document.body.appendChild(pausedBanner);
  }
  pausedBanner.textContent = `Game paused – ${who} is in the settings menu`;
}

let toggleListenerAdded = false;

export function ensureSettingsButton() {
  if (!toggleListenerAdded) {
    document.addEventListener('settings-toggle', toggleMenu);
    toggleListenerAdded = true;
  }
  if (State.isTutorial || settingsButton) return;
  const btn = document.createElement('button');
  btn.id = 'settingsButton';
  btn.innerHTML = '⚙';
  btn.title = 'Settings (Esc)';
  btn.style.cssText = buttonStyle(SETTINGS_BUTTON_TOP);
  onActivate(btn, toggleMenu);
  document.body.appendChild(btn);
  settingsButton = btn;
}
