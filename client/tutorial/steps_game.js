// Game-page tutorial: Section 3 (controls) + Section 4 (rules).
// Talks to the server's TutorialDirector via {type:'tutorial_step'} messages
// and listens for tutorial_event messages (success / progress / role_change).

import { runSections, clearState } from './engine.js';
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

function enemyCenterHoopId() {
    return `hoop_${1 - traineeTeam()}_center`;
}

function traineeRect(pad = 1.0) {
    return A.playerRect(A.traineeId(), pad);
}

function volleyballRect() {
    return A.ballRect('volleyball', 0.9);
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
                text: ['See the yellow ring? That is you.', 'The white headband marks you as a chaser.'],
                interaction: 'next',
            },
            {
                id: 'keyboard_overview',
                when: (ctx) => !ctx.isTouch,
                anchor: null,
                text: ['Move: mouse or WASD/arrows · Throw: click or Space', 'Fullscreen: F'],
                interaction: 'next',
            },
            {
                id: 'move',
                anchor: () => traineeRect(1.2),
                quip: QUIPS.moving,
                text: (ctx) => ctx.isTouch
                    ? ['Touch the left side — a joystick appears.', 'Take a lap, trainee!']
                    : ['Your player follows the mouse.', 'Take a lap, trainee!'],
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
                    text: ['Smooth moves! One warning: chasers may', 'never block the space before their own hoops.'],
                    quip: QUIPS.meow,
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
                id: 'tackle',
                scenario: 'tackle_practice',
                anchor: () => {
                    const carrier = opponent((p) => p.has_ball);
                    return carrier ? A.playerRect(carrier.id, 1.2) : null;
                },
                quip: QUIPS.must,
                text: (ctx) => ctx.isTouch
                    ? ['That one stole our ball! Touch the carrier', 'and tap the right side to tackle.']
                    : ['That one stole our ball! Touch the carrier', 'and click to tackle.'],
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
                id: 'pitch_midline',
                scenario: 'idle_all',
                anchor: () => {
                    const config = A.config();
                    if (!config) return null;
                    return A.worldBoxRect(midlineX() - 0.5, 0, midlineX() + 0.5, config.PITCH_WIDTH);
                },
                quip: QUIPS.surroundings,
                text: ['The midline splits the pitch.', 'Stalling with the ball in your half? Penalty!'],
                interaction: 'next',
            },
            {
                id: 'pitch_keeper_lines',
                anchor: () => {
                    const config = A.config();
                    if (!config) return null;
                    return A.worldBoxRect(config.KEEPER_ZONE_X - 0.5, 0, config.KEEPER_ZONE_X + 0.5, config.PITCH_WIDTH);
                },
                text: ['Behind this line lies keeper territory.', 'In their zone, keepers shrug off dodgeballs.'],
                interaction: 'next',
            },
            {
                id: 'pitch_boundary',
                anchor: () => {
                    const config = A.config();
                    if (!config) return null;
                    return A.worldBoxRect(midlineX() - 8, 0, midlineX() + 8, 1);
                },
                text: ['The dark red frame is the boundary.', 'Balls that cross it are out of bounds.'],
                interaction: 'next',
            },
            {
                id: 'pitch_scorebug',
                anchor: () => A.domRect('.game-ui .scorebug'),
                text: ['Time and score live up here.', 'Goals score points — highest score wins.'],
                interaction: 'next',
            },
            {
                id: 'lineup_keeper',
                scenario: 'lineup',
                anchor: () => {
                    const keeper = A.findPlayer((p) => p.team === traineeTeam() && p.role === 'keeper');
                    return keeper ? A.playerRect(keeper.id, 1.2) : null;
                },
                quip: QUIPS.stepByStep,
                text: ['Green headband: the keeper.', 'Guards the hoops and handles dead balls.'],
                interaction: 'next',
            },
            {
                id: 'lineup_chaser_beater',
                anchor: () => {
                    const beater = A.findPlayer((p) => p.team === traineeTeam() && p.role === 'beater');
                    return beater ? A.playerRect(beater.id, 1.2) : null;
                },
                text: ['Black band: beaters — they throw dodgeballs.', 'White band: chasers — they score goals.'],
                interaction: 'next',
            },
            {
                id: 'lineup_balls',
                anchor: () => volleyballRect(),
                text: ['The pale ball scores goals. The red ones sting.', 'Yellow-band seekers? Not trained yet.'],
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
                        text: ['Beaten! You drop everything you hold.', 'You jog to your center hoop to recover.'],
                        anchor: () => A.hoopRect(ownCenterHoopId(), 2.0),
                    },
                },
                success: {
                    text: ['Back on stick! Touching your hoop', 'brings you back into the game.'],
                },
            },
            {
                id: 'goal_restart',
                scenario: 'goal_restart_demo',
                anchor: () => {
                    const carrier = opponent((p) => p.has_ball);
                    return carrier ? A.playerRect(carrier.id, 1.2) : volleyballRect();
                },
                text: ['You are the keeper now — green band!', 'Watch them attack our hoops…'],
                interaction: 'server',
                progressUpdates: {
                    goal_scored: {
                        text: ['Goal against us! The ball is dead now.', 'Only you may pick it up — go fetch!'],
                        anchor: () => volleyballRect(),
                    },
                },
                success: {
                    text: ['Ball is alive again — that is the restart.', 'The keeper carries it back into play.'],
                },
            },
            {
                id: 'delay_of_game',
                scenario: 'delay_demo',
                anchor: () => volleyballRect(),
                text: ['You hold the ball in our own half.', 'Now stand completely still and watch…'],
                interaction: 'server',
                progressUpdates: {
                    delay_ticking: {
                        text: ['See the clock? That is delay of game.', 'Move it, trainee — cross the midline!'],
                        quip: QUIPS.moving,
                    },
                },
                success: {
                    text: ['That is hustle! Keep the game flowing', 'or the referee takes the ball away.'],
                },
            },
            {
                id: 'out_of_bounds',
                scenario: 'oob_demo',
                anchor: () => volleyballRect(),
                text: ['Time for mischief: throw the ball', 'over the nearby boundary line!'],
                interaction: 'server',
                hint: { afterMs: 15000, text: 'Face the closest red line and throw.' },
                success: {
                    text: ['Out! The other team throws it back in', 'with a free path. Do not make it a habit.'],
                },
            },
            {
                id: 'third_dodgeball',
                scenario: 'third_dodgeball_demo',
                anchor: () => {
                    const free = A.findBall((b) => (b.ball_type === 'dodgeball' || b.ball_type === 'DODGEBALL') && !b.holder_id);
                    return free ? A.ballRect(free.id, 1.0) : null;
                },
                text: ['They hold two dodgeballs, so the free one', 'belongs to us. Grabbing a third is a foul.'],
                interaction: 'next',
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
    runSections(sections, context).then(() => {
        clearState();
        clearAll();
    });
});
