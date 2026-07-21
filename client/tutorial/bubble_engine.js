// Speech-bubble engine: positioned bubbles with pointing arrows, highlight
// rings, and centered hero cards.
//
// A bubble is placed once and then STAYS PUT: it settles for a short window
// (long enough for the server to teleport entities into their scenario spots),
// picks the best free position, and freezes there. It deliberately does not
// follow moving players/balls — only the highlight ring tracks them. Placement
// is redone on resize/fullscreen changes, where old coordinates are meaningless.

import { avatarEl, heroImageEl } from './donatella.js';

const MARGIN = 8;           // min distance to viewport edges
const GAP_LARGE = 16;       // distance between anchor and bubble (leaves room for arrow)
const GAP_SMALL = 10;
const SETTLE_MS = 700;      // keep re-placing this long before freezing

// Kept in sync with the small-screen media query in tutorial.css.
export function isSmallScreen() {
    return window.innerWidth <= 700 || window.innerHeight <= 520;
}

let layer = null;

export function ensureLayer() {
    if (layer && document.body.contains(layer)) return layer;
    layer = document.createElement('div');
    layer.id = 'tutorialLayer';
    document.body.appendChild(layer);
    return layer;
}

export function clearAll() {
    if (layer) layer.innerHTML = '';
}

function rectsOverlap(a, b) {
    return a.left < b.left + b.width && a.left + a.width > b.left &&
        a.top < b.top + b.height && a.top + a.height > b.top;
}

function overlapArea(a, b) {
    const w = Math.min(a.left + a.width, b.left + b.width) - Math.max(a.left, b.left);
    const h = Math.min(a.top + a.height, b.top + b.height) - Math.max(a.top, b.top);
    return (w > 0 && h > 0) ? w * h : 0;
}

/**
 * Footer shared by bubbles and hero cards:
 *   [‹‹ prev section] [‹ prev step]  progress  [› skip step] [›› skip section]  … [✕ exit]
 * The actions are symbols; their wording shows as a tooltip on hover/focus.
 * `onPrevStep`/`onPrevSection` may be null — the control still renders, disabled,
 * so the footer layout does not shift at the start of the tutorial.
 */
function buildFooter(options) {
    const footer = document.createElement('div');
    footer.className = 'tut-footer';

    function navButton(symbol, tip, onClick) {
        const el = document.createElement('button');
        el.className = 'tut-nav';
        el.textContent = symbol;
        el.dataset.tip = tip;
        el.setAttribute('aria-label', tip);
        if (onClick) el.addEventListener('click', onClick);
        else el.disabled = true;
        footer.appendChild(el);
        return el;
    }

    if (options.showPrevSection) navButton('‹‹', 'Previous section', options.onPrevSection);
    if (options.showPrevStep) navButton('‹', 'Previous step', options.onPrevStep);

    if (options.progress) {
        const progress = document.createElement('span');
        progress.className = 'tut-progress';
        progress.textContent = options.progress;
        footer.appendChild(progress);
    }

    if (options.onSkipStep) navButton('›', 'Skip step', options.onSkipStep);
    if (options.onSkipSection) navButton('››', 'Skip section', options.onSkipSection);

    if (options.onExit) {
        const exit = navButton('✕', 'Exit tutorial', options.onExit);
        exit.classList.add('tut-exit');
    }
    return footer.childNodes.length ? footer : null;
}

function centerInside(rect, container) {
    const cx = rect.left + rect.width / 2;
    const cy = rect.top + rect.height / 2;
    return cx >= container.left && cx <= container.left + container.width &&
        cy >= container.top && cy <= container.top + container.height;
}

/**
 * Show a speech bubble.
 *
 * options:
 *   text: string[] (<= 2 short lines)
 *   quip: optional string
 *   hint: optional string (shown below text, updatable)
 *   buttons: [{label, kind: 'primary'|'secondary', onClick}]
 *   progress: optional string ("Section 2/4 · Step 1/5")
 *   onSkipStep / onSkipSection / onExit: optional callbacks (footer icon actions)
 *   showPrevStep / showPrevSection: render the ‹ / ‹‹ controls
 *   onPrevStep / onPrevSection: their callbacks (null → control renders disabled)
 *   getAnchorRect: () => rect|null  (viewport coords; null → centered bubble)
 *   getObstacles: optional () => rect[]  (placement prefers not to cover these)
 *   getCriticalRects: optional () => rect[]  (placement must not cover these, e.g. the player)
 *
 * Returns handle {el, setHint(text), setText(lines, quip), close()}.
 */
export function showBubble(options) {
    ensureLayer();

    const bubble = document.createElement('div');
    bubble.className = 'tut-bubble';

    bubble.appendChild(avatarEl());

    const body = document.createElement('div');
    body.className = 'tut-body';
    bubble.appendChild(body);

    const quipEl = document.createElement('div');
    quipEl.className = 'tut-quip';
    const textEl = document.createElement('div');
    textEl.className = 'tut-text';
    const hintEl = document.createElement('div');
    hintEl.className = 'tut-hint';
    hintEl.style.display = 'none';
    body.appendChild(quipEl);
    body.appendChild(textEl);
    body.appendChild(hintEl);

    function applyText(lines, quip) {
        quipEl.textContent = quip || '';
        quipEl.style.display = quip ? '' : 'none';
        textEl.innerHTML = '';
        (lines || []).forEach((line, index) => {
            if (index > 0) textEl.appendChild(document.createElement('br'));
            textEl.appendChild(document.createTextNode(line));
        });
    }
    applyText(options.text, options.quip);

    if (options.buttons && options.buttons.length) {
        const actions = document.createElement('div');
        actions.className = 'tut-actions';
        options.buttons.forEach((button) => {
            const el = document.createElement('button');
            el.className = 'tut-btn' + (button.kind === 'secondary' ? ' tut-btn-secondary' : '');
            el.textContent = button.label;
            el.addEventListener('click', button.onClick);
            actions.appendChild(el);
        });
        body.appendChild(actions);
    }

    const footer = buildFooter(options);
    if (footer) body.appendChild(footer);

    const arrow = document.createElement('div');
    arrow.className = 'tut-arrow';

    layer.appendChild(arrow); // below the bubble so its shadow never covers text
    layer.appendChild(bubble);

    let closed = false;
    let rafId = null;
    let settleDeadline = null;   // set once the anchor first resolves
    let placement = null;        // frozen geometry: {side, left, top, width, height, ax, ay}

    function positionArrow(side, left, top, bw, bh, ax, ay) {
        arrow.style.display = '';
        const arrowHalf = (arrow.offsetWidth || 14) / 2;
        let arrowLeft, arrowTop;
        if (side === 'top' || side === 'bottom') {
            arrowLeft = Math.max(left + 10, Math.min(left + bw - 10 - 2 * arrowHalf, ax - arrowHalf));
            arrowTop = side === 'top' ? top + bh - arrowHalf : top - arrowHalf;
        } else {
            arrowTop = Math.max(top + 10, Math.min(top + bh - 10 - 2 * arrowHalf, ay - arrowHalf));
            arrowLeft = side === 'right' ? left - arrowHalf : left + bw - arrowHalf;
        }
        arrow.style.left = `${arrowLeft}px`;
        arrow.style.top = `${arrowTop}px`;
    }

    /**
     * Re-fit a frozen bubble after its content (and therefore height) changed,
     * without re-running placement — it must stay where it was put. Bubbles
     * sitting above their anchor keep their bottom edge so they never grow
     * downward over it.
     */
    function refit() {
        if (closed || !placement) return;
        const bw = bubble.offsetWidth;
        const bh = bubble.offsetHeight;
        if (!bw || !bh) return;
        let left = placement.left;
        let top = placement.top;
        if (placement.side === 'center') {
            left = (window.innerWidth - bw) / 2;
            top = (window.innerHeight - bh) / 2;
        } else if (placement.side === 'top') {
            top -= (bh - placement.height);              // keep the bottom edge off the anchor
        } else if (placement.side === 'left' || placement.side === 'right') {
            top -= (bh - placement.height) / 2;          // stay vertically centered on the anchor
        }
        left = Math.max(MARGIN, Math.min(window.innerWidth - bw - MARGIN, left));
        top = Math.max(MARGIN, Math.min(window.innerHeight - bh - MARGIN, top));
        bubble.style.left = `${left}px`;
        bubble.style.top = `${top}px`;
        placement = { ...placement, left, top, width: bw, height: bh };
        if (options.getAnchorRect) {
            positionArrow(placement.side, left, top, bw, bh, placement.ax, placement.ay);
        }
    }

    function applyPlacement() {
        const anchor = options.getAnchorRect ? options.getAnchorRect() : null;
        const bw = bubble.offsetWidth;
        const bh = bubble.offsetHeight;
        const vw = window.innerWidth;
        const vh = window.innerHeight;
        if (!bw || !bh) return false; // not laid out yet

        if (!options.getAnchorRect) {
            arrow.style.display = 'none';
            const left = Math.max(MARGIN, (vw - bw) / 2);
            const top = Math.max(MARGIN, (vh - bh) / 2);
            bubble.style.left = `${left}px`;
            bubble.style.top = `${top}px`;
            placement = { side: 'center', left, top, width: bw, height: bh, ax: 0, ay: 0 };
            return true;
        }
        if (!anchor) return false; // anchor not available yet — keep waiting

        const gap = isSmallScreen() ? GAP_SMALL : GAP_LARGE;
        const ax = anchor.left + anchor.width / 2;
        const ay = anchor.top + anchor.height / 2;
        const right = anchor.left + anchor.width;
        const bottom = anchor.top + anchor.height;

        // Sides first (arrow points cleanly), then diagonals as fallbacks so a
        // crowded pitch still offers somewhere that covers nothing important.
        const candidates = [
            { side: 'top', left: ax - bw / 2, top: anchor.top - gap - bh, bonus: 3 },
            { side: 'bottom', left: ax - bw / 2, top: bottom + gap, bonus: 2 },
            { side: 'right', left: right + gap, top: ay - bh / 2, bonus: 1 },
            { side: 'left', left: anchor.left - gap - bw, top: ay - bh / 2, bonus: 1 },
            { side: 'top', left: anchor.left - gap - bw, top: anchor.top - gap - bh, bonus: 0 },
            { side: 'top', left: right + gap, top: anchor.top - gap - bh, bonus: 0 },
            { side: 'bottom', left: anchor.left - gap - bw, top: bottom + gap, bonus: 0 },
            { side: 'bottom', left: right + gap, top: bottom + gap, bonus: 0 },
        ];

        // Last resort: park in a viewport corner. Negative bonus means these are
        // only chosen when every spot near the anchor would cover something.
        for (const corner of [
            { left: MARGIN, top: MARGIN },
            { left: vw - bw - MARGIN, top: MARGIN },
            { left: MARGIN, top: vh - bh - MARGIN },
            { left: vw - bw - MARGIN, top: vh - bh - MARGIN },
        ]) {
            candidates.push({
                side: (corner.top + bh / 2 < ay) ? 'top' : 'bottom',
                left: corner.left,
                top: corner.top,
                bonus: -1,
            });
        }

        const obstacles = options.getObstacles ? options.getObstacles() : [];
        // When the bubble points AT the player, the anchor gap already keeps it
        // clear — otherwise the constraint would fight the anchor and saturate.
        const critical = (options.getCriticalRects ? options.getCriticalRects() : [])
            .filter((rect) => !centerInside(rect, anchor));
        const bubbleArea = Math.max(1, bw * bh);

        let best = null;
        for (const candidate of candidates) {
            const clampedLeft = Math.max(MARGIN, Math.min(vw - bw - MARGIN, candidate.left));
            const clampedTop = Math.max(MARGIN, Math.min(vh - bh - MARGIN, candidate.top));
            const clampPenalty = Math.abs(clampedLeft - candidate.left) + Math.abs(clampedTop - candidate.top);
            const rect = { left: clampedLeft, top: clampedTop, width: bw, height: bh };

            // Never sit on the player or the highlighted element.
            let hardPenalty = rectsOverlap(rect, anchor) ? 5000 : 0;
            for (const criticalRect of critical) {
                if (rectsOverlap(rect, criticalRect)) hardPenalty += 5000;
            }
            // Prefer covering as little else (other players, balls, scorebug) as possible.
            let softPenalty = 0;
            for (const obstacle of obstacles) {
                softPenalty += (overlapArea(rect, obstacle) / bubbleArea) * 400;
            }

            const score = candidate.bonus - clampPenalty * 2 - softPenalty - hardPenalty;
            if (!best || score > best.score) {
                best = { side: candidate.side, left: clampedLeft, top: clampedTop, score };
            }
        }

        bubble.style.left = `${best.left}px`;
        bubble.style.top = `${best.top}px`;
        placement = { side: best.side, left: best.left, top: best.top, width: bw, height: bh, ax, ay };
        // Arrow sits on the bubble edge facing the anchor, aimed at the anchor center.
        positionArrow(best.side, best.left, best.top, bw, bh, ax, ay);
        return true;
    }

    function schedule() {
        if (rafId === null && !closed) rafId = requestAnimationFrame(step);
    }

    function step() {
        rafId = null;
        if (closed) return;
        const ok = applyPlacement();
        if (!ok) {
            schedule(); // anchor/layout not ready yet
            return;
        }
        // Entities may still be settling into their scenario positions; keep
        // re-placing briefly, then freeze so the bubble stops moving.
        if (settleDeadline === null) settleDeadline = performance.now() + SETTLE_MS;
        if (performance.now() < settleDeadline) schedule();
    }
    schedule();

    // Old coordinates are meaningless after these — re-place (and re-settle).
    function replace() {
        settleDeadline = null;
        placement = null;
        schedule();
    }
    window.addEventListener('resize', replace);
    window.addEventListener('orientationchange', replace);
    document.addEventListener('fullscreenchange', replace);

    return {
        el: bubble,
        setHint(text) {
            const changed = hintEl.textContent !== (text || '');
            hintEl.textContent = text || '';
            hintEl.style.display = text ? '' : 'none';
            if (changed) refit(); // height changed; keep it in place and on screen
        },
        setText(lines, quip) {
            applyText(lines, quip);
            refit();
        },
        // Deliberate re-placement, e.g. when a step switches to a different anchor.
        reposition() {
            replace();
        },
        close() {
            closed = true;
            if (rafId !== null) cancelAnimationFrame(rafId);
            window.removeEventListener('resize', replace);
            window.removeEventListener('orientationchange', replace);
            document.removeEventListener('fullscreenchange', replace);
            bubble.remove();
            arrow.remove();
        },
    };
}

/**
 * Show a centered hero card (intro / graduation).
 * options: {text, quip, buttons, progress, onSkipStep, onSkipSection, onExit}
 */
export function showHero(options) {
    ensureLayer();
    const card = document.createElement('div');
    card.className = 'tut-hero';
    card.appendChild(heroImageEl());

    if (options.quip) {
        const quip = document.createElement('div');
        quip.className = 'tut-quip';
        quip.textContent = options.quip;
        card.appendChild(quip);
    }
    const text = document.createElement('div');
    text.className = 'tut-text';
    (options.text || []).forEach((line, index) => {
        if (index > 0) text.appendChild(document.createElement('br'));
        text.appendChild(document.createTextNode(line));
    });
    card.appendChild(text);

    if (options.buttons && options.buttons.length) {
        const actions = document.createElement('div');
        actions.className = 'tut-actions';
        options.buttons.forEach((button) => {
            const el = document.createElement('button');
            el.className = 'tut-btn' + (button.kind === 'secondary' ? ' tut-btn-secondary' : '');
            el.textContent = button.label;
            el.addEventListener('click', button.onClick);
            actions.appendChild(el);
        });
        card.appendChild(actions);
    }

    const footer = buildFooter(options);
    if (footer) card.appendChild(footer);

    layer.appendChild(card);
    return {
        el: card,
        close() { card.remove(); },
    };
}

/** Pulsing highlight ring following getRect() each frame. */
export function showHighlight(getRect) {
    return showHighlights(() => {
        const rect = getRect ? getRect() : null;
        return rect ? [rect] : [];
    });
}

/**
 * Pulsing highlight rings following getRects() each frame. The ring pool grows
 * to the largest count seen; surplus rings are hidden rather than recreated,
 * so a resolver whose rect count varies does not thrash the DOM.
 */
export function showHighlights(getRects) {
    ensureLayer();
    const rings = [];
    let closed = false;

    function ringAt(index) {
        while (rings.length <= index) {
            const ring = document.createElement('div');
            ring.className = 'tut-ring';
            layer.appendChild(ring);
            rings.push(ring);
        }
        return rings[index];
    }

    function place() {
        if (closed) return;
        const rects = (getRects ? getRects() : null) || [];
        for (let i = 0; i < rects.length; i++) {
            const rect = rects[i];
            const ring = ringAt(i);
            if (!rect) {
                ring.style.display = 'none';
                continue;
            }
            ring.style.display = '';
            ring.style.left = `${rect.left - 4}px`;
            ring.style.top = `${rect.top - 4}px`;
            ring.style.width = `${rect.width + 8}px`;
            ring.style.height = `${rect.height + 8}px`;
        }
        for (let i = rects.length; i < rings.length; i++) rings[i].style.display = 'none';
        requestAnimationFrame(place);
    }
    requestAnimationFrame(place);

    return {
        close() {
            closed = true;
            for (const ring of rings) ring.remove();
        },
    };
}
