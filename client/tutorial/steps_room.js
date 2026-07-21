// Room-page tutorial: Section 1 (introduction) + Section 2 (game_room).
// Relies on room_client.js globals (setPlayerSlot, startGame) and its
// 'q4a:room_state' CustomEvent for interaction detection.

import { runSections, saveState, clearState } from './engine.js';
import { QUIPS } from './donatella.js';

const TARGET_SLOT = 'team_a_chaser_1';

function domRect(selector) {
    const el = document.querySelector(selector);
    if (!el) return null;
    const rect = el.getBoundingClientRect();
    return { left: rect.left, top: rect.top, width: rect.width, height: rect.height };
}

const context = {
    myId: new URLSearchParams(window.location.search).get('player_id'),
    roomState: { players: [], slots: {} },
    initialName: null,
    sendScenario: null,       // no game socket on this page
    getObstacles: null,
    onTutorialEvent: () => () => {},
};

document.addEventListener('q4a:room_state', (event) => {
    context.roomState = event.detail;
});

function mySlot() {
    const slots = context.roomState.slots || {};
    for (const slotId of Object.keys(slots)) {
        if (slots[slotId] === context.myId) return slotId;
    }
    return null;
}

function myPlayer() {
    return (context.roomState.players || []).find((p) => p.id === context.myId) || null;
}

function persistHandoffToGamePage() {
    // The Start click navigates away; make sure the game page resumes at Controls.
    saveState({ active: true, section: 'controls', step: 0 });
}

const sections = [
    {
        id: 'introduction',
        steps: [
            {
                id: 'meet_donatella',
                hero: true,
                quip: QUIPS.meow,
                text: ["I'm Donatella — lynx, mascot, legend.", "And you, trainee, are my next champion."],
                interaction: 'next',
            },
            {
                id: 'objective',
                hero: true,
                quip: QUIPS.stepByStep,
                text: ['Quadball is a fast-paced team sport.', 'With 4 balls and 4 different positions it will never be the same.'],
                interaction: 'next',
            },
        ],
    },
    {
        id: 'game_room',
        onSkip: () => {
            // Auto-place, hand off, and start so the tutorial can continue in-game.
            if (window.setPlayerSlot) window.setPlayerSlot(TARGET_SLOT);
            persistHandoffToGamePage();
            setTimeout(() => { if (window.startGame) window.startGame(); }, 300);
        },
        steps: [
            {
                id: 'room_id',
                anchor: () => domRect('.room-status'),
                quip: QUIPS.surroundings,
                text: ["This is your room's ID.", 'Share it to invite fellow cubs.'],
                interaction: 'next',
            },
            {
                id: 'board',
                anchor: () => domRect('.room-board'),
                text: ['Two teams, their positions —', 'and the spectator bench in the middle.'],
                interaction: 'next',
            },
            {
                id: 'choose_slot',
                anchor: () => domRect(`.slot-box[data-slot-id="${TARGET_SLOT}"]`),
                extraHighlight: () => domRect('.player-card.me'),
                quip: QUIPS.betting,
                text: ['Drag your green card into', 'Team A · Chaser 1.'],
                interaction: 'client',
                check: () => mySlot() === TARGET_SLOT,
                dynamicHint: () => {
                    const slot = mySlot();
                    if (slot && slot !== TARGET_SLOT) {
                        return 'Nice spot — but today you train as Team A Chaser 1.';
                    }
                    return null;
                },
                hint: { afterMs: 12000, text: 'Press and drag your card onto the glowing slot.' },
                onSkip: () => { if (window.setPlayerSlot) window.setPlayerSlot(TARGET_SLOT); },
                success: {
                    text: ['A natural-born chaser!'],
                    quip: QUIPS.meow,
                },
            },
            {
                id: 'enter_name',
                anchor: () => domRect('.player-name-input'),
                text: ['Every legend needs a name.', 'Type yours and press Enter.'],
                interaction: 'client',
                onEnter: (ctx) => {
                    const player = myPlayer();
                    ctx.initialName = player ? player.name : null;
                },
                check: (ctx) => {
                    const player = myPlayer();
                    if (!player) return false;
                    // Pass when the name changed this visit, OR the trainee already
                    // has a custom (non-default "player N") name — the case when
                    // they walked back here from a later section.
                    const changed = ctx.initialName !== null && player.name !== ctx.initialName;
                    const custom = player.name && !/^player \d+$/i.test(player.name.trim());
                    return Boolean(changed || custom);
                },
                hint: { afterMs: 12000, text: 'Click the name field inside your card.' },
                success: {
                    text: (ctx) => {
                        const player = myPlayer();
                        const name = player ? player.name : 'Trainee';
                        return [`${name}, huh? Sounds dangerous. I like it.`];
                    },
                },
            },
            {
                id: 'start_game',
                anchor: () => domRect('#startBtn'),
                quip: QUIPS.must,
                text: ['Hit Start! CPU teammates will', 'fill the empty spots.'],
                interaction: 'client',
                onEnter: () => persistHandoffToGamePage(),
                check: () => false, // the page navigates on start_successful
                hint: { afterMs: 15000, text: 'The green glowing button. You can do it, trainee.' },
                onSkip: () => {
                    if (mySlot() !== TARGET_SLOT && window.setPlayerSlot) window.setPlayerSlot(TARGET_SLOT);
                    persistHandoffToGamePage();
                    setTimeout(() => { if (window.startGame) window.startGame(); }, 300);
                },
            },
        ],
    },
];

runSections(sections, context).then((result) => {
    if (result === 'exit') {
        clearState();
    }
});
