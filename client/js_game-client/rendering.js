import { Config } from './config.js';
import { State } from './state.js';
import { updateViewport } from './viewport.js';

export function drawOffScreenBallIndicators(offScreenBalls, xScale) {
  const ctx = State.ctx;
  if (!State.viewport.enabled || !State.gameState || !State.localPlayerId) return;
  const triangleSize = Math.max(3, 0.35 * xScale);
  const edgeMargin = Math.max(5, 0.5 * xScale);
  ctx.save();
  for (const ballInfo of offScreenBalls) {
    const ballPos = ballInfo.position;
    const dirX = ballPos.x - State.viewport.centerX;
    const dirY = ballPos.y - State.viewport.centerY;
    if (dirX === 0 && dirY === 0) continue;
    const distance = Math.sqrt(dirX * dirX + dirY * dirY);
    const normalizedX = dirX / distance;
    const normalizedY = dirY / distance;
    let edgeX, edgeY;
    const halfWidth = Config.CANVAS_WIDTH / 2;
    const halfHeight = Config.CANVAS_HEIGHT / 2;
    const timeToVerticalEdge = normalizedX > 0 ? (halfWidth - edgeMargin) / normalizedX : (-halfWidth + edgeMargin) / normalizedX;
    const timeToHorizontalEdge = normalizedY > 0 ? (halfHeight - edgeMargin) / normalizedY : (-halfHeight + edgeMargin) / normalizedY;
    const time = Math.min(Math.abs(timeToVerticalEdge), Math.abs(timeToHorizontalEdge));
    edgeX = halfWidth + normalizedX * time;
    edgeY = halfHeight + normalizedY * time;
    edgeX = Math.max(edgeMargin, Math.min(Config.CANVAS_WIDTH - edgeMargin, edgeX));
    edgeY = Math.max(edgeMargin, Math.min(Config.CANVAS_HEIGHT - edgeMargin, edgeY));
    const angle = Math.atan2(dirY, dirX);
    ctx.fillStyle = ballInfo.color; ctx.strokeStyle = '#ffffff'; ctx.lineWidth = 1; ctx.globalAlpha = ballInfo.isDead ? 0.3 : 0.8;
    ctx.save(); ctx.translate(edgeX, edgeY); ctx.rotate(angle);
    ctx.beginPath(); ctx.moveTo(triangleSize, 0); ctx.lineTo(-triangleSize / 2, -triangleSize / 2); ctx.lineTo(-triangleSize / 2, triangleSize / 2); ctx.closePath();
    ctx.fill(); ctx.stroke(); ctx.restore();
  }
  ctx.restore();
}

export function renderGame() {
  const ctx = State.ctx; const gs = State.gameState;
  if (!ctx) { console.log('No canvas context available'); return; }
  if (!gs) { if (State.debug.enabled) console.log('No game state available'); return; }

  updateViewport();

  let xScale, yScale, offsetX = 0, offsetY = 0;
  if (State.viewport.enabled) {
    xScale = Config.CANVAS_WIDTH / State.viewport.worldWidth;
    yScale = Config.CANVAS_HEIGHT / State.viewport.worldHeight;
    offsetX = State.viewport.offsetX; offsetY = State.viewport.offsetY;
  } else { xScale = Config.CANVAS_WIDTH / Config.PITCH_LENGTH; yScale = Config.CANVAS_HEIGHT / Config.PITCH_WIDTH; }

  function worldToScreen(x, y) { return { x: x * xScale + offsetX, y: y * yScale + offsetY }; }
  function isVisible(x, y, m = 2) {
    if (!State.viewport.enabled) return true;
    const s = worldToScreen(x, y);
    return s.x >= -m && s.x <= Config.CANVAS_WIDTH + m && s.y >= -m && s.y <= Config.CANVAS_HEIGHT + m;
  }

  ctx.fillStyle = '#228b22'; ctx.fillRect(0, 0, Config.CANVAS_WIDTH, Config.CANVAS_HEIGHT);

  const lineThickness = Math.max(1, xScale / 15); ctx.lineWidth = lineThickness; ctx.strokeStyle = '#000000';

  let centerX, keeperAX, keeperBX;
  const centerScreen = worldToScreen(Config.PITCH_LENGTH / 2, 0);
  const keeperAScreen = worldToScreen(Config.KEEPER_ZONE_X, 0);
  const keeperBScreen = worldToScreen(Config.PITCH_LENGTH - Config.KEEPER_ZONE_X, 0);
  centerX = centerScreen.x; keeperAX = keeperAScreen.x; keeperBX = keeperBScreen.x;
  if (centerX >= 0 && centerX <= Config.CANVAS_WIDTH) { ctx.beginPath(); ctx.moveTo(centerX, 0); ctx.lineTo(centerX, Config.CANVAS_HEIGHT); ctx.stroke(); }
  if (keeperAX >= 0 && keeperAX <= Config.CANVAS_WIDTH) { ctx.beginPath(); ctx.moveTo(keeperAX, 0); ctx.lineTo(keeperAX, Config.CANVAS_HEIGHT); ctx.stroke(); }
  if (keeperBX >= 0 && keeperBX <= Config.CANVAS_WIDTH) { ctx.beginPath(); ctx.moveTo(keeperBX, 0); ctx.lineTo(keeperBX, Config.CANVAS_HEIGHT); ctx.stroke(); }

  ctx.strokeStyle = '#641111ff'; ctx.lineWidth = 4 * lineThickness;
  if (State.viewport.enabled) {
    const topLeft = worldToScreen(0, 0); const bottomRight = worldToScreen(Config.PITCH_LENGTH, Config.PITCH_WIDTH);
    ctx.beginPath(); ctx.rect(topLeft.x, topLeft.y, bottomRight.x - topLeft.x, bottomRight.y - topLeft.y); ctx.stroke();
  } else { ctx.beginPath(); ctx.rect(0, 0, Config.CANVAS_WIDTH, Config.CANVAS_HEIGHT); ctx.stroke(); }

  const colour_player_A = '#6464ff';
  const colour_player_B = '#ff7f00';
  const colour_keeper = '#7cfc00';
  const colour_chaser = '#ffffff';
  const colour_beater = '#000000';
  const colour_seeker = '#ffff00';
  const colour_quaffle = '#ebb0b7';
  const colour_bludger = '#ff0000';
  const colour_selected_player = '#ffff00';
  const knocked_out_alpha = 0.5; const is_dead_alpha = 0.5;

  if (gs.hoops) {
    const colour_hoop_A = '#14c896'; const colour_hoop_B = '#00ff32';
    for (const hoop of Object.values(gs.hoops)) {
      const hp = hoop.position || hoop.pos || hoop;
      if (!isVisible(hp.x, hp.y)) continue;
      const hs = worldToScreen(hp.x, hp.y); const hx = hs.x, hy = hs.y;
      const hoopThicknessM = (hoop.thickness !== undefined) ? hoop.thickness : 0.1;
      const hoopRadiusM = (hoop.radius !== undefined) ? hoop.radius : (Config.HOOP_RADIUS / 2);
      const thicknessPx = hoopThicknessM * xScale; const heightPx = hoopRadiusM * 2 * xScale;
      ctx.fillStyle = (hoop.team === 'A' || hoop.team === 0) ? colour_hoop_A : colour_hoop_B;
      ctx.fillRect(hx - 0.5 * thicknessPx, hy - 0.5 * heightPx, thicknessPx, heightPx);
    }
  }

  if (gs.players) {
    for (const player of Object.values(gs.players)) {
      const pos = player.position || player.pos || player;
      const margin = (player.id === State.localPlayerId) ? 10 : 2;
      if (!isVisible(pos.x, pos.y, margin)) continue;
      const ps = worldToScreen(pos.x, pos.y); const px = ps.x, py = ps.y;
      const boxW = Config.PLAYER_RADIUS * xScale; const boxH = Config.PLAYER_RADIUS * yScale;
      const team = (player.team === 'A' || player.team === 0 || player.team === '0') ? 'A' : 'B';
      const colour = team === 'A' ? colour_player_A : colour_player_B; let sizePx = Config.PLAYER_RADIUS * xScale;
      ctx.fillStyle = colour; ctx.save(); if (player.is_knocked_out) ctx.globalAlpha = knocked_out_alpha; else ctx.globalAlpha = 1.0;
      ctx.beginPath(); ctx.arc(px, py, Math.max(2, sizePx), 0, Math.PI * 2); ctx.fill(); ctx.restore();

      const headbandW = 0.4 * Config.PLAYER_RADIUS * xScale; const headbandH = 1.25 * Config.PLAYER_RADIUS * yScale;
      const vel = player.velocity || player.vel || player.v || { x: 0, y: -1 };
      const velMag = Math.hypot(vel.x * xScale || 0, vel.y * yScale || 0);
      const angle = velMag > 1e-3 ? Math.atan2(vel.y * yScale, vel.x * xScale) : 0;
      ctx.save(); ctx.translate(px, py); ctx.rotate(angle);
      let hbColor = colour_chaser;
      if (player.role === 'keeper' || player.role === 'KEEPER') hbColor = colour_keeper;
      else if (player.role === 'chaser' || player.role === 'CHASER') hbColor = colour_chaser;
      else if (player.role === 'beater' || player.role === 'BEATER') hbColor = colour_beater;
      else if (player.role === 'seeker' || player.role === 'SEEKER') hbColor = colour_seeker;
      ctx.fillStyle = hbColor; if (player.is_knocked_out) ctx.globalAlpha = knocked_out_alpha; else ctx.globalAlpha = 1.0;
      ctx.fillRect(-0.01 * headbandW, -0.5 * headbandH, Math.max(0.5, headbandW), Math.max(1, headbandH)); ctx.restore();

      if (player.id === State.localPlayerId) {
        const lw = 0.15 * Config.PLAYER_RADIUS * xScale; ctx.save(); ctx.strokeStyle = colour_selected_player; ctx.lineWidth = lw;
        ctx.beginPath(); ctx.arc(px, py, Math.max(2, sizePx + lw), 0, Math.PI * 2); ctx.stroke(); ctx.restore();
        if (player.has_ball) {
          const dirX = player.direction.x; const dirY = player.direction.y; const dm = Math.sqrt(dirX * dirX + dirY * dirY);
          if (dm > 0.001) {
            const ndx = dirX / dm; const ndy = dirY / dm; const maxD = Math.max(Config.CANVAS_WIDTH, Config.CANVAS_HEIGHT);
            let ballX = px, ballY = py;
            if (gs.balls) {
              for (const ball of Object.values(gs.balls)) {
                if (ball.holder_id === player.id) { const bp = ball.position || ball.pos || ball; const bs = worldToScreen(bp.x, bp.y); ballX = bs.x; ballY = bs.y; break; }
              }
            }
            const startX = ballX, startY = ballY; const endX = ballX + maxD * ndx; const endY = ballY + maxD * ndy;
            ctx.save(); ctx.strokeStyle = '#ffffff'; ctx.globalAlpha = 0.3; ctx.lineWidth = lineThickness; ctx.setLineDash([lineThickness * 4, lineThickness * 4]);
            ctx.beginPath(); ctx.moveTo(startX, startY); ctx.lineTo(endX, endY); ctx.stroke(); ctx.restore();
          }
        }
      }
    }
  }

  const offScreenBalls = [];
  if (gs.balls) {
    for (const ball of Object.values(gs.balls)) {
      const bpos = ball.position || ball.pos || ball;
      if (!isVisible(bpos.x, bpos.y)) {
        if (State.viewport.enabled) {
          let color = colour_quaffle;
          if (ball.ball_type === 'dodgeball' || ball.ball_type === 'DODGEBALL' || ball.ball_type === 'bludger') color = colour_bludger;
          else if (ball.ball_type === 'volleyball' || ball.ball_type === 'VOLLEYBALL' || ball.ball_type === 'quaffle') color = colour_quaffle;
          offScreenBalls.push({ position: bpos, color, isDead: ball.is_dead });
        }
        continue;
      }
      const bs = worldToScreen(bpos.x, bpos.y); const bx = bs.x, by = bs.y;
      let color = colour_quaffle; let sizePx = xScale * 0.3;
      if (ball.ball_type === 'dodgeball' || ball.ball_type === 'DODGEBALL' || ball.ball_type === 'bludger') { color = colour_bludger; sizePx = Config.DODGEBALL_RADIUS * xScale; }
      else if (ball.ball_type === 'volleyball' || ball.ball_type === 'VOLLEYBALL' || ball.ball_type === 'quaffle') { color = colour_quaffle; sizePx = Config.VOLLEYBALL_RADIUS * xScale; }
      ctx.fillStyle = color; ctx.save(); if (ball.is_dead) { ctx.globalAlpha = is_dead_alpha; } else { ctx.globalAlpha = 1.0; }
      ctx.beginPath(); ctx.arc(bx, by, Math.max(1, sizePx), 0, Math.PI * 2); ctx.fill(); ctx.restore();

      // render delay-of-game indicator near volleyball when bin > 0
      const delayBin = (State.gameState && State.gameState.delay_bin !== undefined) ? State.gameState.delay_bin : 0;
      const possessionCode = (State.gameState && State.gameState.possession_code !== undefined) ? State.gameState.possession_code : 0;
      const isVolley = (ball.ball_type === 'volleyball' || ball.ball_type === 'VOLLEYBALL' || ball.ball_type === 'quaffle');
      if (isVolley && delayBin > 0) {
        const indicatorRadius = Math.max(3, Config.VOLLEYBALL_RADIUS * xScale * 5);
        const baseOffsetX = Math.max(6, Config.VOLLEYBALL_RADIUS * xScale * 10);
        // positive offset if team_0 (possession_code=1), negative if team_1 (possession_code=2)
        const offsetDirection = (possessionCode === 1) ? 1 : -1;
        // const offsetX = (possessionCode === 2) ? -baseOffsetX : baseOffsetX;
        const offsetX = offsetDirection * baseOffsetX;
        // draw arrow from volleyball through clock indicator center
        try {
          // line from ball to clock edge
          const dx1 = offsetX - offsetDirection * indicatorRadius; const dy1 = 0;
          const startX1 = bx;
          const startY1 = by;
          const endX1 = bx + dx1;
          const endY1 = by;
          ctx.save();
          ctx.globalAlpha = 0.6;
          ctx.strokeStyle = '#ffffff';
          ctx.lineWidth = Math.max(1, 2 * lineThickness);
          ctx.beginPath();
          ctx.moveTo(startX1, startY1);
          ctx.lineTo(endX1, endY1);
          ctx.stroke();
          // line from clock edge to arrow head
          const dx2 = 2 * offsetX; const dy2 = 0;
          const startX2 = bx + offsetX + offsetDirection * indicatorRadius;
          const startY2 = by;
          const endX2 = bx + dx2;
          const endY2 = by;
          const angle = Math.atan2(dy2, dx2);
          const arrowHead = Math.max(3, 0.8 * indicatorRadius);
          ctx.beginPath();
          ctx.moveTo(startX2, startY2);
          ctx.lineTo(endX2, endY2);
          ctx.stroke();
          // arrow head
          ctx.translate(endX2 + offsetDirection * arrowHead, endY2);
          ctx.rotate(angle);
          ctx.fillStyle = '#ffffff';
          ctx.beginPath();
          ctx.moveTo(0, 0);
          ctx.lineTo(-arrowHead, arrowHead * 0.5);
          ctx.lineTo(-arrowHead, -arrowHead * 0.5);
          ctx.closePath();
          ctx.fill();
          ctx.restore();
        } catch (e) {console.log('Error drawing delay-of-game arrow:', e); }
        const endAngle = (Math.PI * 2) * (Math.min(7, delayBin) / 8);
        const startAngle = -Math.PI / 2;
        const fillAngle = startAngle + endAngle;
        const cx = bx + offsetX;
        const cy = by;
        // draw faint circle outline of the clock
        ctx.save();
        ctx.globalAlpha = 0.6;
        ctx.strokeStyle = '#ffffff';
        ctx.lineWidth = Math.max(1, indicatorRadius * 0.1);
        ctx.beginPath();
        ctx.arc(cx, cy, indicatorRadius, 0, Math.PI * 2);
        ctx.stroke();
        ctx.restore();

        // draw filled wedge corresponding to the delay bin in the clock
        ctx.save();
        ctx.globalAlpha = 0.7;
        ctx.fillStyle = '#808080';
        ctx.beginPath();
        ctx.moveTo(cx, cy);
        ctx.arc(cx, cy, indicatorRadius, startAngle, fillAngle, false);
        ctx.closePath();
        ctx.fill();
        ctx.restore();

        // draw clock quarter marks
        for (let i = 0; i < 8; i++) {
          const angle = startAngle + (i * Math.PI / 4);
          const innerRadius = indicatorRadius * 0.75;
          const outerRadius = indicatorRadius;
          const x1 = cx + innerRadius * Math.cos(angle);
          const y1 = cy + innerRadius * Math.sin(angle);
          const x2 = cx + outerRadius * Math.cos(angle);
          const y2 = cy + outerRadius * Math.sin(angle);
          ctx.save();
          ctx.globalAlpha = 0.6;
          ctx.strokeStyle = '#ffffff';
          ctx.lineWidth = Math.max(1, indicatorRadius * 0.1);
          ctx.beginPath();
          ctx.moveTo(x1, y1);
          ctx.lineTo(x2, y2);
          ctx.stroke();
          ctx.restore();
        }
      }
    }
  }

  if (gs.score) { document.getElementById('score0').textContent = gs.score[0] || 0; document.getElementById('score1').textContent = gs.score[1] || 0; }
  if (gs.game_time !== undefined) {
    const total = Math.floor(gs.game_time); const m = Math.floor(total / 60); const s = total % 60; document.getElementById('gameTime').textContent = `${m}:${s.toString().padStart(2, '0')}`;
  }

  if (State.viewport.enabled && offScreenBalls.length > 0) drawOffScreenBallIndicators(offScreenBalls, xScale);

  if (State.isTouchDevice && (State.joystick.active || State.joystick.opacity > 0)) {
    ctx.save(); ctx.globalAlpha = State.joystick.opacity;
    ctx.strokeStyle = '#ffffff'; ctx.fillStyle = 'rgba(255,255,255,0.1)'; ctx.lineWidth = 2;
    ctx.beginPath(); ctx.arc(State.joystick.centerX, State.joystick.centerY, State.joystick.baseRadius, 0, Math.PI * 2); ctx.fill(); ctx.stroke();
    ctx.fillStyle = 'rgba(255,255,255,0.8)'; ctx.beginPath(); ctx.arc(State.joystick.currentX, State.joystick.currentY, State.joystick.knobRadius, 0, Math.PI * 2); ctx.fill();
    ctx.restore();
  }
}