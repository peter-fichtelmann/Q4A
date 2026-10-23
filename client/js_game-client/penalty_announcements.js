// Penalty turnovers (delay of game, stalled volleyball, third dodgeball interference).
//
// The server sends one `penalty_turnover` message per turnover (PenaltyLogic.announce_turnover).
// The rule is drawn at the spot where it happened, in the stalled-countdown style,
// and a randomly male or female voice says "<rule> - <balls> turnover".

import { Config } from './config.js';
import { isMuted } from './audio.js';

const RULE_LABELS = {
  delay_of_game: 'Delay of game',
  stalled_volleyball: 'Stalled volleyball',
  third_dodgeball_interference: 'Third dodgeball interference',
};

// Real-time ms the label stays fully visible, then how long it takes to fade out.
const LABEL_HOLD_MS = 2000;
const LABEL_FADE_MS = 500;

// Speech voices carry no gender, so it is guessed from the voice name.
const FEMALE_VOICE_HINTS = ['female', 'woman', 'zira', 'samantha', 'victoria', 'karen', 'moira', 'tessa', 'fiona', 'hazel', 'susan', 'catherine', 'jenny', 'aria', 'libby', 'sonia', 'natasha', 'emma', 'serena', 'allison', 'ava', 'kate', 'linda', 'heather', 'michelle', 'clara', 'eva', 'katja', 'hedda', 'anna', 'amy', 'joanna', 'salli', 'kimberly', 'ivy', 'kendra'];
const MALE_VOICE_HINTS = ['male', 'man', 'david', 'mark', 'daniel', 'alex', 'fred', 'george', 'guy', 'ryan', 'james', 'thomas', 'oliver', 'arthur', 'aaron', 'rishi', 'tom', 'stefan', 'conrad', 'christopher', 'eric', 'brian', 'matthew', 'justin', 'joey', 'william', 'gordon', 'lee', 'richard', 'paul'];
// Pitch used to tell the genders apart when no matching voice is installed.
const FALLBACK_PITCH = { female: 1.35, male: 0.75 };

const active = [];

function nowMs() {
  return (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
}

function ruleLabel(rule) {
  return RULE_LABELS[rule] || String(rule || 'Penalty').replace(/_/g, ' ');
}

/** "volleyball", "volleyball and dodgeball", "volleyball and two dodgeballs", ... */
function ballsPhrase(balls) {
  const counts = {};
  for (const ball of balls || []) counts[ball] = (counts[ball] || 0) + 1;
  const numberWords = ['', '', 'two', 'three'];
  const parts = Object.entries(counts).map(([type, n]) => (n === 1 ? type : `${numberWords[n] || n} ${type}s`));
  if (parts.length <= 1) return parts.join('');
  return `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`;
}

function nameMatches(name, hints) {
  const words = name.toLowerCase().split(/[^a-z]+/);
  return hints.some((hint) => words.includes(hint));
}

function pickVoice(gender) {
  const synth = window.speechSynthesis;
  const voices = synth.getVoices().filter((voice) => /^en/i.test(voice.lang));
  const hints = gender === 'female' ? FEMALE_VOICE_HINTS : MALE_VOICE_HINTS;
  // 'female' contains 'male', so whole words are compared and female names are excluded for men.
  const matching = voices.filter((voice) => nameMatches(voice.name, hints)
    && (gender === 'female' || !nameMatches(voice.name, FEMALE_VOICE_HINTS)));
  if (matching.length > 0) return { voice: matching[Math.floor(Math.random() * matching.length)], pitch: 1 };
  return { voice: voices[0] || null, pitch: FALLBACK_PITCH[gender] };
}

function speak(text) {
  if (isMuted() || typeof window === 'undefined' || !window.speechSynthesis) return;
  const gender = Math.random() < 0.5 ? 'female' : 'male';
  const { voice, pitch } = pickVoice(gender);
  const utterance = new SpeechSynthesisUtterance(text);
  if (voice) { utterance.voice = voice; utterance.lang = voice.lang; } else { utterance.lang = 'en-US'; }
  utterance.pitch = pitch;
  window.speechSynthesis.speak(utterance);
}

// Some browsers load the voice list asynchronously; touching it early starts that load.
if (typeof window !== 'undefined' && window.speechSynthesis) {
  try { window.speechSynthesis.getVoices(); } catch (e) {}
}

/** Handle a `penalty_turnover` message from the server. */
export function handlePenaltyTurnover(message) {
  const label = ruleLabel(message.rule);
  active.push({ label, x: Number(message.x) || 0, y: Number(message.y) || 0, startMs: nowMs() });
  const balls = ballsPhrase(message.balls);
  speak(balls ? `${label} - ${balls} turnover` : `${label} - turnover`);
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
