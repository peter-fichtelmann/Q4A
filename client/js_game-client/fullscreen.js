import { State } from './state.js';

export function request() {
  const element = document.documentElement;
  const f = element.requestFullscreen || element.webkitRequestFullscreen || element.msRequestFullscreen || element.mozRequestFullScreen;
  if (f) {
    Promise.resolve().then(() => f.call(element)).catch(err => console.log('Fullscreen request failed:', err));
  }
  State.fullscreen.attempted = true;
}

export function exit() {
  const f = document.exitFullscreen || document.webkitExitFullscreen || document.msExitFullscreen || document.mozCancelFullScreen;
  if (f) f.call(document);
}

export function toggle() { if (State.fullscreen.isFullscreen) exit(); else request(); }

export function updateState() {
  State.fullscreen.isFullscreen = !!(document.fullscreenElement || document.webkitFullscreenElement || document.msFullscreenElement || document.mozFullScreenElement);
  updateButton();
}

export function showPrompt() {
  if (!State.fullscreen.button) {
    const btn = document.createElement('button');
    btn.id = 'fullscreenButton';
    btn.innerHTML = '⛶';
    btn.style.cssText = 'position: fixed; top: 10px; right: 10px; z-index: 1000; background: rgba(0,0,0,0.7); color: white; border: 2px solid rgba(255,255,255,0.3); border-radius: 8px; padding: 8px 12px; font-size: 18px; cursor: pointer; font-family: monospace; transition: all 0.3s ease; user-select: none;';
    btn.addEventListener('mouseenter', () => { btn.style.borderColor = 'rgba(255,255,255,0.6)'; btn.style.transform = 'scale(1.05)'; });
    btn.addEventListener('mouseleave', () => { btn.style.borderColor = 'rgba(255,255,255,0.3)'; btn.style.transform = 'scale(1)'; });
    btn.addEventListener('click', (e) => { e.preventDefault(); toggle(); });
    document.body.appendChild(btn);
    State.fullscreen.button = btn;
  }
  updateButton();
}

export function updateButton() {
  const button = State.fullscreen.button;
  if (!button) return;
  if (State.fullscreen.isFullscreen) { button.innerHTML = '⛷'; button.title = 'Exit Fullscreen'; }
  else { button.innerHTML = '⛶'; button.title = 'Enter Fullscreen'; }
}