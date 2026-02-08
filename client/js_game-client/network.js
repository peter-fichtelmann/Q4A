import { Config } from './config.js';
import { State } from './state.js';
import { getQueryParam } from './utils.js';
import { resizeCanvasToFit } from './viewport.js';
import { showPrompt } from './fullscreen.js';

export function connectGame() {
  State.roomId = getQueryParam('room');
  State.localPlayerId = getQueryParam('player');
  if (!State.roomId || !State.localPlayerId) { window.location.href = '/'; return; }
  const protocol = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  State.gameSocket = new WebSocket(`${protocol}//${window.location.host}/ws/game/${State.roomId}/${State.localPlayerId}`);
  State.gameSocket.binaryType = 'arraybuffer';
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
    }
    try { resizeCanvasToFit(); } catch (e) {}
    showPrompt();
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
      if (incoming.game_time !== undefined) State.gameState.game_time = incoming.game_time;
      if (incoming.score !== undefined) State.gameState.score = incoming.score;
      if (incoming.delay_bin !== undefined) State.gameState.delay_bin = incoming.delay_bin;
      if (incoming.possession_code !== undefined) State.gameState.possession_code = incoming.possession_code;
    }
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

export function sendThrow() {
  const sock = State.gameSocket;
  if (sock && sock.readyState === WebSocket.OPEN) {
    sock.send(JSON.stringify({ type: 'throw' }));
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
    if (version !== 1 && version !== 2 && version !== 3) { console.warn('Unknown binary state version', version); return null; }
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
      let id = (State.playersOrder && State.playersOrder[i]) ? State.playersOrder[i] : `p_${i}`;
      players[id] = { id, position: { x, y }, velocity: { x: vx, y: vy }, is_knocked_out, has_ball };
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
    if (version === 2) {
      delay_bin = dv.getUint8(off, true); off += 1;
      possession_code = dv.getUint8(off, true); off += 1;
    }
    return { players, balls, game_time: gameTime, score, delay_bin, possession_code };
  } catch (err) { console.warn('Failed to parse binary state', err); return null; }
}

export function returnToLobby() {
  if (State.gameSocket) State.gameSocket.close();
  window.location.href = '/';
}