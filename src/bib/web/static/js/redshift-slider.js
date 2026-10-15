/** Redshift slider: 0.05 steps up to 10, then 0.1 steps up to 20. */

export const Z_MAX = 20;
const Z_BREAK = 10;
const Z_FINE = 0.05;
const Z_COARSE = 0.1;
const FINE_STEPS = Math.round(Z_BREAK / Z_FINE);

export function redshiftSliderMax() {
  return FINE_STEPS + Math.round((Z_MAX - Z_BREAK) / Z_COARSE);
}

export function zFromSlider(index) {
  const i = Math.max(0, Math.min(redshiftSliderMax(), Math.round(Number(index) || 0)));
  if (i <= FINE_STEPS) return Math.round(i * Z_FINE * 100) / 100;
  return Math.round((Z_BREAK + (i - FINE_STEPS) * Z_COARSE) * 10) / 10;
}

export function sliderFromZ(z) {
  const zz = Math.max(0, Math.min(Z_MAX, Number(z) || 0));
  if (zz <= Z_BREAK) return Math.round(zz / Z_FINE);
  return FINE_STEPS + Math.round((zz - Z_BREAK) / Z_COARSE);
}
