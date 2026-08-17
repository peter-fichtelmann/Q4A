// Wire a floating button so it also works while another finger is on the pitch.
//
// Browsers only synthesise mouse/click events for the *primary* touch point, so
// while the joystick finger is down a second finger tapping a button produces
// touch events but never a click, and the button looks dead. Acting on
// touchstart fixes that; preventDefault there suppresses the compatibility
// click, and the timestamp guard catches the browsers that fire it anyway.
export function onActivate(button, handler) {
  let lastTouch = 0;
  button.addEventListener('touchstart', (e) => {
    e.preventDefault();
    lastTouch = Date.now();
    handler(e);
  }, { passive: false });
  button.addEventListener('click', (e) => {
    e.preventDefault();
    if (Date.now() - lastTouch < 700) return;
    handler(e);
  });
}

export function getQueryParam(param) {
  const params = new URLSearchParams(window.location.search);
  return params.get(param);
}

export function screenTooSmallRatio() {
  const dpi = 120;
  const cmPerInch = 2.54;
  const pixelsPerCm = dpi / cmPerInch;
  const screenWidthCm = window.innerWidth / pixelsPerCm;
  const screenHeightCm = window.innerHeight / pixelsPerCm;
  const goodScreenWidthCm = 25;
  const goodScreenHeightCm = 15;
  const tooSmallRatio = Math.min(
    screenWidthCm / goodScreenWidthCm,
    screenHeightCm / goodScreenHeightCm,
  );
  return tooSmallRatio;
}