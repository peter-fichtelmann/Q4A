// Anchor resolvers for the game page: convert world coordinates (meters) to
// viewport pixel rects using the same transform as the game renderer.
// All functions return null when the required state is unavailable.

function GC() {
    return window.GameClient || null;
}

export function gameReady() {
    const gc = GC();
    return Boolean(gc && gc.State && gc.State.gameState && gc.State.canvas);
}

function transform() {
    const { Config, State } = GC();
    let xScale, yScale, offsetX = 0, offsetY = 0;
    if (State.viewport.enabled) {
        xScale = Config.CANVAS_WIDTH / State.viewport.worldWidth;
        yScale = Config.CANVAS_HEIGHT / State.viewport.worldHeight;
        offsetX = State.viewport.offsetX;
        offsetY = State.viewport.offsetY;
    } else {
        xScale = Config.CANVAS_WIDTH / Config.PITCH_LENGTH;
        yScale = Config.CANVAS_HEIGHT / Config.PITCH_WIDTH;
    }
    const rect = State.canvas.getBoundingClientRect();
    return { xScale, yScale, offsetX, offsetY, canvasLeft: rect.left, canvasTop: rect.top };
}

/** Rect around a world point with a radius in meters. */
export function worldRect(wx, wy, radiusMeters = 1) {
    if (!gameReady()) return null;
    const t = transform();
    const x = wx * t.xScale + t.offsetX + t.canvasLeft;
    const y = wy * t.yScale + t.offsetY + t.canvasTop;
    const rx = Math.max(10, radiusMeters * t.xScale);
    const ry = Math.max(10, radiusMeters * t.yScale);
    return { left: x - rx, top: y - ry, width: rx * 2, height: ry * 2 };
}

/** Rect spanning a world-coordinate box (x0,y0)..(x1,y1). */
export function worldBoxRect(x0, y0, x1, y1) {
    if (!gameReady()) return null;
    const t = transform();
    const left = x0 * t.xScale + t.offsetX + t.canvasLeft;
    const top = y0 * t.yScale + t.offsetY + t.canvasTop;
    const right = x1 * t.xScale + t.offsetX + t.canvasLeft;
    const bottom = y1 * t.yScale + t.offsetY + t.canvasTop;
    return { left, top, width: right - left, height: bottom - top };
}

export function config() {
    return gameReady() ? GC().Config : null;
}

export function state() {
    return gameReady() ? GC().State : null;
}

export function traineeId() {
    return gameReady() ? GC().State.localPlayerId : null;
}

export function getPlayer(playerId) {
    if (!gameReady() || !playerId) return null;
    return GC().State.gameState.players[playerId] || null;
}

export function findPlayer(predicate) {
    if (!gameReady()) return null;
    const players = GC().State.gameState.players || {};
    for (const id of Object.keys(players)) {
        if (predicate(players[id])) return players[id];
    }
    return null;
}

export function playerRect(playerId, padMeters = 1.0) {
    const player = getPlayer(playerId);
    if (!player || !player.position) return null;
    return worldRect(player.position.x, player.position.y, padMeters);
}

export function getBall(ballId) {
    if (!gameReady()) return null;
    return GC().State.gameState.balls[ballId] || null;
}

export function ballRect(ballId, padMeters = 0.8) {
    const ball = getBall(ballId);
    if (!ball || !ball.position) return null;
    return worldRect(ball.position.x, ball.position.y, padMeters);
}

export function findBall(predicate) {
    if (!gameReady()) return null;
    const balls = GC().State.gameState.balls || {};
    for (const id of Object.keys(balls)) {
        if (predicate(balls[id])) return balls[id];
    }
    return null;
}

export function hoopRect(hoopId, padMeters = 1.4) {
    if (!gameReady()) return null;
    const hoop = GC().State.gameState.hoops[hoopId];
    if (!hoop || !hoop.position) return null;
    return worldRect(hoop.position.x, hoop.position.y, padMeters);
}

export function findBalls(predicate) {
    if (!gameReady()) return [];
    const balls = GC().State.gameState.balls || {};
    return Object.keys(balls).map((id) => balls[id]).filter(predicate);
}

export function findHoops(predicate) {
    if (!gameReady()) return [];
    const hoops = GC().State.gameState.hoops || {};
    return Object.keys(hoops).map((id) => hoops[id]).filter(predicate);
}

export function domRect(selector) {
    const el = document.querySelector(selector);
    if (!el) return null;
    const rect = el.getBoundingClientRect();
    return { left: rect.left, top: rect.top, width: rect.width, height: rect.height };
}

/** Rects of all players, balls, and the scorebug — for bubble placement avoidance. */
export function obstacleRects() {
    const rects = [];
    if (gameReady()) {
        const gs = GC().State.gameState;
        for (const id of Object.keys(gs.players || {})) {
            const rect = playerRect(id, 1.2);
            if (rect) rects.push(rect);
        }
        for (const id of Object.keys(gs.balls || {})) {
            const rect = ballRect(id, 0.6);
            if (rect) rects.push(rect);
        }
    }
    const scorebug = domRect('.game-ui .scorebug');
    if (scorebug) rects.push(scorebug);
    return rects;
}
