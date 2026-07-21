// Tutorial step runner: drives sections/steps defined as data, persists
// progress across page navigations, and handles skip/exit on every step.

import { showBubble, showHero, showHighlight, showHighlights, clearAll, isSmallScreen } from './bubble_engine.js';

const STORAGE_KEY = 'q4a_tutorial';

// Global section order across both pages (for the progress indicator).
export const SECTION_ORDER = ['introduction', 'game_room', 'controls', 'rules'];
export const SECTION_LABELS = {
    introduction: 'Introduction',
    game_room: 'Game Room',
    controls: 'Controls',
    rules: 'Rules',
};

export function loadState() {
    try {
        return JSON.parse(sessionStorage.getItem(STORAGE_KEY)) || null;
    } catch (e) {
        return null;
    }
}

export function saveState(state) {
    try {
        sessionStorage.setItem(STORAGE_KEY, JSON.stringify(state));
    } catch (e) { /* ignore */ }
}

export function clearState() {
    try {
        sessionStorage.removeItem(STORAGE_KEY);
    } catch (e) { /* ignore */ }
}

function progressLabel(sectionId, stepIndex, stepCount) {
    const sectionNumber = SECTION_ORDER.indexOf(sectionId) + 1;
    // Compact on phones so the skip links keep their full width in the footer.
    if (isSmallScreen()) {
        return `🐾 ${sectionNumber}/${SECTION_ORDER.length} · ${stepIndex + 1}/${stepCount}`;
    }
    return `🐾 ${SECTION_LABELS[sectionId] || sectionId} ${sectionNumber}/${SECTION_ORDER.length} · Step ${stepIndex + 1}/${stepCount}`;
}

function resolve(value, context) {
    return (typeof value === 'function') ? value(context) : value;
}

/**
 * Run one step. Resolves with
 * 'done' | 'skip-step' | 'skip-section' | 'prev' | 'prev-section' | 'exit'.
 *
 * Step fields:
 *   id, hero?: bool
 *   text: string[] | (ctx) => string[]   (<= 2 short lines)
 *   quip?: string | fn
 *   when?: (ctx) => bool                  (false → step silently skipped)
 *   anchor?: (ctx) => rect|null           (bubble target, also highlighted)
 *   extraHighlight?: (ctx) => rect|rect[]|null
 *   scenario?: string                     (sent via ctx.sendScenario on enter)
 *   interaction: 'next' | 'client' | 'server' | 'buttons'
 *   check?: (ctx) => bool                 (client interaction predicate, polled)
 *   hint?: {afterMs, text: string | fn}
 *   dynamicHint?: (ctx) => string|null    (polled; overrides static hint)
 *   progressUpdates?: {detail: {text, quip?, anchor?}}  (server progress events)
 *   success?: {text: string[] | fn, quip?: string}      (congratulation bubble)
 *   buttons?: (ctx, finish) => button[]   (interaction 'buttons'; finish(result))
 *   onEnter?, onSkip?: (ctx) => void
 */
function runStep(step, context, progress) {
    return new Promise((resolveStep) => {
        if (step.when && !step.when(context)) {
            resolveStep('done-silent');
            return;
        }
        context.outcome = 'default';
        if (step.onEnter) step.onEnter(context);
        if (step.scenario && context.sendScenario) context.sendScenario(step.scenario);

        let finished = false;
        let bubble = null;
        let highlight = null;
        let extraHighlight = null;
        let pollTimer = null;
        let hintTimer = null;
        let unsubscribe = null;
        let currentAnchor = step.anchor || null;

        function cleanup() {
            finished = true;
            if (bubble) bubble.close();
            if (highlight) highlight.close();
            if (extraHighlight) extraHighlight.close();
            if (pollTimer) clearInterval(pollTimer);
            if (hintTimer) clearTimeout(hintTimer);
            if (unsubscribe) unsubscribe();
        }

        function finish(result) {
            if (finished) return;
            cleanup();
            if (result === 'done' && step.success) {
                const successBubble = showBubble({
                    text: resolve(step.success.text, context),
                    quip: resolve(step.success.quip, context),
                    getAnchorRect: currentAnchor ? () => currentAnchor(context) : null,
                    getObstacles: context.getObstacles,
                    getCriticalRects: context.getCriticalRects,
                    buttons: [{
                        label: 'Continue ›',
                        onClick: () => { successBubble.close(); resolveStep('done'); },
                    }],
                });
                return;
            }
            resolveStep(result);
        }

        const baseOptions = {
            text: resolve(step.text, context),
            quip: resolve(step.quip, context),
            progress,
            getObstacles: context.getObstacles,
            getCriticalRects: context.getCriticalRects,
            showPrevSection: true,
            showPrevStep: true,
            // null when there is nothing earlier on this page → control renders disabled
            onPrevSection: context.hasPrevSection ? () => finish('prev-section') : null,
            onPrevStep: context.hasPrevStep ? () => finish('prev') : null,
            onSkipStep: () => {
                if (step.onSkip) step.onSkip(context);
                finish('skip-step');
            },
            onSkipSection: () => finish('skip-section'),
            onExit: () => finish('exit'),
        };

        function attachAnchor() {
            if (currentAnchor) {
                baseOptions.getAnchorRect = () => currentAnchor(context);
                if (highlight) highlight.close();
                highlight = showHighlight(() => currentAnchor(context));
            } else {
                baseOptions.getAnchorRect = null;
            }
        }
        attachAnchor();
        if (step.extraHighlight) {
            extraHighlight = showHighlights(() => {
                const rects = step.extraHighlight(context);
                if (!rects) return [];
                return Array.isArray(rects) ? rects : [rects];
            });
        }

        const show = step.hero ? showHero : showBubble;

        if (step.interaction === 'next') {
            baseOptions.buttons = [{ label: 'Next ›', onClick: () => finish('done') }];
            bubble = show(baseOptions);
        } else if (step.interaction === 'buttons') {
            baseOptions.buttons = step.buttons(context, finish);
            bubble = show(baseOptions);
        } else if (step.interaction === 'client') {
            bubble = show(baseOptions);
            let staticHint = null;
            pollTimer = setInterval(() => {
                if (finished) return;
                if (step.dynamicHint && bubble.setHint) {
                    bubble.setHint(step.dynamicHint(context) || staticHint);
                }
                if (step.check && step.check(context)) finish('done');
            }, 150);
            if (step.hint && bubble.setHint) {
                hintTimer = setTimeout(() => {
                    if (!finished) {
                        staticHint = resolve(step.hint.text, context);
                        bubble.setHint((step.dynamicHint && step.dynamicHint(context)) || staticHint);
                    }
                }, step.hint.afterMs || 12000);
            }
        } else if (step.interaction === 'server') {
            bubble = show(baseOptions);
            unsubscribe = context.onTutorialEvent((event) => {
                if (finished) return;
                if (event.step !== step.scenario) return;
                if (event.event === 'success') {
                    // Lets a step's success message vary by how it was completed.
                    context.outcome = event.outcome || 'default';
                    finish('done');
                } else if (event.event === 'progress' && step.progressUpdates) {
                    const update = step.progressUpdates[event.detail];
                    if (update) {
                        if (update.text && bubble.setText) {
                            bubble.setText(resolve(update.text, context), resolve(update.quip, context));
                        }
                        if (update.hint && bubble.setHint) {
                            bubble.setHint(resolve(update.hint, context));
                        }
                        if (update.anchor) {
                            // A different element is being pointed at now, so the
                            // bubble is allowed to move once and settle again.
                            currentAnchor = update.anchor;
                            attachAnchor();
                            if (bubble.reposition) bubble.reposition();
                        }
                    }
                }
            });
        } else {
            bubble = show(baseOptions);
        }

        if (step.hint && step.interaction !== 'client' && bubble && bubble.setHint) {
            hintTimer = setTimeout(() => {
                if (!finished) bubble.setHint(resolve(step.hint.text, context));
            }, step.hint.afterMs || 12000);
        }
    });
}

/**
 * Run a list of sections on the current page.
 * sections: [{id, steps, onSkip?}]
 * Returns 'finished' | 'exit'.
 */
export async function runSections(sections, context) {
    const saved = loadState() || {};
    let sectionIndex = 0;
    let startStep = 0;
    if (saved.section) {
        const found = sections.findIndex((section) => section.id === saved.section);
        if (found >= 0) {
            sectionIndex = found;
            startStep = saved.step || 0;
        } else if (SECTION_ORDER.indexOf(saved.section) > SECTION_ORDER.indexOf(sections[sections.length - 1].id)) {
            return 'finished'; // saved progress is beyond this page's sections
        }
    }

    let stepIndex = startStep;
    // Steps hidden by `when` resolve instantly; keep travelling the way the user
    // was going so 'previous' cannot bounce straight forward off a hidden step.
    let direction = 1;

    while (sectionIndex < sections.length) {
        const section = sections[sectionIndex];

        if (stepIndex >= section.steps.length) {
            sectionIndex += 1;
            stepIndex = 0;
            direction = 1;
            continue;
        }
        if (stepIndex < 0) {
            // Walk back into the previous section on this page, or stay put.
            if (sectionIndex === 0) {
                stepIndex = 0;
                direction = 1;
                continue;
            }
            sectionIndex -= 1;
            stepIndex = sections[sectionIndex].steps.length - 1;
            continue;
        }

        // Only the very first step of the page has nothing to go back to.
        context.hasPrevStep = !(sectionIndex === 0 && stepIndex === 0);
        // ‹‹ needs an earlier section that lives on this page.
        context.hasPrevSection = sectionIndex > 0;

        const step = section.steps[stepIndex];
        saveState({ active: true, section: section.id, step: stepIndex });
        const progress = progressLabel(section.id, stepIndex, section.steps.length);
        const result = await runStep(step, context, progress);

        if (result === 'exit') {
            clearState();
            clearAll();
            return 'exit';
        }
        if (result === 'prev') {
            direction = -1;
            stepIndex -= 1;
            continue;
        }
        if (result === 'prev-section') {
            // Restart the previous section from its first step.
            sectionIndex -= 1;
            stepIndex = 0;
            direction = 1;
            continue;
        }
        if (result === 'done-silent') {
            stepIndex += direction;   // hidden step: keep going the same way
            continue;
        }
        direction = 1;
        if (result === 'skip-section') {
            if (section.onSkip) section.onSkip(context);
            sectionIndex += 1;
            stepIndex = 0;
            continue;
        }
        stepIndex += 1;   // 'done' and 'skip-step'
    }
    return 'finished';
}
