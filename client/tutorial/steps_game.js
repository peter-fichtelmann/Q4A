// Game-page tutorial: Section 3 (controls) + Section 4 (rules).
// Talks to the server's TutorialDirector via {type:'tutorial_step'} messages
// and listens for tutorial_event messages (success / progress / role_change).

import { runSections, clearState, saveState } from './engine.js';
import { clearAll } from './bubble_engine.js';
import { QUIPS } from './donatella.js';
import * as A from './anchors.js';

// ---- context ----

const eventListeners = new Set();

const context = {
    isTouch: false,
    moveAccum: 0,
    lastPos: null,
    getObstacles: () => A.obstacleRects(),
    // The trainee's own player must never end up under a speech bubble.
    getCriticalRects: () => {
        const rect = A.playerRect(A.traineeId(), 2.0);
        return rect ? [rect] : [];
    },
    sendScenario(name) {
        const state = A.state();
        if (state && state.gameSocket && state.gameSocket.readyState === WebSocket.OPEN) {
            state.gameSocket.send(JSON.stringify({ type: 'tutorial_step', step: name }));
        }
    },
    onTutorialEvent(handler) {
        eventListeners.add(handler);
        return () => eventListeners.delete(handler);
    },
    // ‹ / ‹‹ from the first section of this page walk back onto the room page.
    // The tutorial room keeps running; pressing Start there returns here (the
    // server treats an already-started room's Start as an idempotent no-op).
    crossPageBack(sectionId, position) {
        const params = new URLSearchParams(window.location.search);
        const room = params.get('room');
        const player = params.get('player');
        saveState({ active: true, section: sectionId, step: position });
        const query = new URLSearchParams({
            room_id: room || '',
            player_id: player || '',
            creator: '1',
            tutorial: '1',
        });
        window.location.href = `/room?${query.toString()}`;
    },
};

function handleSocketMessage(event) {
    if (typeof event.data !== 'string') return; // binary state updates
    let message;
    try {
        message = JSON.parse(event.data);
    } catch (e) {
        return;
    }
    if (message.type !== 'tutorial_event') return;
    if (message.event === 'role_change') {
        // Roles are otherwise static after initial_state; keep headband colors correct.
        const player = A.getPlayer(message.player_id);
        if (player) player.role = message.role;
        return;
    }
    for (const handler of [...eventListeners]) handler(message);
}

// ---- helpers ----

function trainee() {
    return A.getPlayer(A.traineeId());
}

function traineeTeam() {
    const me = trainee();
    return me ? me.team : 0;
}

function teammate(role) {
    const me = trainee();
    if (!me) return null;
    return A.findPlayer((p) => p.id !== me.id && p.team === me.team && p.role === role);
}

function opponent(predicate) {
    const me = trainee();
    if (!me) return null;
    return A.findPlayer((p) => p.team !== me.team && (!predicate || predicate(p)));
}

function ownCenterHoopId() {
    return `hoop_${traineeTeam()}_center`;
}

// The two outer own hoops — the center one is the bubble anchor and is
// highlighted by the anchor ring already.
function ownSideHoopRects() {
    const centerId = ownCenterHoopId();
    return A.findHoops((hoop) => hoop.team === traineeTeam() && hoop.id !== centerId)
        .map((hoop) => A.hoopRect(hoop.id, 1.1))
        .filter(Boolean);
}

function enemyCenterHoopId() {
    return `hoop_${1 - traineeTeam()}_center`;
}

function traineeRect(pad = 1.0) {
    return A.playerRect(A.traineeId(), pad);
}

function volleyballRect() {
    return A.ballRect('volleyball', 0.9);
}

function isDodgeball(ball) {
    return ball.ball_type === 'dodgeball' || ball.ball_type === 'DODGEBALL';
}

function dodgeballRects() {
    return A.findBalls(isDodgeball)
        .map((ball) => A.ballRect(ball.id, 0.9))
        .filter(Boolean);
}

// The server never sends which dodgeball is the assigned third one, so latch
// onto it while it is still the only free one — the enemy beater dumping theirs
// makes a second dodgeball free moments later.
function thirdDodgeballRect(ctx) {
    if (!ctx.thirdDodgeballId) {
        const free = A.findBalls((ball) => isDodgeball(ball) && !ball.holder_id);
        if (free.length === 1) ctx.thirdDodgeballId = free[0].id;
    }
    return ctx.thirdDodgeballId ? A.ballRect(ctx.thirdDodgeballId, 1.0) : null;
}

// A CPU of the given role from the trainee's own line-up (the trainee itself
// stands apart from the row and already wears the yellow ring).
function lineupPlayerRect(role, pad = 1.2) {
    const player = A.findPlayer((p) => p.team === traineeTeam() && p.role === role && p.id !== A.traineeId());
    return player ? A.playerRect(player.id, pad) : null;
}

// Full-height band on the midline, introduced by the delay-of-game step.
function midlineRect() {
    const config = A.config();
    if (!config) return null;
    return A.worldBoxRect(midlineX() - 0.5, 0, midlineX() + 0.5, config.PITCH_WIDTH);
}

// Strip of the near touchline, introduced by the out-of-bounds step.
function boundaryRect() {
    const config = A.config();
    if (!config) return null;
    return A.worldBoxRect(midlineX() - 8, 0, midlineX() + 8, 1);
}

// The keeper line on the trainee's own half.
function ownKeeperZoneX() {
    const config = A.config();
    if (!config) return null;
    return traineeTeam() === 0 ? config.KEEPER_ZONE_X : config.PITCH_LENGTH - config.KEEPER_ZONE_X;
}

function midlineX() {
    const config = A.config();
    return config ? config.PITCH_LENGTH / 2 : 30;
}

// Anchor for the pass step: the ball until the trainee holds it, then the receiver.
function passAnchor() {
    const me = trainee();
    if (me && me.has_ball) {
        const receiver = teammate('chaser');
        if (receiver) return A.playerRect(receiver.id, 1.2);
    }
    return volleyballRect();
}

// ---- sections ----

const sections = [
    {
        id: 'controls',
        steps: [
            {
                id: 'this_is_you',
                scenario: 'idle_all',
                anchor: () => traineeRect(1.2),
                quip: QUIPS.surroundings,
                text: [
                    'See the yellow ring? That is you.', 
                    // 'The white headband marks you as a chaser.'
                ],
                interaction: 'next',
            },
            // {
            //     id: 'keyboard_overview',
            //     when: (ctx) => !ctx.isTouch,
            //     anchor: null,
            //     text: ['Move: mouse or WASD/arrows · Throw: click or Space', 'Fullscreen: F'],
            //     interaction: 'next',
            // },
            {
                id: 'move',
                anchor: () => traineeRect(1.2),
                quip: QUIPS.moving,
                text: (ctx) => ctx.isTouch
                    ? ['Touch the left side — a joystick appears.', 'Take a lap, trainee!']
                    : ['Your player follows the mouse or WASD/arrows.', 'Take a lap, trainee!'],
                interaction: 'client',
                onEnter: (ctx) => { ctx.moveAccum = 0; ctx.lastPos = null; },
                check: (ctx) => {
                    const me = trainee();
                    if (!me || !me.position) return false;
                    if (ctx.lastPos) {
                        const dx = me.position.x - ctx.lastPos.x;
                        const dy = me.position.y - ctx.lastPos.y;
                        ctx.moveAccum += Math.sqrt(dx * dx + dy * dy);
                    }
                    ctx.lastPos = { x: me.position.x, y: me.position.y };
                    return ctx.moveAccum > 8;
                },
                success: {
                    text: ['Smooth moves, trainee!'],
                    quip: QUIPS.meow,
                },
            },
            {
                id: 'own_hoops',
                scenario: 'hoop_blockage_demo',
                anchor: () => A.hoopRect(ownCenterHoopId(), 1.1),
                extraHighlight: () => ownSideHoopRects(),
                quip: QUIPS.must,
                text: ['The yellow rings are OUR hoops.', 'Try walking straight through one!'],
                interaction: 'server',
                hint: { afterMs: 15000, text: 'Head right at a hoop — something will stop you.' },
                success: {
                    text: ['Bounced off an invisible wall! Chasers may', 'never block their own hoops from both sides.'],
                },
            },
            {
                id: 'pass',
                scenario: 'pass_practice',
                anchor: () => passAnchor(),
                quip: QUIPS.paws,
                text: (ctx) => ctx.isTouch
                    ? ['Walk into the ball to grab it. Face your', 'teammate and tap the right side to throw.']
                    : ['Walk into the ball to grab it. Face your', 'teammate and click (or Space) to throw.'],
                interaction: 'server',
                hint: { afterMs: 20000, text: 'Your throw flies in the direction you are moving/aiming.' },
                progressUpdates: {
                    retry: { hint: 'Out of bounds! Try again.' },
                },
                success: {
                    text: ['Caught! Teamwork makes the wild work.'],
                },
            },
            {
                id: 'score',
                scenario: 'scoring_practice',
                anchor: () => A.hoopRect(enemyCenterHoopId(), 2.0),
                text: ['Throw or carry the ball through a hoop!', 'Any of the three counts.'],
                interaction: 'server',
                hint: { afterMs: 20000, text: 'Get close and run straight through — or throw it in.' },
                progressUpdates: {
                    retry: { hint: 'Out of bounds! Try again.' },
                },
                success: {
                    text: ['GOOOAL! Ten points for us.'],
                    quip: QUIPS.meow,
                },
            },
            {
                id: 'score_behind',
                scenario: 'scoring_behind_practice',
                anchor: () => A.hoopRect(enemyCenterHoopId(), 2.0),
                quip: QUIPS.sneaky,
                text: ['Now you are behind the hoops.', 'Score again — from this side!'],
                interaction: 'server',
                hint: { afterMs: 20000, text: 'Hoops work both ways: just go through it again.' },
                progressUpdates: {
                    retry: { hint: 'Out of bounds! Try again.' },
                },
                success: {
                    text: ['Both sides count! Attack from wherever', 'the defenders are not looking.'],
                },
            },
            {
                id: 'pitch_scorebug',
                anchor: () => A.domRect('.game-ui .scorebug'),
                text: ['Look up: your goals are on the board.', 'Time and score — the higher score wins.'],
                interaction: 'next',
            },
            {
                id: 'tackle',
                scenario: 'tackle_practice',
                anchor: () => {
                    const carrier = opponent((p) => p.has_ball);
                    return carrier ? A.playerRect(carrier.id, 1.2) : null;
                },
                quip: QUIPS.must,
                text: (ctx) => ctx.isTouch
                    ? ['That one stole our ball! Touch the carrier', 'and tap the right side to tackle.']
                    : ['That one stole our ball! Touch the carrier', 'and press space to tackle.'],
                interaction: 'server',
                hint: { afterMs: 20000, text: 'You must be in contact with the carrier when you tackle.' },
                success: {
                    text: ['Flattened! Tackling stops carriers cold.'],
                },
            },
            {
                id: 'fullscreen',
                anchor: (ctx) => (ctx.isTouch ? null : A.domRect('#fullscreenButton')),
                text: (ctx) => ctx.isTouch
                    ? ['Double-tap the right side of the pitch', 'to go fullscreen (and back).']
                    : ['Go fullscreen: press F', 'or use this button.'],
                interaction: 'client',
                check: () => {
                    const state = A.state();
                    return Boolean(document.fullscreenElement || (state && state.fullscreen.isFullscreen));
                },
                hint: { afterMs: 12000, text: 'Not working on your device? Just skip this step.' },
                success: {
                    text: ['Big pitch, big dreams.'],
                },
            },
        ],
    },
    {
        id: 'rules',
        steps: [
            {
                id: 'lineup_headbands',
                scenario: 'lineup',
                anchor: () => lineupPlayerRect('chaser'),
                extraHighlight: () => [lineupPlayerRect('keeper'), lineupPlayerRect('beater')].filter(Boolean),
                quip: QUIPS.stepByStep,
                text: ['Now you see the small rectangular headbands.', 'Each position a one color.'],
                interaction: 'next',
            },
            {
                id: 'lineup_chasers',
                anchor: () => volleyballRect(),
                text: ['White band: chasers — they score goals.', '3 chasers per team, 1 pale volleyball for all.'],
                interaction: 'next',
            },
            {
                id: 'lineup_beaters',
                anchor: () => dodgeballRects()[0] || null,
                extraHighlight: () => dodgeballRects().slice(1),
                text: ['Black band: beaters — they throw dodgeballs.', '2 beaters per team, 3 red dodgeballs in total.'],
                interaction: 'next',
            },
            {
                id: 'beat_practice',
                scenario: 'beat_practice',
                anchor: () => {
                    const me = trainee();
                    if (me && !me.has_ball) {
                        const target = opponent((p) => p.role === 'chaser' && !p.is_knocked_out);
                        if (target) return A.playerRect(target.id, 1.2);
                    }
                    return traineeRect(1.2);
                },
                quip: QUIPS.must,
                text: (ctx) => ctx.isTouch
                    ? ['You are a beater now — black band, dodgeball!', 'Face the strolling chaser and tap to throw.']
                    : ['You are a beater now — black band, dodgeball!', 'Face the strolling chaser and click to throw.'],
                interaction: 'server',
                hint: { afterMs: 20000, text: 'Lead your target a little — they keep walking.' },
                progressUpdates: {
                    retry: { hint: 'Out of bounds! Try again.' },
                },
                success: {
                    text: ['Bullseye! They are off stick — knocked out.'],
                    quip: QUIPS.meow,
                },
                
            },
            {
                id: 'get_beaten',
                scenario: 'get_beaten',
                anchor: () => traineeRect(1.2),
                quip: QUIPS.paws,
                text: ['Fair is fair: their beater hunts YOU now.', 'Try to dodge!'],
                interaction: 'server',
                progressUpdates: {
                    knocked_out: {
                        text: ['Beaten! You drop everything you hold.', 'You auto-jog to your center hoop to recover.'],
                        anchor: () => A.hoopRect(ownCenterHoopId(), 2.0),
                    },
                },
                success: {
                    text: ['Back on stick! Touching your hoop', 'brings you back into the game.'],
                },
            },
            {
                id: 'lineup_keeper',
                scenario: 'lineup',
                anchor: () => lineupPlayerRect('keeper'),
                quip: QUIPS.stepByStep,
                text: ['Green headband: the keeper.', 'A chaser with superpowers.'],
                interaction: 'next',
            },
            {
                id: 'pitch_keeper_lines',
                anchor: () => {
                    const config = A.config();
                    const zoneX = ownKeeperZoneX();
                    if (!config || zoneX === null) return null;
                    return A.worldBoxRect(zoneX - 0.5, 0, zoneX + 0.5, config.PITCH_WIDTH);
                },
                text: ['Behind this line lies keeper territory.', 'In their zone, keepers shrug off dodgeballs.'],
                interaction: 'next',
            },
            {
                id: 'keeper_immunity',
                scenario: 'keeper_immunity_demo',
                anchor: () => traineeRect(1.2),
                quip: QUIPS.paws,
                text: ['You are the keeper now — green band!', 'Stay calm: in your zone, those beats bounce off.'],
                interaction: 'next',
            },
            {
                id: 'goal_restart',
                scenario: 'goal_restart_demo',
                anchor: () => {
                    const carrier = opponent((p) => p.has_ball);
                    return carrier ? A.playerRect(carrier.id, 1.2) : volleyballRect();
                },
                text: ['Still keeping — now mind the hoops.', 'Watch them attack…'],
                interaction: 'server',
                progressUpdates: {
                    goal_scored: {
                        text: ['Goal against us! The ball is dead now.', 'Only you may pick it up — but it is auto-fetch!'],
                        anchor: () => volleyballRect(),
                    },
                },
                success: {
                    text: ['Ball is alive again — that is the restart.', 'The keeper carries it back into play.'],
                },
            },
            {
                id: 'seekers',
                anchor: null,
                text: ['One band is still missing: yellow for seekers,', 'chasing the snitch. Not implemented yet!'],
                interaction: 'next',
            },
            {
                id: 'delay_of_game',
                scenario: 'delay_demo',
                anchor: () => midlineRect(),
                quip: QUIPS.surroundings,
                text: ['The midline splits the pitch. Stand still and watch…'],
                interaction: 'server',
                progressUpdates: {
                    delay_ticking: {
                        text: ['See the clock? That is delay of game.', 'Move it, trainee — cross the midline!'],
                        quip: QUIPS.moving,
                    },
                },
                success: {
                    text: (ctx) => (ctx.outcome === 'turnover'
                        ? ['Too slow — the referee handed the ball', 'to the other team. That is a delay turnover!']
                        : ['That is hustle! Keep the game flowing', 'or the referee takes the ball away.']),
                    quip: (ctx) => (ctx.outcome === 'turnover' ? QUIPS.moving : undefined),
                },
            },
            {
                id: 'out_of_bounds',
                scenario: 'oob_demo',
                anchor: () => boundaryRect(),
                extraHighlight: () => volleyballRect(),
                text: ['The dark red frame is the boundary.', 'Mischief: throw the ball over the near line!'],
                interaction: 'server',
                hint: { afterMs: 15000, text: 'Face the closest red line and throw.' },
                success: {
                    text: ['Out! They inbound and you cannot come to close.', 'Only volleyballs are inbounded, never dodgeballs.'],
                },
            },
            {
                id: 'third_dodgeball',
                scenario: 'third_dodgeball_demo',
                anchor: (ctx) => thirdDodgeballRect(ctx),
                quip: QUIPS.must,
                text: ['You are a beater. They hold both dodgeballs,', 'so the free one is ours. Watch them anyway…'],
                interaction: 'server',
                onEnter: (ctx) => { ctx.thirdDodgeballId = null; },
                progressUpdates: {
                    ball_dumped: {
                        text: ['That was no beat.', 'Only a real beat earns the third ball.'],
                    },
                    retry: { hint: 'You picked it up — leave it and let them foul.' },
                },
                success: {
                    text: ['3rd DodgeballInterference! Back to hoops for them,', 'and ball turnovers to us.'],
                    quip: QUIPS.meow,
                },
            },
            {
                id: 'graduation',
                hero: true,
                scenario: 'idle_all',
                quip: QUIPS.essentials,
                text: ['You have earned your headband, trainee.', 'Now go make this lynx proud!'],
                interaction: 'buttons',
                buttons: (ctx, finish) => [
                    {
                        label: '🐾 Free play',
                        onClick: () => {
                            ctx.sendScenario('free_play');
                            finish('done');
                        },
                    },
                    {
                        label: 'Back to lobby',
                        kind: 'secondary',
                        onClick: () => {
                            clearState();
                            window.location.href = '/';
                        },
                    },
                ],
            },
        ],
    },
];

// ---- bootstrap: wait for the game client to be ready ----

function whenReady(callback) {
    const timer = setInterval(() => {
        const state = A.state();
        if (A.gameReady() && state.gameSocket && state.gameSocket.readyState === WebSocket.OPEN) {
            clearInterval(timer);
            callback();
        }
    }, 200);
}

whenReady(() => {
    const state = A.state();
    context.isTouch = state.isTouchDevice;
    state.gameSocket.addEventListener('message', handleSocketMessage);
    runSections(sections, context).then((result) => {
        // Do not wipe saved progress when we are navigating back to the room page.
        if (result !== 'navigating') {
            clearState();
            clearAll();
        }
    });
});
