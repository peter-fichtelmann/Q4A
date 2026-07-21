// Donatella the lynx: quips and image elements (with placeholders until art exists).

const AVATAR_SRC = '/client/tutorial/assets/donatella_avatar.png';
const HERO_SRC = '/client/tutorial/assets/donatella_large.png';

export const QUIPS = {
    surroundings: 'Lynx rule number one: always know your surroundings.',
    paws: 'Relax your paws, sharpen your claws.',
    meow: 'Meow!',
    must: 'A lynx must do what a lynx must do.',
    essentials: "That's the essentials. You can explore now—but keep your ears up and your claws ready.",
    moving: 'First rule of the wild: keep moving.',
    betting: "Choose like you're betting your tail on it.",
    stepByStep: "We'll take this step by step.",
    sneaky: 'A lynx never attacks from where you are expected.',
};

function placeholder(container, emojiSize) {
    const emoji = document.createElement('div');
    emoji.className = 'tut-placeholder-emoji';
    emoji.textContent = '🐈'; // 🐈
    if (emojiSize) emoji.style.fontSize = `${emojiSize}px`;
    const caption = document.createElement('div');
    caption.className = 'tut-placeholder-caption';
    caption.textContent = 'Donatella';
    container.appendChild(emoji);
    if (!emojiSize || emojiSize > 30) container.appendChild(caption);
}

function imageWithFallback(container, src, emojiSize) {
    const img = document.createElement('img');
    img.alt = 'Donatella the lynx coach';
    img.src = src;
    img.addEventListener('error', () => {
        img.remove();
        placeholder(container, emojiSize);
    });
    container.appendChild(img);
}

// Small round avatar used inside speech bubbles.
export function avatarEl() {
    const el = document.createElement('div');
    el.className = 'tut-avatar';
    imageWithFallback(el, AVATAR_SRC, 20);
    return el;
}

// Large image used on hero cards (intro / graduation).
export function heroImageEl() {
    const el = document.createElement('div');
    el.className = 'tut-hero-image';
    imageWithFallback(el, HERO_SRC, 52);
    return el;
}
