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