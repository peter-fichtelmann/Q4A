// Crowd bed for the game page plus the cheer for a goal or a flag-runner catch.
// A beat makes the crowd swell: the bed jumps to 1.75x and fades back over 1s.
//
// One atmosphere track plays at half volume; 1.5s before it ends a different one
// starts, so the two overlap briefly and the bed never drops to silence.
//
// Imports player_switch.js only for the shared button styling. It must not import
// network.js: network.js imports this module to mount the mute button, so that
// would create a module cycle.

import { buttonStyle } from './player_switch.js';
import { onActivate } from './utils.js';

const ATMOSPHERE_TRACKS = [
  '/client/assets/sound_effects/pitch_atmosphere/itmightgetloud-1.mp3',
  '/client/assets/sound_effects/pitch_atmosphere/itmightgetloud-2.mp3',
  '/client/assets/sound_effects/pitch_atmosphere/itmightgetloud-3.mp3',
  '/client/assets/sound_effects/pitch_atmosphere/neilraouf.mp3',
];

const EVENT_SOUNDS = [
  '/client/assets/sound_effects/event_sounds/score_goal.mp3',
  '/client/assets/sound_effects/event_sounds/score_goal-2.mp3',
];

const ATMOSPHERE_VOLUME = 0.5;
const EVENT_VOLUME = 1.0;
const CROSSFADE_LEAD_SECONDS = 1.5;
const BEAT_SWELL_FACTOR = 1.75;
const BEAT_SWELL_FADE_MS = 1000;
// A third-dodgeball interference penalty also knocks a player out. Its
// penalty_turnover message is broadcast just before the state that shows the
// knockout, so knockouts this soon after one are not taken for a beat.
const INTERFERENCE_SUPPRESS_MS = 500;

// Browsers refuse to start audio before the user has interacted with the page,
// so playback waits for one of these.
const UNLOCK_EVENTS = ['pointerdown', 'touchstart', 'keydown'];

// Continues the fullscreen / player-switch button column.
const MUTE_BUTTON_TOP = 154;

let started = false;
let muted = false;
// Player-chosen loudness (0..1) applied on top of every sound; kept across games.
const VOLUME_STORAGE_KEY = 'q4a_master_volume';
let masterVolume = 1;
try {
  const stored = parseFloat(localStorage.getItem(VOLUME_STORAGE_KEY));
  if (Number.isFinite(stored)) masterVolume = Math.min(1, Math.max(0, stored));
} catch (e) {}
let unlockRegistered = false;
// Every atmosphere element that is still audible: the running track plus, during
// the crossfade, the one playing itself out. Kept so muting reaches both.
const liveTracks = new Set();
let muteButton = null;
// Running total of both teams' scores; null until the first state arrives.
let lastScoreTotal = null;
// is_knocked_out per player id as of the previous state, to spot new knockouts.
const lastKnockedOut = new Map();
let swellStartMs = null;
let swellFrame = null;
let interferenceAtMs = -Infinity;

/** Normalize `play()` across browsers that return nothing instead of a promise. */
function toPromise(playback) {
  return (playback && typeof playback.catch === 'function') ? playback : Promise.resolve();
}

/** A random track index that is never `excludeIndex`. */
function pickOtherTrackIndex(excludeIndex) {
  if (ATMOSPHERE_TRACKS.length < 2) return 0;
  let index = Math.floor(Math.random() * (ATMOSPHERE_TRACKS.length - 1));
  if (index >= excludeIndex) index += 1;
  return index;
}

/** Bed volume right now: the base level, raised while a beat swell fades out. */
function baseAtmosphereVolume() {
  return ATMOSPHERE_VOLUME * masterVolume;
}

function atmosphereVolume() {
  if (swellStartMs === null) return baseAtmosphereVolume();
  const progress = (performance.now() - swellStartMs) / BEAT_SWELL_FADE_MS;
  if (progress >= 1) return baseAtmosphereVolume();
  const factor = BEAT_SWELL_FACTOR + (1 - BEAT_SWELL_FACTOR) * progress;
  return Math.min(1, baseAtmosphereVolume() * factor);
}

function applySwellFrame() {
  const volume = atmosphereVolume();
  for (const element of liveTracks) element.volume = volume;
  if (volume === baseAtmosphereVolume()) {
    swellStartMs = null;
    swellFrame = null;
    return;
  }
  swellFrame = requestAnimationFrame(applySwellFrame);
}

/** Jump the bed to 1.75x and fade it back to normal over 1s; a new beat restarts it. */
export function swellAtmosphere() {
  swellStartMs = performance.now();
  if (swellFrame === null) applySwellFrame();
  else for (const element of liveTracks) element.volume = atmosphereVolume();
}

function playTrack(index) {
  const element = new Audio(ATMOSPHERE_TRACKS[index]);
  element.volume = atmosphereVolume();
  element.muted = muted;
  element.preload = 'auto';
  liveTracks.add(element);

  let successorStarted = false;
  const startSuccessor = () => {
    if (successorStarted) return;
    successorStarted = true;
    playTrack(pickOtherTrackIndex(index)).catch(() => {});
  };

  // Scheduled on timeupdate (fires ~4x/s) rather than a timeout computed from
  // the duration up front, so a track that stalls while buffering still hands
  // over 1.5s before its real end.
  element.addEventListener('timeupdate', () => {
    // The length guard keeps a track shorter than the lead time from chaining the
    // whole playlist at once; such a track just hands over when it ends.
    if (!Number.isFinite(element.duration) || element.duration <= CROSSFADE_LEAD_SECONDS) return;
    if (element.duration - element.currentTime <= CROSSFADE_LEAD_SECONDS) startSuccessor();
  });
  // Safety net: if the duration never became known, nothing was scheduled above,
  // so chain here instead of letting the bed die. The old element is otherwise
  // left alone — playing out its last 1.5s under the new one is the crossfade.
  element.addEventListener('ended', () => {
    liveTracks.delete(element);
    startSuccessor();
  });

  return toPromise(element.play());
}

function stopAllTracks() {
  for (const element of liveTracks) element.pause();
  liveTracks.clear();
}

/** Start the crowd bed. Idempotent; rejects while autoplay is still blocked. */
export function startAtmosphere() {
  if (started) return Promise.resolve();
  started = true;
  const index = Math.floor(Math.random() * ATMOSPHERE_TRACKS.length);
  return playTrack(index).catch((err) => {
    // Still blocked: forget the attempt so a later gesture can retry.
    started = false;
    stopAllTracks();
    throw err;
  });
}

/** Wait for the first user gesture, then start the bed. */
export function unlockOnFirstGesture() {
  if (unlockRegistered) return;
  unlockRegistered = true;
  const onGesture = () => {
    startAtmosphere()
      .then(() => {
        for (const name of UNLOCK_EVENTS) window.removeEventListener(name, onGesture);
      })
      .catch(() => {});  // keep listening and retry on the next gesture
  };
  for (const name of UNLOCK_EVENTS) window.addEventListener(name, onGesture);
}

/** One of the two goal clips, at full volume, over the atmosphere. */
export function playScoreSound() {
  if (muted) return;
  const url = EVENT_SOUNDS[Math.floor(Math.random() * EVENT_SOUNDS.length)];
  // A fresh element per call so goals in quick succession do not cut each other off.
  const element = new Audio(url);
  element.volume = EVENT_VOLUME * masterVolume;
  toPromise(element.play()).catch(() => {});
}

/**
 * Fire the goal sound whenever the score went up.
 *
 * Both events the sound is for reach the client the same way: a quaffle goal adds
 * 1 (volleyball_logic._check_goals) and a caught flag runner adds 3
 * (flag_runner_logic.resolve_catch). The score never decreases, so an increase is
 * exactly "something was scored". The first call only records the baseline, so a
 * client joining a running game does not cheer for goals it never saw.
 */
export function noteScore(score) {
  if (!Array.isArray(score)) return;
  const total = (Number(score[0]) || 0) + (Number(score[1]) || 0);
  if (lastScoreTotal !== null && total > lastScoreTotal) playScoreSound();
  lastScoreTotal = total;
}

/** Called for every penalty turnover; see INTERFERENCE_SUPPRESS_MS. */
export function notePenaltyTurnover(rule) {
  if (rule === 'third_dodgeball_interference') interferenceAtMs = performance.now();
}

/**
 * Swell the crowd whenever a player was newly knocked out, i.e. beaten.
 *
 * Like noteScore, a player seen for the first time only sets the baseline, so
 * joining a running game does not swell for players already knocked out.
 */
export function noteKnockouts(players) {
  if (!players) return;
  let beaten = false;
  for (const [id, player] of Object.entries(players)) {
    const knockedOut = !!player.is_knocked_out;
    if (knockedOut && lastKnockedOut.get(id) === false) beaten = true;
    lastKnockedOut.set(id, knockedOut);
  }
  if (beaten && performance.now() - interferenceAtMs > INTERFERENCE_SUPPRESS_MS) swellAtmosphere();
}

// Referee voice (penalty turnovers, inbounding, flag catch verdict).

// Speech voices carry no gender, so it is guessed from the voice name.
const FEMALE_VOICE_HINTS = ['female', 'woman', 'zira', 'samantha', 'victoria', 'karen', 'moira', 'tessa', 'fiona', 'hazel', 'susan', 'catherine', 'jenny', 'aria', 'libby', 'sonia', 'natasha', 'emma', 'serena', 'allison', 'ava', 'kate', 'linda', 'heather', 'michelle', 'clara', 'eva', 'katja', 'hedda', 'anna', 'amy', 'joanna', 'salli', 'kimberly', 'ivy', 'kendra'];
const MALE_VOICE_HINTS = ['male', 'man', 'david', 'mark', 'daniel', 'alex', 'fred', 'george', 'guy', 'ryan', 'james', 'thomas', 'oliver', 'arthur', 'aaron', 'rishi', 'tom', 'stefan', 'conrad', 'christopher', 'eric', 'brian', 'matthew', 'justin', 'joey', 'william', 'gordon', 'lee', 'richard', 'paul'];
// Pitch used to tell the genders apart when no matching voice is installed.
const FALLBACK_PITCH = { female: 1.35, male: 0.75 };

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

/** Say `text` in a randomly chosen male or female voice, unless muted. */
export function speak(text) {
  if (muted || typeof window === 'undefined' || !window.speechSynthesis) return;
  const gender = Math.random() < 0.5 ? 'female' : 'male';
  const { voice, pitch } = pickVoice(gender);
  const utterance = new SpeechSynthesisUtterance(text);
  if (voice) { utterance.voice = voice; utterance.lang = voice.lang; } else { utterance.lang = 'en-US'; }
  utterance.pitch = pitch;
  utterance.volume = masterVolume;
  window.speechSynthesis.speak(utterance);
}

// Some browsers load the voice list asynchronously; touching it early starts that load.
if (typeof window !== 'undefined' && window.speechSynthesis) {
  try { window.speechSynthesis.getVoices(); } catch (e) {}
}

export function isMuted() { return muted; }

export function getMasterVolume() { return masterVolume; }

export function setMasterVolume(volume) {
  masterVolume = Math.min(1, Math.max(0, Number(volume) || 0));
  try { localStorage.setItem(VOLUME_STORAGE_KEY, String(masterVolume)); } catch (e) {}
  for (const element of liveTracks) element.volume = atmosphereVolume();
}

export function setMuted(nextMuted) {
  muted = !!nextMuted;
  for (const element of liveTracks) element.muted = muted;
  updateMuteButton();
}

function updateMuteButton() {
  if (!muteButton) return;
  muteButton.innerHTML = muted ? '🔇' : '🔊';
  muteButton.title = muted ? 'Unmute' : 'Mute';
}

export function ensureMuteButton() {
  if (muteButton) return;
  const btn = document.createElement('button');
  btn.id = 'muteButton';
  btn.style.cssText = buttonStyle(MUTE_BUTTON_TOP);
  btn.addEventListener('mouseenter', () => {
    btn.style.borderColor = 'rgba(255,255,255,0.6)';
    btn.style.transform = 'scale(1.05)';
  });
  btn.addEventListener('mouseleave', () => {
    btn.style.borderColor = 'rgba(255,255,255,0.3)';
    btn.style.transform = 'scale(1)';
  });
  onActivate(btn, () => {
    setMuted(!muted);
    // The tap is itself a gesture, so it can double as the autoplay unlock.
    if (!muted) startAtmosphere().catch(() => {});
  });
  document.body.appendChild(btn);
  muteButton = btn;
  updateMuteButton();
}
