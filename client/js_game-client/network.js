import { Config } from './config.js';
import { State } from './state.js';
import { getQueryParam } from './utils.js';
import { resizeCanvasToFit } from './viewport.js';
import { showPrompt } from './fullscreen.js';
import { ensureButtons, showForbidden } from './player_switch.js';
import { ensureClaimButton, updateClaimButton } from './claim.js';
import * as Audio from './audio.js';
import { ensureSettingsButton, applyPauseState, sendThrowAssist } from './settings.js';
import { handlePenaltyTurnover, handleInbounding } from './penalty_announcements.js';

function getNowMs() {
  return (typeof performance !== 'undefined' && performance.now) ? performance.now() : Date.now();
}

function rememberServerUpdateTime() {
  State.network.lastUpdateAtMs = getNowMs();
}

function mergeBallVelocityFallbacks(gameState, ballVelocities) {
  if (!gameState || !gameState.balls || !ballVelocities) return;
  for (const [ballId, velocity] of Object.entries(ballVelocities)) {
    const ball = gameState.balls[ballId];
    if (!ball) continue;
    if (!ball.velocity || ball.velocity.x === undefined || ball.velocity.y === undefined) {
      ball.velocity = {
        x: Number(velocity?.x) || 0,
        y: Number(velocity?.y) || 0,
      };
    }
  }
}

function cacheBallVelocities(gameState) {
  if (!gameState || !gameState.balls) return;
  State.ballVelocities = State.ballVelocities || {};
  for (const [ballId, ball] of Object.entries(gameState.balls)) {
    if (ball && ball.velocity && ball.velocity.x !== undefined && ball.velocity.y !== undefined) {
      State.ballVelocities[ballId] = {
        x: Number(ball.velocity.x) || 0,
        y: Number(ball.velocity.y) || 0,
      };
    }
  }
}

export function connectGame() {
  State.roomId = getQueryParam('room');
  State.connectionPlayerId = getQueryParam('player');
  // Starts as our own player; the server tells us when a switch moves it.
  State.localPlayerId = State.connectionPlayerId;
  if (!State.roomId || !State.connectionPlayerId) { window.location.href = '/'; return; }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  State.gameSocket = new WebSocket(`${protocol}//${window.location.host}/ws/game/${State.roomId}/${State.connectionPlayerId}`);
  State.gameSocket.binaryType = 'arraybuffer';
  State.gameSocket.onopen = () => { sendThrowAssist(); };
  State.gameSocket.onmessage = (event) => {
    try {
      if (event.data instanceof ArrayBuffer) {
        const parsed = parseBinaryState(event.data);
        if (parsed) handleMessage({ type: 'state_update', game_state: parsed });
      } else if (typeof event.data === 'string') {
        const message = JSON.parse(event.data);
        handleMessage(message);
      } else if (event.data instanceof Blob) {
        const reader = new FileReader();
        reader.onload = () => {
          const ab = reader.result;
          const parsed = parseBinaryState(ab);
          if (parsed) handleMessage({ type: 'state_update', game_state: parsed });
        };
        reader.readAsArrayBuffer(event.data);
      }
    } catch (err) {
      console.warn('Error handling websocket message', err);
    }
  };
  State.gameSocket.onerror = (error) => { console.error('Game WebSocket error:', error); };
  State.gameSocket.onclose = () => { console.log('Game connection closed'); };
}

export function handleMessage(message) {
  if (message.type === 'initial_state') {
    State.gameState = message.game_state;
    if (message.players_order) State.playersOrder = message.players_order;
    if (message.balls_order) State.ballsOrder = message.balls_order;
    if (message.tick_time_seconds !== undefined) {
      State.network.tickSeconds = Number(message.tick_time_seconds) || 0;
    }
    if (message.ball_velocities) {
      State.ballVelocities = message.ball_velocities;
      mergeBallVelocityFallbacks(State.gameState, State.ballVelocities);
    } else {
      cacheBallVelocities(State.gameState);
    }
    if (message.config) {
      const cfg = message.config;
      if (cfg.pitch_length !== undefined) Config.PITCH_LENGTH = cfg.pitch_length;
      if (cfg.pitch_width !== undefined) Config.PITCH_WIDTH = cfg.pitch_width;
      if (cfg.keeper_zone_x !== undefined) Config.KEEPER_ZONE_X = cfg.keeper_zone_x;
      if (cfg.hoop_radius !== undefined) Config.HOOP_RADIUS = cfg.hoop_radius;
      if (cfg.hoop_thickness !== undefined) Config.HOOP_THICKNESS = cfg.hoop_thickness;
      if (cfg.player_radius !== undefined) Config.PLAYER_RADIUS = cfg.player_radius;
      if (cfg.volleyball_radius !== undefined) Config.VOLLEYBALL_RADIUS = cfg.volleyball_radius;
      if (cfg.dodgeball_radius !== undefined) Config.DODGEBALL_RADIUS = cfg.dodgeball_radius;
      if (cfg.flag_runner_radius !== undefined) Config.FLAG_RUNNER_RADIUS = cfg.flag_runner_radius;
      if (cfg.game_time_to_real_time_ratio !== undefined) Config.GAME_TIME_TO_REAL_TIME_RATIO = cfg.game_time_to_real_time_ratio;
    }
    // Null for a spectator, who steers nobody.
    State.localPlayerId = message.controlled_player_id || null;
    State.isTutorial = !!message.is_tutorial;
    if (message.throw_charge_full_ticks) State.throwCharge.fullTicks = message.throw_charge_full_ticks;
    if (Array.isArray(message.team_names)) State.teamNames = message.team_names;
    State.humanNames = message.human_names || {};
    rememberServerUpdateTime();
    try { resizeCanvasToFit(); } catch (e) {}
    showPrompt();
    ensureButtons();
    ensureClaimButton();
    Audio.ensureMuteButton();
    ensureSettingsButton();
    if (message.paused) applyPauseState(message.paused);
    // Baseline only, so joining a running game does not replay its goals.
    Audio.noteScore(State.gameState && State.gameState.score);
    Audio.noteKnockouts(State.gameState && State.gameState.players);
  } else if (message.type === 'penalty_turnover') {
    Audio.notePenaltyTurnover(message.rule);
    handlePenaltyTurnover(message);
  } else if (message.type === 'inbounding') {
    handleInbounding(message);
  } else if (message.type === 'team_names') {
    if (Array.isArray(message.team_names)) State.teamNames = message.team_names;
  } else if (message.type === 'game_paused') {
    applyPauseState(message);
  } else if (message.type === 'human_names') {
    State.humanNames = message.human_names || {};
  } else if (message.type === 'controlled_player') {
    State.localPlayerId = message.controlled_player_id || null;
  } else if (message.type === 'switch_player_failed') {
    showForbidden(message.mode, message.reason);
  } else if (message.type === 'state_update') {
    State.debug.stateUpdateCounter += 1;
    const incoming = message.game_state || {};
    if (!State.gameState) {
      State.gameState = incoming;
    } else {
      if (incoming.players) {
        State.gameState.players = State.gameState.players || {};
        for (const [id, pdata] of Object.entries(incoming.players)) {
          const existing = State.gameState.players[id] || {};
          existing.position = pdata.position || existing.position;
          existing.velocity = pdata.velocity || existing.velocity;
          if (pdata.is_knocked_out !== undefined) existing.is_knocked_out = pdata.is_knocked_out;
          if (pdata.has_ball !== undefined) existing.has_ball = pdata.has_ball;
          if (pdata.dodgeball_immunity !== undefined) existing.dodgeball_immunity = pdata.dodgeball_immunity;
          if (pdata.is_claiming !== undefined) existing.is_claiming = pdata.is_claiming;
          existing.id = id;
          if (!existing.direction) existing.direction = { x: 0, y: 0 };
          State.gameState.players[id] = existing;
        }
      }
      if (incoming.balls) {
        State.gameState.balls = State.gameState.balls || {};
        for (const [id, bdata] of Object.entries(incoming.balls)) {
          const existing = State.gameState.balls[id] || {};
          existing.position = bdata.position || existing.position;
          existing.velocity = bdata.velocity || existing.velocity;
          if (bdata.holder_id !== undefined) existing.holder_id = bdata.holder_id;
          if (bdata.possession_team !== undefined) existing.possession_team = bdata.possession_team;
          existing.id = id;
          if (bdata.is_dead !== undefined) existing.is_dead = bdata.is_dead;
          State.gameState.balls[id] = existing;
        }
      }
      if (incoming.ball_velocities) {
        State.ballVelocities = { ...State.ballVelocities, ...incoming.ball_velocities };
      }
      mergeBallVelocityFallbacks(State.gameState, State.ballVelocities);
      cacheBallVelocities(State.gameState);
      if (incoming.flag_runner) {
        // keep the static attributes (e.g. radius) received with the initial state
        const existingFlagRunner = State.gameState.flag_runner || {};
        existingFlagRunner.position = incoming.flag_runner.position || existingFlagRunner.position;
        existingFlagRunner.velocity = incoming.flag_runner.velocity || existingFlagRunner.velocity;
        State.gameState.flag_runner = existingFlagRunner;
      }
      if (incoming.flag_runner_on_pitch !== undefined) State.gameState.flag_runner_on_pitch = incoming.flag_runner_on_pitch;
      if (incoming.seeker_on_pitch !== undefined) State.gameState.seeker_on_pitch = incoming.seeker_on_pitch;
      if (incoming.game_time !== undefined) State.gameState.game_time = incoming.game_time;
      if (incoming.score !== undefined) State.gameState.score = incoming.score;
      if (incoming.delay_bin !== undefined) State.gameState.delay_bin = incoming.delay_bin;
      if (incoming.possession_code !== undefined) State.gameState.possession_code = incoming.possession_code;
      if (incoming.is_game_live !== undefined) State.gameState.is_game_live = incoming.is_game_live;
      if (incoming.is_game_over !== undefined) State.gameState.is_game_over = incoming.is_game_over;
      if (incoming.is_overtime !== undefined) State.gameState.is_overtime = incoming.is_overtime;
      if (incoming.flag_catched_team !== undefined) State.gameState.flag_catched_team = incoming.flag_catched_team;
      if (incoming.flag_catch_continue_timer !== undefined) State.gameState.flag_catch_continue_timer = incoming.flag_catch_continue_timer;
      if (incoming.set_score !== undefined) State.gameState.set_score = incoming.set_score;
      if (incoming.third_dodgeball_team !== undefined) State.gameState.third_dodgeball_team = incoming.third_dodgeball_team;
      if (incoming.stalled_countdown !== undefined) State.gameState.stalled_countdown = incoming.stalled_countdown;
      if (incoming.third_dodgeball_id !== undefined) State.gameState.third_dodgeball_id = incoming.third_dodgeball_id;
    }
    // Which player we steer is sent as an index into playersOrder on every update
    // (255 = none), so a switch needs no extra message and cannot get out of sync.
    if (incoming.controlled_index !== undefined && State.playersOrder) {
      State.localPlayerId = incoming.controlled_index === 255
        ? null
        : (State.playersOrder[incoming.controlled_index] || State.localPlayerId);
    }
    if (incoming.throw_charge_ticks !== undefined) {
      const charge = State.throwCharge;
      if (charge.ticks > 0 && incoming.throw_charge_ticks === 0) {
        // the charge ended (thrown): keep showing its bars for a while
        charge.endedTicks = charge.ticks;
        charge.endedAt = performance.now();
      }
      charge.ticks = incoming.throw_charge_ticks;
    }
    // Right after the merge, before the hooks below: if one of them throws, a stale
    // time would make the renderer extrapolate the fresh positions further and further.
    rememberServerUpdateTime();
    // Cheers for a quaffle goal and for a caught flag runner; both show up here
    // as a score increase.
    Audio.noteScore(State.gameState && State.gameState.score);
    // Crowd swell for a beat, which shows up here as a new knockout.
    Audio.noteKnockouts(State.gameState && State.gameState.players);
    updateClaimButton();
  }
}

export function sendPlayerInput(dirX, dirY) {
  const sock = State.gameSocket;
  if (sock && sock.readyState === WebSocket.OPEN) {
    function floatToHalf(v) {
      const f32 = new Float32Array(1);
      const u32 = new Uint32Array(f32.buffer);
      f32[0] = v;
      const x = u32[0];
      const sign = (x >> 16) & 0x8000;
      const mantissa = x & 0x007fffff;
      let exp = (x >> 23) & 0xff;
      if (exp === 255) { if (mantissa !== 0) return sign | 0x7e00; return sign | 0x7c00; }
      exp = exp - 127 + 15;
      if (exp >= 31) return sign | 0x7c00;
      if (exp <= 0) { if (exp < -10) return sign; const m = (mantissa | 0x00800000) >> (1 - exp); return sign | (m >> 13); }
      return sign | (exp << 10) | (mantissa >> 13);
    }
    const buf = new ArrayBuffer(4);
    const dv = new DataView(buf);
    dv.setUint16(0, floatToHalf(Number(dirX) || 0), true);
    dv.setUint16(2, floatToHalf(Number(dirY) || 0), true);
    sock.send(buf);
  }
}

// The throw action is held to charge the throw: throw_start when pressed (also tackles), throw_end when
// let go. The server throws on throw_end, or by itself once the charge is full.
export function sendThrowStart() {
  if (State.throwCharge.pressed) return;
  State.throwCharge.pressed = true;
  const sock = State.gameSocket;
  if (sock && sock.readyState === WebSocket.OPEN) {
    sock.send(JSON.stringify({ type: 'throw_start' }));
  }
}

export function sendThrowEnd() {
  if (!State.throwCharge.pressed) return;
  State.throwCharge.pressed = false;
  const sock = State.gameSocket;
  if (sock && sock.readyState === WebSocket.OPEN) {
    sock.send(JSON.stringify({ type: 'throw_end' }));
  }
}

export function parseBinaryState(arrayBuffer) {
  function halfToFloat(h) {
    const s = (h & 0x8000) >>> 15;
    const e = (h & 0x7C00) >>> 10;
    const f = h & 0x03FF;
    if (e === 0) { if (f === 0) return s ? -0 : 0; return (s ? -1 : 1) * Math.pow(2, -14) * (f / 1024); }
    if (e === 31) { if (f === 0) return s ? -Infinity : Infinity; return NaN; }
    return (s ? -1 : 1) * Math.pow(2, e - 15) * (1 + f / 1024);
  }
  try {
    const dv = new DataView(arrayBuffer);
    let off = 0;
    const version = dv.getUint8(off, true); off += 1;
    if (version < 1 || version > 9) { console.warn('Unknown binary state version', version); return null; }
    const playerCount = dv.getUint8(off, true); off += 1;
    const ballCount = dv.getUint8(off, true); off += 1;
    const gameTimeHalf = dv.getUint16(off, true); off += 2;
    const gameTime = halfToFloat(gameTimeHalf);
    const score0 = dv.getUint8(off, true); off += 1;
    const score1 = dv.getUint8(off, true); off += 1;
    const score = [score0, score1];

    const players = {};
    for (let i = 0; i < playerCount; i++) {
      const xh = dv.getUint16(off, true); off += 2;
      const yh = dv.getUint16(off, true); off += 2;
      const vxh = dv.getUint16(off, true); off += 2;
      const vyh = dv.getUint16(off, true); off += 2;
      const x = halfToFloat(xh);
      const y = halfToFloat(yh);
      const vx = halfToFloat(vxh);
      const vy = halfToFloat(vyh);
      const flags = dv.getUint8(off, true); off += 1;
      const is_knocked_out = !!(flags & 1);
      const has_ball = !!(flags & 2);
      const dodgeball_immunity = !!(flags & 4);
      const is_claiming = !!(flags & 8);
      let id = (State.playersOrder && State.playersOrder[i]) ? State.playersOrder[i] : `p_${i}`;
      players[id] = { id, position: { x, y }, velocity: { x: vx, y: vy }, is_knocked_out, has_ball, dodgeball_immunity, is_claiming };
    }

    const balls = {};
    for (let i = 0; i < ballCount; i++) {
      const xh = dv.getUint16(off, true); off += 2;
      const yh = dv.getUint16(off, true); off += 2;
      const vxh = dv.getUint16(off, true); off += 2;
      const vyh = dv.getUint16(off, true); off += 2;
      const x = halfToFloat(xh);
      const y = halfToFloat(yh);
      const vx = halfToFloat(vxh);
      const vy = halfToFloat(vyh);
      const holder_flag = dv.getUint8(off, true); off += 1;
      const is_dead_flag = dv.getUint8(off, true); off += 1;
      let possession_team = null;
      if (version >= 3) {
        const poss_code = dv.getUint8(off, true); off += 1;
        if (poss_code === 1) possession_team = 'team_0';
        else if (poss_code === 2) possession_team = 'team_1';
        else possession_team = null;
      }
      let id = (State.ballsOrder && State.ballsOrder[i]) ? State.ballsOrder[i] : `b_${i}`;
      balls[id] = { id, position: { x, y }, velocity: { x: vx, y: vy }, holder_id: holder_flag ? true : null, is_dead: is_dead_flag ? true : null, possession_team };
    }
    let delay_bin;
    let possession_code = 0;
    if (version >= 2) {
      delay_bin = dv.getUint8(off, true); off += 1;
      possession_code = dv.getUint8(off, true); off += 1;
    }
    let flag_runner_on_pitch = false;
    let seeker_on_pitch = false;
    let flag_runner = null;
    if (version >= 4) {
      const phaseFlags = dv.getUint8(off, true); off += 1;
      flag_runner_on_pitch = !!(phaseFlags & 1);
      seeker_on_pitch = !!(phaseFlags & 2);
      const frxh = dv.getUint16(off, true); off += 2;
      const fryh = dv.getUint16(off, true); off += 2;
      const frvxh = dv.getUint16(off, true); off += 2;
      const frvyh = dv.getUint16(off, true); off += 2;
      flag_runner = {
        position: { x: halfToFloat(frxh), y: halfToFloat(fryh) },
        velocity: { x: halfToFloat(frvxh), y: halfToFloat(frvyh) },
      };
    }
    // Flag catch block: drives the catch-review popup, the game over box and the
    // star the catching team's score carries from then on.
    let is_game_live = true;
    let is_game_over = false;
    let is_overtime = false;
    let flag_catched_team = null;
    let flag_catch_continue_timer = 0;
    let set_score = null;
    if (version >= 6) {
      const matchFlags = dv.getUint8(off, true); off += 1;
      is_game_live = !!(matchFlags & 1);
      is_game_over = !!(matchFlags & 2);
      is_overtime = !!(matchFlags & 4);
      const catchedTeamCode = dv.getUint8(off, true); off += 1;
      if (catchedTeamCode === 1) flag_catched_team = 0;
      else if (catchedTeamCode === 2) flag_catched_team = 1;
      flag_catch_continue_timer = halfToFloat(dv.getUint16(off, true)); off += 2;
      const setScoreByte = dv.getUint8(off, true); off += 1;
      if (setScoreByte !== 255) set_score = setScoreByte;
    }
    // Third dodgeball team (null = no third dodgeball): drives the claim button.
    let third_dodgeball_team = null;
    let third_dodgeball_id = null;
    if (version >= 7) {
      const thirdTeamCode = dv.getUint8(off, true); off += 1;
      if (thirdTeamCode === 1) third_dodgeball_team = 0;
      else if (thirdTeamCode === 2) third_dodgeball_team = 1;
      // Which ball is the third dodgeball (255 = none): target of the claim line.
      const thirdIndex = dv.getUint8(off, true); off += 1;
      if (thirdIndex !== 255) third_dodgeball_id = (State.ballsOrder && State.ballsOrder[thirdIndex]) || `b_${thirdIndex}`;
    }
    // Stalled volleyball countdown (0 = none): whole game seconds before the turnover.
    let stalled_countdown = 0;
    if (version >= 8) {
      stalled_countdown = dv.getUint8(off, true); off += 1;
    }
    // Trailing per-client byte: index of the player this client controls (255 = none).
    let controlled_index;
    if (version >= 5 && off < dv.byteLength) {
      controlled_index = dv.getUint8(off, true); off += 1;
    }
    // Second per-client byte: ticks charged of the steered player's throw (0 = not charging).
    let throw_charge_ticks;
    if (version >= 9 && off < dv.byteLength) {
      throw_charge_ticks = dv.getUint8(off, true); off += 1;
    }
    return {
      players, balls, game_time: gameTime, score, delay_bin, possession_code,
      flag_runner, flag_runner_on_pitch, seeker_on_pitch,
      is_game_live, is_game_over, is_overtime, flag_catched_team,
      flag_catch_continue_timer, set_score, third_dodgeball_team, third_dodgeball_id, stalled_countdown, controlled_index, throw_charge_ticks,
    };
  } catch (err) { console.warn('Failed to parse binary state', err); return null; }
}

export function returnToLobby() {
  if (State.gameSocket) State.gameSocket.close();
  window.location.href = '/';
}