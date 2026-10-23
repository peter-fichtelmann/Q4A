// Referee calls from the server (PenaltyLogic.announcements).
//
// `penalty_turnover` (delay of game, stalled volleyball, third dodgeball interference):
// the rule is drawn at the spot where it happened, in the stalled-countdown style, and
// a voice says "<rule> - <players> back to hoops, <balls> turnover".
// `inbounding` (volleyball out of bounds): the voice calls the inbounding team.

import { Config } from './config.js';
import { speak } from './audio.js';

const RULE_LABELS = {
  delay_of_game: 'Delay of game',
  stalled_volleyball: 'Stalled volleyball',
  third_dodgeball_interference: 'Third dodgeball interference',
};

// Real-time ms the label stays fully visible, then how long it takes to fade out.
const LABEL_HOLD_MS = 2000;
const LABEL_FADE_MS = 500;

const active = [];

function nowMs() {
  return (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
}

function ruleLabel(rule) {
  return RULE_LABELS[rule] || String(rule || 'Penalty').replace(/_/g, ' ');
}

const TEAM_LABELS = ['Team A', 'Team B'];

/** "volleyball", "volleyball and dodgeball", "volleyball and two dodgeballs", ... */
function countPhrase(items) {
  const counts = {};
  for (const item of items || []) counts[item] = (counts[item] || 0) + 1;
  const numberWords = ['', '', 'two', 'three'];
  const parts = Object.entries(counts).map(([type, n]) => (n === 1 ? type : `${numberWords[n] || n} ${type}s`));
  if (parts.length <= 1) return parts.join('');
  return `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`;
}

/** Handle a `penalty_turnover` message from the server. */
export function handlePenaltyTurnover(message) {
  const label = ruleLabel(message.rule);
  active.push({ label, x: Number(message.x) || 0, y: Number(message.y) || 0, startMs: nowMs() });
  const calls = [];
  const backToHoops = countPhrase(message.back_to_hoops);
  if (backToHoops) calls.push(`${backToHoops} back to hoops`);
  const balls = countPhrase(message.balls);
  calls.push(balls ? `${balls} turnover` : 'turnover');
  speak(`${label} - ${calls.join(', ')}`);
}

/** Handle an `inbounding` message: the volleyball went out of bounds. */
export function handleInbounding(message) {
  const team = TEAM_LABELS[message.team];
  if (team) speak(`Inbounding ${team}`);
}

/** Draw the rule labels of recent penalty turnovers at the spots where they happened. */
export function drawPenaltyAnnouncements(ctx, worldToScreen, xScale) {
  const now = nowMs();
  for (let i = active.length - 1; i >= 0; i--) {
    if (now - active[i].startMs > LABEL_HOLD_MS + LABEL_FADE_MS) active.splice(i, 1);
  }
  if (active.length === 0) return;
  // same font as drawStalledCountdown in rendering.js
  const fontPx = Math.max(12, xScale * 1.1);
  ctx.save();
  ctx.font = `bold ${fontPx}px sans-serif`;
  ctx.textAlign = 'center';
  ctx.textBaseline = 'middle';
  ctx.lineWidth = Math.max(2, fontPx * 0.15);
  ctx.strokeStyle = 'rgba(0, 0, 0, 0.75)';
  ctx.fillStyle = '#ffffff';
  for (const announcement of active) {
    const age = now - announcement.startMs;
    ctx.globalAlpha = age <= LABEL_HOLD_MS ? 1 : Math.max(0, 1 - (age - LABEL_HOLD_MS) / LABEL_FADE_MS);
    const pos = worldToScreen(announcement.x, announcement.y);
    // above the spot, where the stalled countdown sits above the volleyball
    const cy = pos.y - Math.max(10, Config.VOLLEYBALL_RADIUS * xScale * 4) - fontPx * 0.5;
    // keep the text inside the canvas near the side lines
    const halfWidth = ctx.measureText(announcement.label).width / 2;
    const cx = Math.min(Math.max(pos.x, halfWidth + 4), Config.CANVAS_WIDTH - halfWidth - 4);
    ctx.strokeText(announcement.label, cx, Math.max(fontPx, cy));
    ctx.fillText(announcement.label, cx, Math.max(fontPx, cy));
  }
  ctx.restore();
}
