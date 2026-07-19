// Speech-bubble engine: positioned bubbles with pointing arrows, highlight
// rings, and centered hero cards. Bubble positions are recomputed every
// animation frame so they can track moving anchors (canvas entities).

import { avatarEl, heroImageEl } from './donatella.js';

const MARGIN = 8;       // min distance to viewport edges
const GAP = 16;         // distance between anchor and bubble (leaves room for arrow)

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
 * Show a speech bubble.
 *
 * options:
 *   text: string[] (<= 2 short lines)
 *   quip: optional string
 *   hint: optional string (shown below text, updatable)
 *   buttons: [{label, kind: 'primary'|'secondary', onClick}]
 *   progress: optional string ("Section 2/4 · Step 1/5")
 *   onSkipStep / onSkipSection / onExit: optional callbacks (footer links)
 *   getAnchorRect: () => rect|null  (viewport coords; null → centered bubble)
 *   getObstacles: optional () => rect[]  (placement avoids covering these)
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

    const footer = document.createElement('div');
    footer.className = 'tut-footer';
    if (options.progress) {
        const progress = document.createElement('span');
        progress.className = 'tut-progress';
        progress.textContent = options.progress;
        footer.appendChild(progress);
    }
    function footerLink(label, onClick) {
        const el = document.createElement('button');
        el.className = 'tut-skip';
        el.textContent = label;
        el.addEventListener('click', onClick);
        footer.appendChild(el);
    }
    if (options.onSkipStep) footerLink('Skip step', options.onSkipStep);
    if (options.onSkipSection) footerLink('Skip section', options.onSkipSection);
    if (options.onExit) {
        const exit = document.createElement('button');
        exit.className = 'tut-exit';
        exit.title = 'Exit tutorial';
        exit.textContent = '✕';
        exit.addEventListener('click', options.onExit);
        footer.appendChild(exit);
    }
    if (footer.childNodes.length) body.appendChild(footer);

    const arrow = document.createElement('div');
    arrow.className = 'tut-arrow';

    layer.appendChild(arrow); // below the bubble so its shadow never covers text
    layer.appendChild(bubble);

    let closed = false;

    function place() {
        if (closed) return;
        const anchor = options.getAnchorRect ? options.getAnchorRect() : null;
        const bw = bubble.offsetWidth;
        const bh = bubble.offsetHeight;
        const vw = window.innerWidth;
        const vh = window.innerHeight;

        if (!anchor) {
            arrow.style.display = 'none';
            bubble.style.left = `${Math.max(MARGIN, (vw - bw) / 2)}px`;
            bubble.style.top = `${Math.max(MARGIN, (vh - bh) / 2)}px`;
            requestAnimationFrame(place);
            return;
        }

        const ax = anchor.left + anchor.width / 2;
        const ay = anchor.top + anchor.height / 2;

        const candidates = [
            { side: 'top', left: ax - bw / 2, top: anchor.top - GAP - bh, bonus: 3 },
            { side: 'bottom', left: ax - bw / 2, top: anchor.top + anchor.height + GAP, bonus: 2 },
            { side: 'right', left: anchor.left + anchor.width + GAP, top: ay - bh / 2, bonus: 1 },
            { side: 'left', left: anchor.left - GAP - bw, top: ay - bh / 2, bonus: 1 },
        ];

        const obstacles = options.getObstacles ? options.getObstacles() : [];
        let best = null;
        for (const candidate of candidates) {
            const clampedLeft = Math.max(MARGIN, Math.min(vw - bw - MARGIN, candidate.left));
            const clampedTop = Math.max(MARGIN, Math.min(vh - bh - MARGIN, candidate.top));
            const clampPenalty = Math.abs(clampedLeft - candidate.left) + Math.abs(clampedTop - candidate.top);
            const rect = { left: clampedLeft, top: clampedTop, width: bw, height: bh };
            let obstaclePenalty = 0;
            for (const obstacle of obstacles) {
                obstaclePenalty += overlapArea(rect, obstacle);
            }
            const anchorPenalty = rectsOverlap(rect, anchor) ? 5000 : 0;
            const score = candidate.bonus - clampPenalty * 2 - obstaclePenalty * 0.05 - anchorPenalty;
            if (!best || score > best.score) {
                best = { ...candidate, left: clampedLeft, top: clampedTop, score };
            }
        }

        bubble.style.left = `${best.left}px`;
        bubble.style.top = `${best.top}px`;

        // Arrow sits on the bubble edge facing the anchor, aimed at the anchor center.
        arrow.style.display = '';
        const arrowHalf = 7;
        let arrowLeft, arrowTop;
        if (best.side === 'top' || best.side === 'bottom') {
            arrowLeft = Math.max(best.left + 10, Math.min(best.left + bw - 10 - 2 * arrowHalf, ax - arrowHalf));
            arrowTop = best.side === 'top' ? best.top + bh - arrowHalf : best.top - arrowHalf;
        } else {
            arrowTop = Math.max(best.top + 10, Math.min(best.top + bh - 10 - 2 * arrowHalf, ay - arrowHalf));
            arrowLeft = best.side === 'right' ? best.left - arrowHalf : best.left + bw - arrowHalf;
        }
        arrow.style.left = `${arrowLeft}px`;
        arrow.style.top = `${arrowTop}px`;

        requestAnimationFrame(place);
    }
    requestAnimationFrame(place);

    return {
        el: bubble,
        setHint(text) {
            hintEl.textContent = text || '';
            hintEl.style.display = text ? '' : 'none';
        },
        setText(lines, quip) {
            applyText(lines, quip);
        },
        close() {
            closed = true;
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

    const footer = document.createElement('div');
    footer.className = 'tut-footer';
    if (options.progress) {
        const progress = document.createElement('span');
        progress.className = 'tut-progress';
        progress.textContent = options.progress;
        footer.appendChild(progress);
    }
    function footerLink(label, onClick) {
        const el = document.createElement('button');
        el.className = 'tut-skip';
        el.textContent = label;
        el.addEventListener('click', onClick);
        footer.appendChild(el);
    }
    if (options.onSkipStep) footerLink('Skip step', options.onSkipStep);
    if (options.onSkipSection) footerLink('Skip section', options.onSkipSection);
    if (options.onExit) {
        const exit = document.createElement('button');
        exit.className = 'tut-exit';
        exit.title = 'Exit tutorial';
        exit.textContent = '✕';
        exit.addEventListener('click', options.onExit);
        footer.appendChild(exit);
    }
    if (footer.childNodes.length) card.appendChild(footer);

    layer.appendChild(card);
    return {
        el: card,
        close() { card.remove(); },
    };
}

/** Pulsing highlight ring following getRect() each frame. */
export function showHighlight(getRect) {
    ensureLayer();
    const ring = document.createElement('div');
    ring.className = 'tut-ring';
    layer.appendChild(ring);
    let closed = false;

    function place() {
        if (closed) return;
        const rect = getRect ? getRect() : null;
        if (rect) {
            ring.style.display = '';
            ring.style.left = `${rect.left - 4}px`;
            ring.style.top = `${rect.top - 4}px`;
            ring.style.width = `${rect.width + 8}px`;
            ring.style.height = `${rect.height + 8}px`;
        } else {
            ring.style.display = 'none';
        }
        requestAnimationFrame(place);
    }
    requestAnimationFrame(place);

    return {
        close() {
            closed = true;
            ring.remove();
        },
    };
}
