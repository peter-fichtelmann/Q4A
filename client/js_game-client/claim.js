// Contextual "claim" button for the third dodgeball. It only shows while the
// steered player may claim: a beater of the team the third dodgeball is assigned
// to, not knocked out, not holding a ball, and nobody else is claiming yet.
// The server re-checks all of this (process_claiming), so the button is a hint.
//
// Works for every input: tap on touch (bottom right, thumb zone, away from the
// joystick on the left third), click with the mouse, or the C key.
//
// Imports only state.js and utils.js on purpose, same as player_switch.js:
// network.js imports this module, so the socket is reached through State.

import { State } from './state.js';
import { onActivate } from './utils.js';

let claimButton = null;

export function sendClaim() {
  const socket = State.gameSocket;
  if (socket && socket.readyState === WebSocket.OPEN) {
    socket.send(JSON.stringify({ type: 'claim' }));
  }
}

function isBeater(player) {
  return player.role === 'beater' || player.role === 'BEATER';
}

/** True when the steered player may start a claim, judged from the last update. */
export function canClaim() {
  const gs = State.gameState;
  // The tutorial switches claiming off outside the steps that teach it.
  if (State.claimDisabled) return false;
  if (!gs || !gs.players || gs.is_game_live === false) return false;
  if (gs.third_dodgeball_team === null || gs.third_dodgeball_team === undefined) return false;
  const me = gs.players[State.localPlayerId];
  if (!me || !isBeater(me)) return false;
  if (Number(me.team) !== gs.third_dodgeball_team) return false;
  if (me.is_knocked_out || me.has_ball) return false;
  for (const player of Object.values(gs.players)) {
    if (player.is_claiming) return false;
  }
  return true;
}

function injectPulseStyle() {
  if (document.getElementById('claimButtonStyle')) return;
  const style = document.createElement('style');
  style.id = 'claimButtonStyle';
  style.textContent = '@keyframes claim-pulse {'
    + ' 0% { box-shadow: 0 0 0 0 rgba(255,215,64,0.7); }'
    + ' 70% { box-shadow: 0 0 0 14px rgba(255,215,64,0); }'
    + ' 100% { box-shadow: 0 0 0 0 rgba(255,215,64,0); } }';
  document.head.appendChild(style);
}

export function ensureClaimButton() {
  if (claimButton) return;
  injectPulseStyle();
  const btn = document.createElement('button');
  btn.id = 'claimButton';
  btn.title = 'Claim the third dodgeball (C)';
  btn.innerHTML = State.isTouchDevice
    ? 'CLAIM'
    : 'CLAIM <span style="opacity: 0.7; font-size: 12px;">[C]</span>';
  btn.style.cssText = 'position: fixed; right: 24px; bottom: calc(24px + env(safe-area-inset-bottom, 0px)); '
    + 'z-index: 1000; min-width: 88px; height: 88px; border-radius: 44px; padding: 0 16px; '
    + 'display: none; align-items: center; justify-content: center; gap: 6px; '
    + 'background: rgba(0,0,0,0.75); color: #ffd740; border: 3px solid #ffd740; '
    + 'font-size: 18px; font-weight: bold; font-family: monospace; cursor: pointer; '
    + 'animation: claim-pulse 1.2s infinite; user-select: none; touch-action: manipulation;';
  onActivate(btn, () => sendClaim());
  document.body.appendChild(btn);
  claimButton = btn;
}

/** Show or hide the button; called after every state update. */
export function updateClaimButton() {
  if (!claimButton) return;
  // inline display (not the hidden attribute): the inline style would override it
  const display = canClaim() ? 'flex' : 'none';
  if (claimButton.style.display !== display) claimButton.style.display = display;
}
