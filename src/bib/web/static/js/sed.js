/* SSP Explorer: population selection, SED + age-locked SSP plots, pinning. */
"use strict";

import { apiGet, apiUrl, reportError } from "./api.js";
import { PLOT_GRID, logAxisTicks } from "./plot-axis.js";
import { PlaybackClock, attachPlaybar, lerp, locate, syncRangeFill, syncAllRangeFills } from "./playback.js";
import { redshiftSliderMax, zFromSlider } from "./redshift-slider.js?v=1";
import {
  auxPlotsReady,
  cloneSeries,
  fetchSeries,
  hoverLabel,
  renderAuxPlots,
  scrubAuxPlots,
  setAuxAgeClickHandler,
  SUM_COLOR,
  UI_MAX_LOG_AGE,
  wantPinSum,
} from "./ssp-plots.js?v=16";

const $ = (id) => document.getElementById(id);
const css = (name) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const PIN_COLORS = ["#ffb454", "#7ed4a5", "#e08bff", "#ff7d94", "#5fd3e8", "#c9d45e", "#f0a3ff"];
const C_A_S = 2.99792458e18; // Å/s — ν (Hz) = C_A_S / λ(Å)
const GROUP_ORDER = ["JWST", "HST", "LSST", "Gaia", "2MASS", "SDSS", "Johnson-Cousins", "GALEX"];

// Vacuum rest wavelengths (Å). Observer-frame position is λ_rest × (1+z).
const LYMAN_SERIES = [
  { label: "Lyα", restA: 1215.67 },
  { label: "Lyβ", restA: 1025.72 },
  { label: null, restA: 972.54 },
  { label: null, restA: 949.74 },
  { label: null, restA: 937.80 },
  { label: "Ly∞", restA: 911.76, limit: true },
];
const BALMER_SERIES = [
  { label: "Hα", restA: 6564.61 },
  { label: "Hβ", restA: 4862.68 },
  { label: "Hγ", restA: 4341.68 },
  { label: "Hδ", restA: 4102.89 },
  { label: null, restA: 3971.20 },
  { label: "Ba∞", restA: 3646.01, limit: true },
];
const LYMAN_COLOR = "rgba(158, 190, 255, 0.85)";
const BALMER_COLOR = "rgba(255, 196, 110, 0.9)";
// Faint fills behind the *live* SED only: where its dust law acts, and where its IGM model acts.
const DUST_FILL = "rgba(255, 180, 84, 0.08)";
const IGM_FILL = "rgba(120, 150, 255, 0.10)";
const GHOST_OPACITY = 0.38; // the same SED drawn without its IGM factor
const TRAIL_DEX = 0.5; // log-age spacing of play-trail snapshots
// Rest-frame floor for the plot: BPASS atmospheres are not a useful model below this.
// Native files and the API still include the far UV.
const PLOT_WL_MIN_A = 50;

const state = {
  meta: null,
  filters: [],
  popId: null,
  frames: null, // current sed_frames payload (rest frame)
  series: null, // per-age tables for aux plots (1e6 Msun native)
  yLog10: null, // {lo, hi}: log10 flux range over all current frames (rest units)
  redshift: 0,
  dlMpc: null, // luminosity distance from the last photometry response
  xLog: true,
  xNu: false,
  yLog: true,
  userX: null,
  userY: null,
  viewMassLog: 6, // log10 mass the current userY lock was last aligned to
  pins: [],
  pinSeq: 0,
  syncPins: false,
  syncZ: false,
  sumPins: false,
  ticked: new Set(), // filter keys shown on the plot (bundled name or "custom:<file>")
  curveCache: new Map(), // key -> {wavelength, transmission, display_name, lambda_eff}
  photRows: [], // latest photometry rows incl. plot_level
  photFresh: false, // markers only drawn when this matches the plotted SED
  photKey: null,
  showPartial: false,
  showLyman: false,
  showBalmer: false,
  trailOn: false,
  trail: [], // [{logAge, y}] rest-frame snapshots while playing
  customFilters: [], // {name, text, autoTick}
  photRequest: 0,
  igmOn: true, // UI default on; the API default is "none"
  igmModel: "inoue14",
  igm: null, // {popId, z, model, transmission[]} on the display grid for the current z
  igmCache: new Map(), // "popId:model:z" -> transmission[]
  igmRequest: 0,
};

/* ------------------------------------------------------------------ selects */

function currentSelection() {
  return {
    release: $("sel-release").value,
    imf: $("sel-imf").value,
    poptype: document.querySelector('input[name="poptype"]:checked').value,
    z: $("sel-z").value,
    alpha: $("sel-alpha").value || null,
  };
}

function imfLabel(code) {
  const info = (state.meta?.populations || []).find((p) => p.imf === code)?.imf_info;
  return info?.label || code;
}

// Fiducial BPASS IMF: broken power-law α = 1.35, M_max = 300 M☉.
// v2.3 ships only this IMF; v2.2.1 has several, and this is the one shown first.
const DEFAULT_IMF = "imf135_300";

function setOptions(select, options, preferred = null) {
  const previous = select.value;
  select.innerHTML = "";
  for (const { value, label } of options) {
    const option = document.createElement("option");
    option.value = value;
    option.textContent = label;
    select.appendChild(option);
  }
  if (options.some((o) => o.value === previous)) select.value = previous;
  else if (preferred !== null && options.some((o) => o.value === preferred)) {
    select.value = preferred;
  }
}

function rebuildSelectors() {
  const releases = state.meta.releases;
  setOptions(
    $("sel-release"),
    releases.map((r) => ({ value: r.version, label: `${r.version}${r.name ? " — " + r.name : ""}` }))
  );
  const releaseId = releaseIdByVersion.get($("sel-release").value);
  const pops = state.meta.populations.filter((p) => p.release_id === releaseId);

  const imfs = [...new Set(pops.map((p) => p.imf))].sort((a, b) =>
    imfLabel(a).localeCompare(imfLabel(b), undefined, { numeric: true })
  );
  setOptions(
    $("sel-imf"),
    imfs.map((v) => ({ value: v, label: imfLabel(v) })),
    DEFAULT_IMF
  );
  const imf = $("sel-imf").value;

  const afterImf = pops.filter((p) => p.imf === imf);
  const typesAvail = new Set(afterImf.map((p) => p.pop_type));
  for (const input of document.querySelectorAll('input[name="poptype"]')) {
    input.disabled = !typesAvail.has(input.value);
  }
  let poptype = document.querySelector('input[name="poptype"]:checked').value;
  if (!typesAvail.has(poptype)) {
    poptype = [...typesAvail][0];
    document.querySelector(`input[name="poptype"][value="${poptype}"]`).checked = true;
  }

  const afterType = afterImf.filter((p) => p.pop_type === poptype);
  const zs = [...new Map(afterType.map((p) => [p.z_label, p.z_value])).entries()].sort(
    (a, b) => a[1] - b[1]
  );
  setOptions(
    $("sel-z"),
    zs.map(([label, value]) => ({ value: label, label: `${label}  (Z=${value})` })),
    "z020" // default to solar metallicity when available
  );
  const z = $("sel-z").value;

  const alphas = afterType
    .filter((p) => p.z_label === z)
    .map((p) => p.alpha_label)
    .filter((a, i, arr) => arr.indexOf(a) === i);
  const hasAlpha = alphas.some((a) => a !== null);
  $("grp-alpha").hidden = !hasAlpha;
  if (hasAlpha) {
    const sorted = alphas.sort((a, b) => (a === null ? -1 : b === null ? 1 : a.localeCompare(b)));
    setOptions(
      $("sel-alpha"),
      sorted.map((a) => ({ value: a ?? "", label: a === null ? "none (v2.2-style)" : a }))
    );
  } else {
    $("sel-alpha").value = "";
  }
}

let releaseIdByVersion = new Map();

function resolvePopulation() {
  const sel = currentSelection();
  const releaseId = releaseIdByVersion.get(sel.release);
  const match = state.meta.populations.find(
    (p) =>
      p.release_id === releaseId &&
      p.imf === sel.imf &&
      p.pop_type === sel.poptype &&
      p.z_label === sel.z &&
      (p.alpha_label ?? "") === (sel.alpha ?? "")
  );
  return match ? match.id : null;
}

/* ------------------------------------------------------------------- params */

function massMsun() {
  return Math.pow(10, Number($("sl-mass").value));
}

function dustParams() {
  const law = $("sel-dust").value;
  if (!law) return {};
  const params = { dust_law: law, ebv: Number($("sl-ebv").value) };
  const lawMeta = state.meta.dust_laws.find((l) => l.key === law);
  if (lawMeta && lawMeta.fixed_rv === null) params.rv = Number($("sl-rv").value);
  return params;
}

/** IGM model key sent to the API ("none" unless z > 0 and the toggle is on). */
function igmModelKey(z = state.redshift) {
  return z > 0 && state.igmOn ? state.igmModel : "none";
}

function igmParams(z = state.redshift) {
  const key = igmModelKey(z);
  return key === "none" ? {} : { igm: key };
}

function igmLabel(key) {
  return (state.meta?.igm_models || []).find((m) => m.key === key)?.label || key;
}

/** Descriptive bits identifying the current population + non-default params (no age). */
function labelBits() {
  const sel = currentSelection();
  const bits = [imfLabel(sel.imf), sel.z, sel.poptype];
  if (sel.alpha) bits.push(sel.alpha);
  const mass = Number($("sl-mass").value);
  if (mass !== 6) bits.push(`10^${mass.toFixed(1)} M☉`);
  const dust = dustParams();
  if (dust.dust_law) bits.push(`${dust.dust_law} E(B−V)=${dust.ebv}`);
  if (state.redshift > 0) bits.push(`z=${state.redshift.toFixed(2)}`);
  if (igmModelKey() !== "none") bits.push(`IGM ${igmLabel(state.igmModel)}`);
  return bits;
}

/* ----------------------------------------------------------------------- igm */

/** Transmission array aligned with state.frames.wavelength for redshift z, or null. */
function igmFactorFor(z) {
  const cur = state.igm;
  if (!(z > 0) || !state.igmOn || !cur) return null;
  if (cur.popId !== state.popId || cur.model !== state.igmModel || cur.z !== z) return null;
  return cur.transmission;
}

let igmTimer = null;

async function fetchIgm(popId, z, model) {
  const cacheKey = `${popId}:${model}:${z}`;
  const cached = state.igmCache.get(cacheKey);
  if (cached) return cached;
  const data = await apiGet("/igm_transmission", {
    population_id: popId,
    redshift: z,
    model,
  });
  state.igmCache.set(cacheKey, data.transmission);
  if (state.igmCache.size > 400) {
    state.igmCache.delete(state.igmCache.keys().next().value);
  }
  return data.transmission;
}

/** Fetch (or reuse) IGM transmission for the live SED, and for z-synced pins. */
async function ensureIgm() {
  const z = state.redshift;
  const token = ++state.igmRequest;
  try {
    if (!(z > 0) || !state.igmOn || state.popId === null) {
      state.igm = null;
    } else if (!igmFactorFor(z)) {
      const transmission = await fetchIgm(state.popId, z, state.igmModel);
      if (token !== state.igmRequest) return;
      state.igm = { popId: state.popId, z, model: state.igmModel, transmission };
    }
    if (state.syncZ && z > 0) {
      await Promise.all(
        state.pins
          .filter((pin) => pin.popId && pin.igmModel && pin.igmModel !== "none")
          .map((pin) => fetchIgm(pin.popId, z, pin.igmModel)),
      );
    }
  } catch (err) {
    if (token === state.igmRequest) reportError(err);
  }
}

function scheduleIgm() {
  clearTimeout(igmTimer);
  igmTimer = setTimeout(async () => {
    await ensureIgm();
    renderFrame(clock.t, true);
  }, 120);
}

function updateIgmUi() {
  const z = state.redshift;
  const note = $("igm-note");
  $("sel-igm").disabled = !state.igmOn;
  if (!state.igmOn) note.textContent = "Off — photometry blueward of Lyα(1+z) is not IGM-attenuated";
  else if (z > 0) note.textContent = `Lyα(1+z) = ${Math.round(1215.67 * (1 + z))} Å observed`;
  else note.textContent = "Applies blueward of Lyα(1+z) once z > 0";
}

/** Live SSP label in the same style as a pin (population bits + log-age). */
function liveLabel(logAge) {
  const bits = labelBits();
  if (Number.isFinite(logAge)) bits.push(`logA=${logAge.toFixed(2)}`);
  return bits.join(" · ");
}

/** Plotly named dashes → SVG stroke-dasharray, scaled by line width. */
function dashArray(dash, width) {
  const w = Math.max(Number(width) || 2, 1);
  switch (dash) {
    case "dot":
      return `${w} ${2 * w}`;
    case "dash":
      return `${4 * w} ${2 * w}`;
    case "longdash":
      return `${8 * w} ${2 * w}`;
    case "dashdot":
      return `${4 * w} ${2 * w} ${w} ${2 * w}`;
    default:
      return null;
  }
}

function sedLineSwatch(color, width, dash, opacity) {
  const w = Math.max(Number(width) || 2, 1.2);
  const dashAttr = dashArray(dash, w);
  const op = opacity == null ? 1 : opacity;
  return (
    `<svg class="sed-hover-swatch" width="40" height="12" viewBox="0 0 40 12" aria-hidden="true">` +
    `<line x1="1" y1="6" x2="39" y2="6" stroke="${color}" stroke-width="${w}" ` +
    `stroke-linecap="round"${dashAttr ? ` stroke-dasharray="${dashAttr}"` : ""} ` +
    `opacity="${op}"/></svg>`
  );
}

function formatHoverWl(xPlotted) {
  if (state.xNu) return `${Number(xPlotted).toExponential(3)} Hz`;
  return `${Math.round(xPlotted)} Å`;
}

function formatHoverFlux(y) {
  if (y == null || !Number.isFinite(y)) return "—";
  return Number(y).toPrecision(3);
}

function ensureSedHoverTip() {
  let el = $("sed-hover-tip");
  if (el) return el;
  el = document.createElement("div");
  el.id = "sed-hover-tip";
  el.className = "sed-hover-tip";
  el.hidden = true;
  document.body.appendChild(el);
  return el;
}

function hideSedHoverTip() {
  const el = $("sed-hover-tip");
  if (el) el.hidden = true;
}

function showSedHoverTip(pt, mouse) {
  const tr = pt.data;
  const meta = tr?.meta || pt.fullData?.meta;
  if (!meta?.sedLine) {
    hideSedHoverTip();
    return;
  }
  const line = tr.line || {};
  const note = meta.note ? `<span class="sed-hover-note">${meta.note}</span>` : "";
  const el = ensureSedHoverTip();
  el.innerHTML =
    `<div class="sed-hover-legend">${sedLineSwatch(line.color, line.width, line.dash, tr.opacity)}${note}</div>` +
    `<div>${formatHoverWl(pt.x)}</div>` +
    `<div>F<sub>λ</sub> = ${formatHoverFlux(pt.y)} L<sub>☉</sub>/Å</div>`;
  el.hidden = false;
  const pad = 14;
  let left = (mouse?.clientX ?? 0) + pad;
  let top = (mouse?.clientY ?? 0) + pad;
  const w = el.offsetWidth;
  const h = el.offsetHeight;
  if (left + w > window.innerWidth - 8) left = (mouse?.clientX ?? 0) - w - pad;
  if (top + h > window.innerHeight - 8) top = (mouse?.clientY ?? 0) - h - pad;
  el.style.left = `${Math.max(8, left)}px`;
  el.style.top = `${Math.max(8, top)}px`;
}

function plotWlStart(wavelength) {
  let i = 0;
  while (i < wavelength.length && wavelength[i] < PLOT_WL_MIN_A) i++;
  return i;
}

function clipRest(wavelength, y, igm) {
  const i = plotWlStart(wavelength);
  return {
    x: wavelength.slice(i),
    y: y.slice(i),
    igm: igm ? igm.slice(i) : null,
  };
}

/** Observer-frame SED for the plot: rest λ < 50 Å dropped. */
function observedPlot(restX, restY, z, igm) {
  const clipped = clipRest(restX, restY, igm);
  return toObserved(clipped.x, clipped.y, z, clipped.igm);
}

function pinPlotView(pin, t) {
  const labeled = pinView(pin, t);
  const restX = pin.frames?.wavelength;
  const restY = pinRestY(pin, t);
  if (restX && restY) {
    const view = observedPlot(restX, restY, pinObservedZ(pin), pinIgmFactor(pin));
    return { ...view, label: labeled.label };
  }
  return labeled;
}

function sedLineTrace({ uid, observedA, y, color, width, name, note, opacity, dash }) {
  return {
    uid,
    x: spectralXs(copyArr(observedA)),
    y: copyArr(y),
    name,
    showlegend: false,
    mode: "lines",
    opacity: opacity ?? 1,
    line: { color, width, dash: dash || "solid" },
    hoverinfo: "none",
    meta: { sedLine: true, note: note || "" },
  };
}

/* -------------------------------------------------------------------- frames */

let framesToken = 0;

async function loadFrames() {
  const popId = resolvePopulation();
  if (popId === null) return;
  const needSeries = popId !== state.popId || !state.series;
  state.popId = popId;
  const token = ++framesToken;
  try {
    const [data, series] = await Promise.all([
      apiGet(`/populations/${popId}/sed_frames`, {
        mass: massMsun(),
        ...dustParams(),
      }),
      needSeries ? fetchSeries(popId) : Promise.resolve(null),
    ]);
    if (token !== framesToken) return; // superseded
    state.frames = data;
    if (series) state.series = series;
    state.yLog10 = framesLogRange(data);
    clearTrail();
    updateTrailUi();
    invalidatePhotometry();
    await ensureIgm();
    if (token !== framesToken) return;
    renderFrame(clock.t, true);
    schedulePhotometry();
  } catch (err) {
    reportError(err);
  }
}

function framesLogRange(payload) {
  const i0 = plotWlStart(payload.wavelength || []);
  let lo = Infinity,
    hi = -Infinity;
  for (const frame of payload.frames) {
    const flux = frame.flux;
    for (let i = i0; i < flux.length; i++) {
      const v = flux[i];
      if (v > 0) {
        if (v < lo) lo = v;
        if (v > hi) hi = v;
      }
    }
  }
  lo = Math.max(lo, hi * 1e-12);
  return { lo: Math.log10(lo), hi: Math.log10(hi) };
}

/* ------------------------------------------------------- frame interpolation */

function interpFromFrames(payload, t) {
  const frames = payload.frames;
  const ageIdx = (t * (UI_MAX_LOG_AGE - 6)) / 0.1;
  const logAges = frames.map((f) => f.age_index);
  const [i0, i1, w] = locate(logAges, ageIdx);
  const f0 = frames[i0].flux;
  const f1 = frames[i1].flux;
  const y = new Array(f0.length);
  for (let i = 0; i < f0.length; i++) {
    const a = f0[i],
      b = f1[i];
    if (a > 0 && b > 0) y[i] = Math.pow(10, lerp(Math.log10(a), Math.log10(b), w));
    else y[i] = w < 0.5 ? a : b;
    if (!(y[i] > 0)) y[i] = null;
  }
  return { y, i0, i1, w, logAge: 6 + ageIdx * 0.1 };
}

/* ------------------------------------------------------------- play trail */

function logAgeFromT(t) {
  return 6 + t * (UI_MAX_LOG_AGE - 6);
}

function tFromLogAge(logAge) {
  return (logAge - 6) / (UI_MAX_LOG_AGE - 6);
}

function clearTrail() {
  state.trail = [];
}

function pruneTrail(logAge) {
  if (logAge <= 6.001) {
    state.trail = [];
    return;
  }
  state.trail = state.trail.filter((s) => s.logAge < logAge);
}

function harvestTrail(logAge) {
  if (!state.trailOn || state.pins.length || !state.frames) return;
  const mark = Math.floor(logAge / TRAIL_DEX + 1e-9) * TRAIL_DEX;
  if (mark < 6 || logAge - mark < 0.04) return;
  if (state.trail.some((s) => Math.abs(s.logAge - mark) < 0.01)) return;
  const { y } = interpFromFrames(state.frames, tFromLogAge(mark));
  state.trail.push({ logAge: mark, y: y.slice() });
  state.trail.sort((a, b) => a.logAge - b.logAge);
}

/** Same hue as the current SED; brightness/saturation follow log-age (not a
 *  stretching min–max, so the first snapshot does not vanish when the next
 *  one appears). Floor is high enough to read on the dark plot. */
function trailStyle(logAge) {
  const t = Math.min(1, Math.max(0, (logAge - 6) / (UI_MAX_LOG_AGE - 6)));
  return {
    color: `hsla(210, ${Math.round(44 + 36 * t)}%, ${Math.round(38 + 16 * t)}%, ${(0.58 + 0.32 * t).toFixed(2)})`,
    width: 1.05 + 0.45 * t,
  };
}

function updateTrailUi() {
  const box = $("chk-trail");
  const pinBtn = $("btn-pin");
  if (!box || !pinBtn) return;
  const pinned = state.pins.length > 0;
  if (pinned && state.trailOn) {
    state.trailOn = false;
    box.checked = false;
    clearTrail();
  }
  box.disabled = pinned;
  box.title = pinned
    ? "Remove pinned SSPs to trail ages while playing"
    : "While playing, leave a snapshot every 0.5 dex of log-age. Same hue; older frames fade.";
  pinBtn.disabled = state.trailOn;
  pinBtn.title = state.trailOn
    ? "Turn off trail snapshots to pin an SSP"
    : "Keep this SSP on every visible plot while you change parameters";
}

/* Flat ΛCDM luminosity distance — same H0, Ωm as the server (bib.science.redshift). */
const _dlCache = new Map();

const _univCache = new Map();

/** Age of the Universe at redshift z, same flat ΛCDM as the luminosity distance. */
function universeAgeYr(z) {
  const zz = Math.max(0, Number(z) || 0);
  const key = zz.toFixed(3);
  if (_univCache.has(key)) return _univCache.get(key);
  const h0 = state.meta?.cosmology?.h0 ?? 70;
  const om0 = state.meta?.cosmology?.om0 ?? 0.3;
  const ol = 1 - om0;
  const invHyr = 9.777922166e11 / h0;
  const E = (zi) => Math.sqrt(om0 * (1 + zi) ** 3 + ol);
  const zMax = 1e4;
  const n = 480;
  const a = Math.log(1 + zz);
  const b = Math.log(1 + zMax);
  const d = (b - a) / n;
  let integ = 0.5 / E(zz);
  for (let i = 1; i < n; i++) integ += 1 / E(Math.exp(a + i * d) - 1);
  integ += 0.5 / E(zMax);
  const age = invHyr * integ * d;
  _univCache.set(key, age);
  return age;
}

function formatCosmoAge(yr) {
  if (yr >= 1e9) return `${(yr / 1e9).toFixed(2)} Gyr`;
  if (yr >= 1e6) return `${(yr / 1e6).toFixed(1)} Myr`;
  return `${yr.toExponential(1)} yr`;
}

function updateCosmoWarn(logAge) {
  const z = zFromSlider($("sl-redshift")?.value);
  const ageYr = 10 ** logAge;
  const univYr = universeAgeYr(z);
  const limitYr = z <= 0 ? 10 ** UI_MAX_LOG_AGE : univYr;
  const tooOld = ageYr > limitYr;
  const label = state.meta?.cosmology?.label || "flat ΛCDM, H₀=70 km/s/Mpc, Ωm=0.3";
  const tip = tooOld
    ? `SSP is older than the Universe at this redshift. Population age ${formatCosmoAge(ageYr)}; the Universe at z=${z.toFixed(2)} is ${formatCosmoAge(univYr)} old (${label}).`
    : "";
  for (const id of ["sl-age", "sl-redshift"]) {
    const el = $(id);
    if (el) el.classList.toggle("is-cosmowarn", tooOld);
  }
  const scrub = document.querySelector('#sed-playbar [data-role="scrub"]');
  if (scrub) scrub.classList.toggle("is-cosmowarn", tooOld);
  for (const id of ["age-bang", "z-bang", "play-bang"]) {
    const bang = $(id);
    if (!bang) continue;
    bang.hidden = !tooOld;
    bang.title = tip;
  }
}

function luminosityDistanceMpc(z) {
  if (!(z > 0)) return 1e-5; // 10 pc
  const key = z.toFixed(4);
  if (_dlCache.has(key)) return _dlCache.get(key);
  const h0 = state.meta?.cosmology?.h0 ?? 70;
  const om0 = state.meta?.cosmology?.om0 ?? 0.3;
  const ol = 1 - om0;
  const dh = 299792.458 / h0; // Mpc
  const n = Math.max(48, Math.ceil(z * 80));
  const dz = z / n;
  const E = (zi) => Math.sqrt(om0 * (1 + zi) ** 3 + ol);
  let integ = 0.5 / E(0);
  for (let i = 1; i < n; i++) integ += 1 / E(i * dz);
  integ += 0.5 / E(z);
  const dl = (1 + z) * dh * integ * dz;
  _dlCache.set(key, dl);
  return dl;
}

/** (10 pc / D_L)² — the missing many-orders-of-magnitude dimming. */
function distanceDimming(z) {
  if (!(z > 0)) return 1;
  const dlPc = luminosityDistanceMpc(z) * 1e6;
  return (10 / dlPc) ** 2;
}

/** Subtract from rest-frame log10 flux to get the plotted observer-frame value. */
function fluxLogShift(z) {
  if (!(z > 0)) return 0;
  return Math.log10(1 + z) - Math.log10(distanceDimming(z));
}

/** Rest-frame L_λ → observer frame: λ×(1+z), L_λ × (10 pc/D_L)² / (1+z), × IGM transmission. */
function toObserved(xArr, yArr, z, igm = null) {
  if (!z) return { x: xArr, y: yArr };
  const s = 1 + z;
  const scale = distanceDimming(z) / s;
  const useIgm = igm && igm.length === yArr.length;
  return {
    x: xArr.map((v) => v * s),
    y: yArr.map((v, i) =>
      v === null || v === undefined ? null : v * scale * (useIgm ? igm[i] : 1),
    ),
  };
}

/* --------------------------------------------------------------------- plot */

function groupRank(group) {
  if (group === "custom") return 1000;
  const i = GROUP_ORDER.indexOf(group);
  return i === -1 ? 500 : i;
}

function normalizeTransmission(tr) {
  let peak = 0;
  for (const v of tr) if (v > peak) peak = v;
  if (!(peak > 0)) return tr;
  return tr.map((v) => v / peak);
}

function spectralX(lambdaA) {
  if (lambdaA == null) return lambdaA;
  return state.xNu ? C_A_S / lambdaA : lambdaA;
}

function spectralXs(lambdas) {
  return state.xNu ? lambdas.map((l) => C_A_S / l) : lambdas;
}

function annotationX(lambdaA) {
  const x = spectralX(lambdaA);
  return state.xLog ? Math.log10(x) : x;
}

/** Wavelength → hue (UV violet → IR red). Kept pale so passbands don't look like SEDs. */
function filterHue(lambdaEff) {
  const t = Math.min(1, Math.max(0, (Math.log10(lambdaEff) - 3.45) / 0.95));
  return Math.round(285 * (1 - t));
}

function filterColor(lambdaEff, alpha = 1) {
  const hue = filterHue(lambdaEff);
  return alpha >= 1 ? `hsl(${hue}, 28%, 78%)` : `hsla(${hue}, 28%, 78%, ${alpha})`;
}

function filterMarkerColor(lambdaEff) {
  return `hsl(${filterHue(lambdaEff)}, 42%, 72%)`;
}

function tickedCurves() {
  const out = [];
  for (const key of state.ticked) {
    const curve = state.curveCache.get(key);
    if (curve) out.push({ key, curve });
  }
  return out;
}

function addSeriesOverlays(layout, xExtent, lines, color) {
  const stretch = 1 + state.redshift;
  const xLo = Math.min(xExtent[0], xExtent[1]);
  const xHi = Math.max(xExtent[0], xExtent[1]);
  for (const line of lines) {
    const obsA = line.restA * stretch;
    const x = spectralX(obsA);
    if (!(x >= xLo && x <= xHi)) continue;
    layout.shapes.push({
      type: "line",
      xref: "x",
      yref: "paper",
      x0: x,
      x1: x,
      y0: 0,
      y1: 1,
      line: {
        color,
        width: line.limit ? 1 : 1.15,
        dash: line.limit ? "dot" : "dash",
      },
      layer: "below",
    });
    if (!line.label) continue;
    layout.annotations.push({
      x: annotationX(obsA),
      y: 1,
      yref: "paper",
      yanchor: "bottom",
      xanchor: "center",
      text: line.label,
      showarrow: false,
      font: { size: 10, color },
      bgcolor: "rgba(10,14,22,0.55)",
      yshift: 4,
    });
  }
}

/* ------------------------------------------------------- attenuation marks */
/*
 * Dust and IGM are properties of *each* SED, not of the plot: every pin keeps the
 * z, dust law and IGM model it was pinned with, so the live toggles must not
 * change how a pin is marked. Each visible SED therefore gets its own marks, in
 * its own colour:
 *   - a faint "ghost" copy of itself without the IGM factor, so the attenuation
 *     is visible as the gap between ghost and curve.
 * Only the live SED additionally gets at most three vertical edge lines (dust
 * window blue/red, Lyα) and faint fills over the regions where its dust law and
 * IGM model act (IGM takes precedence where both do). Pins are not given their
 * own edge lines — that became a forest as soon as more than one SED was on.
 */

/** Observed-frame wavelengths at which dust / IGM act on one SED (null = not active). */
function attenuationSpec({ z, dust, igmKey, igmActive }) {
  const stretch = 1 + (z > 0 ? z : 0);
  const spec = { dustWindow: null, dustLabel: null, lya: null, igmLabel: null };
  if (dust?.dust_law && dust.ebv > 0) {
    const lawMeta = state.meta?.dust_laws?.find((l) => l.key === dust.dust_law);
    if (lawMeta?.valid_range_a) {
      spec.dustWindow = [lawMeta.valid_range_a[0] * stretch, lawMeta.valid_range_a[1] * stretch];
      spec.dustLabel = `${lawMeta.label || dust.dust_law} E(B−V)=${dust.ebv}`;
    }
  }
  if (igmKey && igmKey !== "none" && igmActive) {
    spec.lya = 1215.67 * stretch;
    spec.igmLabel = igmLabel(igmKey);
  }
  return spec;
}

function liveAttenuationSpec() {
  const z = state.redshift;
  return attenuationSpec({
    z,
    dust: dustParams(),
    igmKey: igmModelKey(z),
    igmActive: Boolean(igmFactorFor(z)),
  });
}

/** Faint fills behind the live SED where its dust law / IGM model act. */
function addAttenuationRegions(layout, xExtent) {
  const xLo = Math.min(xExtent[0], xExtent[1]);
  const xHi = Math.max(xExtent[0], xExtent[1]);
  const fill = (wlA, wlB, color) => {
    let x0 = spectralX(wlA);
    let x1 = spectralX(wlB);
    if (x0 > x1) [x0, x1] = [x1, x0];
    x0 = Math.max(x0, xLo);
    x1 = Math.min(x1, xHi);
    if (!(x1 > x0)) return;
    layout.shapes.push({
      type: "rect",
      xref: "x",
      yref: "paper",
      x0,
      x1,
      y0: 0,
      y1: 1,
      fillcolor: color,
      line: { width: 0 },
      layer: "below",
    });
  };
  const spec = liveAttenuationSpec();
  if (spec.dustWindow) {
    const [lo, hi] = spec.dustWindow;
    fill(spec.lya != null ? Math.max(lo, spec.lya) : lo, hi, DUST_FILL);
  }
  if (spec.lya != null) fill(1e-6, spec.lya, IGM_FILL);
}

/** Full-height vertical line on the hidden passband axis so it can carry hover text. */
function edgeTrace(wl, color, dash, text) {
  const x = spectralX(wl);
  return {
    x: [x, x],
    y: [0, 5],
    yaxis: "y2",
    mode: "lines",
    showlegend: false,
    line: { color, width: 1, dash },
    text: [text, text],
    hovertemplate: "%{text}<extra></extra>",
  };
}

/** At most three full-height lines for the live SED: dust-window edges and Lyα. */
function attenuationEdgeTraces() {
  const traces = [];
  const spec = liveAttenuationSpec();
  const color = css("--brand-primary") || "#5aa9ff";
  if (spec.dustWindow) {
    const [lo, hi] = spec.dustWindow.map(Math.round);
    const text = `${spec.dustLabel}<br>applied ${lo}–${hi} Å (observed)`;
    for (const wl of spec.dustWindow) traces.push(edgeTrace(wl, color, "dot", text));
  }
  if (spec.lya != null) {
    traces.push(
      edgeTrace(
        spec.lya,
        color,
        "dash",
        `IGM ${spec.igmLabel}<br>applied below Lyα(1+z) = ${Math.round(spec.lya)} Å`,
      ),
    );
  }
  return traces;
}

/** The SED without its IGM factor, drawn only where that factor bites (< 0.999). */
function igmGhostTrace(restX, restY, z, igm, color, uid) {
  const clipped = clipRest(restX, restY, igm);
  restX = clipped.x;
  restY = clipped.y;
  igm = clipped.igm;
  if (!igm || !(z > 0) || igm.length !== restY.length) return null;
  let last = -1;
  for (let i = 0; i < igm.length; i++) if (igm[i] < 0.999) last = i;
  if (last < 0) return null;
  const end = Math.min(restX.length, last + 3);
  const view = toObserved(restX.slice(0, end), restY.slice(0, end), z, null);
  return sedLineTrace({
    uid,
    observedA: view.x,
    y: view.y,
    color,
    width: 1,
    name: "no IGM",
    note: "no IGM",
    opacity: GHOST_OPACITY,
  });
}

/** Rest-frame flux of a pin at playhead t (interpolated when age-synced, else as pinned). */
function pinRestY(pin, t) {
  if (state.syncPins && pin.frames) return interpFromFrames(pin.frames, t).y;
  return pin.restY || null;
}

function pinObservedZ(pin) {
  return state.syncZ ? state.redshift : pin.z;
}

/** IGM factor on the pin's rest grid at the z it is currently drawn at, or null. */
function pinIgmFactor(pin) {
  const z = pinObservedZ(pin);
  if (!(z > 0) || !pin.igmModel || pin.igmModel === "none") return null;
  if (!state.syncZ) return pin.igm;
  return state.igmCache.get(`${pin.popId}:${pin.igmModel}:${z}`) || null;
}

function plotLayout(xExtent, yLogExtent) {
  const text = css("--brand-text") || "#e7ecf3";
  const grid = PLOT_GRID;
  const z = state.redshift;
  const seriesOn = state.showLyman || state.showBalmer;

  const xLabel = state.xNu
    ? z > 0
      ? "observed frequency (Hz)"
      : "frequency (Hz)"
    : z > 0
      ? "observed wavelength (Å)"
      : "wavelength (Å)";
  const xRange = state.userX
    ? state.userX.slice()
    : state.xLog
      ? [Math.log10(xExtent[0]), Math.log10(xExtent[1])]
      : [xExtent[0] * 0.98, xExtent[1] * 1.02];
  const yRange = state.userY
    ? state.userY.slice()
    : state.yLog
      ? [yLogExtent[0] - 0.05, yLogExtent[1] + 0.3]
      : [0, Math.pow(10, yLogExtent[1]) * 1.08];
  const xLogSpan = state.xLog ? xRange[1] - xRange[0] : Math.log10(xExtent[1]) - Math.log10(xExtent[0]);
  const yLogSpan = state.yLog ? yRange[1] - yRange[0] : yLogExtent[1] - yLogExtent[0] + 0.35;
  const xaxis = {
    type: state.xLog ? "log" : "linear",
    title: { text: xLabel, standoff: 14 },
    range: xRange,
    autorange: false,
    gridcolor: grid,
    gridwidth: 1,
    zeroline: false,
    ...(state.xLog ? logAxisTicks(xLogSpan) : {}),
  };

  const yaxis = {
    type: state.yLog ? "log" : "linear",
    title: {
      text:
        z > 0
          ? "observed F<sub>λ</sub> (L<sub>☉</sub>/Å × (10 pc/D<sub>L</sub>)<sup>2</sup>)"
          : "F<sub>λ</sub> (L<sub>☉</sub> / Å)",
    },
    gridcolor: grid,
    gridwidth: 1,
    zeroline: false,
    exponentformat: "power",
    range: yRange,
    autorange: false,
    ...(state.yLog ? logAxisTicks(yLogSpan) : {}),
  };

  // Passbands live on a hidden second axis: T=0–1 occupies the lower 20%.
  const layout = {
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { color: text, size: 12.5 },
    margin: { l: 70, r: 16, t: seriesOn ? 32 : 10, b: 52 },
    shapes: [],
    xaxis,
    yaxis,
    yaxis2: {
      overlaying: "y",
      side: "right",
      range: [0, 5],
      visible: false,
      fixedrange: true,
    },
    showlegend: false,
    hovermode: "closest",
    hoverlabel: hoverLabel(),
    annotations: [],
  };

  addAttenuationRegions(layout, xExtent);
  if (state.showLyman) addSeriesOverlays(layout, xExtent, LYMAN_SERIES, LYMAN_COLOR);
  if (state.showBalmer) addSeriesOverlays(layout, xExtent, BALMER_SERIES, BALMER_COLOR);

  // Small floor label at each ticked passband's effective wavelength.
  for (const { curve } of tickedCurves()) {
    layout.annotations.push({
      x: annotationX(curve.lambda_eff),
      y: 1.18,
      yref: "y2",
      text: curve.display_name,
      showarrow: false,
      font: { size: 9.5, color: filterColor(curve.lambda_eff) },
      bgcolor: "rgba(10,14,22,0.55)",
    });
  }
  return layout;
}

function copyArr(arr) {
  const out = new Array(arr.length);
  for (let i = 0; i < arr.length; i++) out[i] = arr[i];
  return out;
}

function pinView(pin, t) {
  if (!state.syncPins && !state.syncZ) {
    return { x: pin.frozen.x, y: pin.frozen.y, label: pin.frozen.label };
  }
  const restY = pinRestY(pin, t);
  if (!restY || !pin.frames) {
    return { x: pin.frozen.x, y: pin.frozen.y, label: pin.frozen.label };
  }
  const logAge =
    state.syncPins && pin.frames ? interpFromFrames(pin.frames, t).logAge : pin.logAge;
  const view = toObserved(pin.frames.wavelength, restY, pinObservedZ(pin), pinIgmFactor(pin));
  const linked = [state.syncPins && "age", state.syncZ && "z"].filter(Boolean);
  const mark = linked.length ? ` 🔗${linked.join("+")}` : "";
  return { ...view, label: `${pin.basebits} · logA=${Number(logAge).toFixed(2)}${mark}` };
}

function addFluxOnto(xBase, yAcc, xSrc, ySrc) {
  const same =
    xBase.length === xSrc.length && xBase[0] === xSrc[0] && xBase[xBase.length - 1] === xSrc[xSrc.length - 1];
  if (same) {
    for (let i = 0; i < yAcc.length; i++) {
      const a = yAcc[i];
      const b = ySrc[i];
      const na = a == null || !Number.isFinite(a);
      const nb = b == null || !Number.isFinite(b);
      const s = (na ? 0 : a) + (nb ? 0 : b);
      yAcc[i] = s > 0 ? s : null;
    }
    return yAcc;
  }
  for (let i = 0; i < xBase.length; i++) {
    const [i0, i1, w] = locate(xSrc, xBase[i]);
    const a = ySrc[i0];
    const b = ySrc[i1];
    let add = 0;
    if (a > 0 && b > 0) add = Math.pow(10, lerp(Math.log10(a), Math.log10(b), w));
    else if (a > 0 || b > 0) add = w < 0.5 ? a || 0 : b || 0;
    const cur = yAcc[i];
    const s = (cur == null || !Number.isFinite(cur) ? 0 : cur) + add;
    yAcc[i] = s > 0 ? s : null;
  }
  return yAcc;
}

/** Sum of the live SED plus every pin as currently drawn (frozen or age-synced). */
function sumVisibleSed(t, live) {
  if (!state.pins.length || !live?.y?.length) return null;
  const x = copyArr(live.x);
  const y = copyArr(live.y);
  for (const pin of state.pins) {
    const view = pinView(pin, t);
    if (!view?.y?.length) continue;
    addFluxOnto(x, y, view.x, view.y);
  }
  return { x, y };
}

function noteAxisLock(ev, lock, prefix) {
  if (!ev) return;
  if (ev[`${prefix}.autorange`]) lock[prefix] = null;
  else if (ev[`${prefix}.range[0]`] != null) {
    lock[prefix] = [+ev[`${prefix}.range[0]`], +ev[`${prefix}.range[1]`]];
  } else if (Array.isArray(ev[`${prefix}.range`])) {
    lock[prefix] = ev[`${prefix}.range`].map(Number);
  }
}

function bindSedViewLock(host) {
  if (!host || host._bibViewLock || typeof host.on !== "function") return;
  host._bibViewLock = true;
  host.on("plotly_relayout", (ev) => {
    hideSedHoverTip();
    if (!ev || host._bibApplying) return;
    const box = { xaxis: state.userX, yaxis: state.userY };
    noteAxisLock(ev, box, "xaxis");
    noteAxisLock(ev, box, "yaxis");
    state.userX = box.xaxis;
    state.userY = box.yaxis;
  });
  host.on("plotly_hover", (ev) => {
    const pt = ev?.points?.[0];
    if (!pt) {
      hideSedHoverTip();
      return;
    }
    showSedHoverTip(pt, ev.event);
  });
  host.on("plotly_unhover", hideSedHoverTip);
  host.addEventListener("mouseleave", hideSedHoverTip);
}

/** Drop any zoom/pan lock so the next draw frames the current SED again. */
function recentreSedView() {
  state.userX = null;
  state.userY = null;
  renderFrame(clock.t);
}

/**
 * Carry a zoomed/panned view along with the data when a slider rescales it:
 * wavelengths × xFactor (ν axes move the other way), flux × yFactor. Without
 * this a deliberate zoom is left behind the moment the redshift or mass moves.
 */
function shiftLockedView(xFactor, yFactor) {
  if (state.userX && xFactor > 0 && xFactor !== 1) {
    const f = state.xNu ? 1 / xFactor : xFactor;
    state.userX = state.xLog
      ? state.userX.map((v) => v + Math.log10(f))
      : state.userX.map((v) => v * f);
  }
  if (state.userY && yFactor > 0 && yFactor !== 1) {
    state.userY = state.yLog
      ? state.userY.map((v) => v + Math.log10(yFactor))
      : state.userY.map((v) => v * yFactor);
  }
}

/** Plotly's own "home" restores the ranges of the *first* draw (z=0, first
 * population), which our relayout hook would record as a user zoom — the
 * SED could then sit permanently off-screen. Replace it with a recentre. */
const SED_PLOT_CONFIG = {
  responsive: true,
  displaylogo: false,
  modeBarButtonsToRemove: ["select2d", "lasso2d", "autoScale2d", "resetScale2d"],
  modeBarButtonsToAdd: [
    {
      name: "recentreSed",
      title: "Recentre axes on the current SED",
      icon: Plotly.Icons.home,
      click: () => recentreSedView(),
    },
  ],
};

function drawSedFrame(t) {
  if (!state.frames) return;
  hideSedHoverTip();
  const { y, logAge } = interpFromFrames(state.frames, t);
  const cur = observedPlot(state.frames.wavelength, y, state.redshift, igmFactorFor(state.redshift));
  const liveName = liveLabel(logAge);

  // ---- axis extents: union of current view, pins, and marker levels
  let xMin = cur.x[0],
    xMax = cur.x[cur.x.length - 1];
  const zShift = fluxLogShift(state.redshift);
  let yLo = state.yLog10.lo - zShift,
    yHi = state.yLog10.hi - zShift;

  const traces = attenuationEdgeTraces();
  for (const pin of state.pins) {
    const view = pinPlotView(pin, t);
    xMin = Math.min(xMin, view.x[0], view.x[view.x.length - 1]);
    xMax = Math.max(xMax, view.x[0], view.x[view.x.length - 1]);
    if (pin.yLog10) {
      const shift = fluxLogShift(pinObservedZ(pin));
      yLo = Math.min(yLo, pin.yLog10.lo - shift);
      yHi = Math.max(yHi, pin.yLog10.hi - shift);
    }
    const restY = pinRestY(pin, t);
    const ghost =
      restY &&
      igmGhostTrace(
        pin.frames.wavelength,
        restY,
        pinObservedZ(pin),
        pinIgmFactor(pin),
        pin.color,
        `pin-ghost-${pin.id}`,
      );
    if (ghost) traces.push(ghost);
    traces.push(
      sedLineTrace({
        uid: `pin-${pin.id}`,
        observedA: view.x,
        y: view.y,
        color: pin.color,
        width: 1.3,
        name: view.label,
      }),
    );
  }

  if (state.trailOn && state.trail.length && !state.pins.length) {
    for (const snap of state.trail) {
      const view = observedPlot(
        state.frames.wavelength,
        snap.y,
        state.redshift,
        igmFactorFor(state.redshift),
      );
      const { color, width } = trailStyle(snap.logAge);
      traces.push(
        sedLineTrace({
          observedA: view.x,
          y: view.y,
          color,
          width,
          name: `logA=${snap.logAge.toFixed(1)}`,
        }),
      );
    }
  }

  const liveColor = css("--brand-primary") || "#5aa9ff";
  const liveGhost = igmGhostTrace(
    state.frames.wavelength,
    y,
    state.redshift,
    igmFactorFor(state.redshift),
    liveColor,
    "live-ghost",
  );
  if (liveGhost) traces.push(liveGhost);
  traces.push(
    sedLineTrace({
      uid: "live-sed",
      observedA: cur.x,
      y: cur.y,
      color: liveColor,
      width: 2.1,
      name: liveName,
    }),
  );

  if (wantPinSum(state)) {
    const summed = sumVisibleSed(t, cur);
    if (summed) {
      traces.push(
        sedLineTrace({
          uid: "sum-sed",
          observedA: summed.x,
          y: summed.y,
          color: SUM_COLOR,
          width: 2.8,
          name: "Σ visible spectra",
        }),
      );
    }
  }

  // ---- ticked filter passbands hugging the plot floor (hidden y2 axis)
  for (const { key, curve } of tickedCurves()) {
    const T = normalizeTransmission(curve.transmission);
    const row = state.photFresh ? state.photRows.find((r) => r.key === key) : null;
    const flagged = Boolean(row && rowFlags(row).length);
    traces.push({
      x: spectralXs(curve.wavelength),
      y: T,
      yaxis: "y2",
      name: curve.display_name,
      showlegend: false,
      mode: "lines",
      line: { color: filterColor(curve.lambda_eff), width: flagged ? 1.6 : 1.2, dash: flagged ? "dash" : "solid" },
      fill: "tozeroy",
      fillcolor: filterColor(curve.lambda_eff, flagged ? 0.12 : 0.22),
      text: curve.wavelength.map((a) =>
        state.xNu ? `${(C_A_S / a).toExponential(3)} Hz` : `${Math.round(a)} Å`,
      ),
      hovertemplate:
        `<b>${curve.display_name}</b>` +
        `<br>%{text} · T=%{y:.2f}` +
        (row ? `<br>${attenuationText(row)}` : "") +
        `<extra></extra>`,
    });
  }

  // ---- measured photometry as points sitting on the SED
  // Only the calculation that matches this exact displayed SED is allowed
  // on the plot; stale markers hide the moment age/z/mass/dust change.
  const marks =
    state.photFresh && !clock.playing
      ? state.photRows.filter(
          (r) => state.ticked.has(r.key) && r.plot_level !== null && r.plot_level !== undefined
        )
      : [];
  if (marks.length) {
    traces.push({
      x: marks.map((r) => spectralX(r.lambda_eff)),
      y: marks.map((r) => r.plot_level * distanceDimming(state.redshift)),
      mode: "markers",
      showlegend: false,
      marker: {
        symbol: "diamond",
        size: 9.5,
        color: marks.map((r) => filterMarkerColor(r.lambda_eff)),
        line: { color: "#ffffff", width: 1 },
      },
      text: marks.map(
        (r) =>
          `<b>${r.display_name}</b>` +
          `<br>${state.redshift > 0 ? "m" : "M"}<sub>AB</sub> = ${r.ab_mag}` +
          `<br>${attenuationText(r)}`,
      ),
      hovertemplate: "%{text}<extra></extra>",
    });
    for (const r of marks) {
      const level = r.plot_level * distanceDimming(state.redshift);
      if (level > 0) yLo = Math.min(yLo, Math.log10(level));
    }
  }

  const xLo = state.xNu ? C_A_S / xMax : xMin;
  const xHi = state.xNu ? C_A_S / xMin : xMax;
  if (!$("panel-sed")?.hidden) {
    const host = $("sed-plot");
    host._bibApplying = true;
    Promise.resolve(
      Plotly.react("sed-plot", traces, plotLayout([xLo, xHi], [yLo, yHi]), SED_PLOT_CONFIG),
    ).then(() => {
      bindSedViewLock(host);
      setTimeout(() => {
        host._bibApplying = false;
      }, 0);
    });
  }
  renderColorKey(logAge);
  updateExportLinks();
}

function updateAgeChrome(t, w) {
  const logAge = logAgeFromT(t);
  const ageIdx = (logAge - 6) / 0.1;
  $("sl-age").value = String(ageIdx);
  syncRangeFill($("sl-age"));
  $("out-age").textContent = logAge.toFixed(2);
  updateCosmoWarn(logAge);
  $("interp-note").textContent =
    w > 0.02 && w < 0.98
      ? "Showing an interpolated frame (visual only) — photometry always uses true grid ages."
      : "On-grid age — this frame is exactly as published.";
}

function restyleLiveSed(cur, logAge, t) {
  const gd = $("sed-plot");
  if (!gd?.data) return false;
  const live = gd.data.findIndex((tr) => tr.uid === "live-sed");
  if (live < 0) return false;
  const liveName = liveLabel(logAge);
  const ys = [cur.y];
  const names = [liveName];
  const indices = [live];
  // Ghost copies (SED without IGM) also move with age; fall back to a full draw if absent.
  const pushGhost = (uid, restX, restY, z, igm) => {
    const j = gd.data.findIndex((tr) => tr.uid === uid);
    const ghost = igmGhostTrace(restX, restY, z, igm, "#000", uid);
    if ((j < 0) !== !ghost) return false;
    if (ghost) {
      ys.push(ghost.y);
      names.push("no IGM");
      indices.push(j);
    }
    return true;
  };
  const liveRest = interpFromFrames(state.frames, t).y;
  if (!pushGhost("live-ghost", state.frames.wavelength, liveRest, state.redshift, igmFactorFor(state.redshift))) {
    return false;
  }
  if (state.syncPins) {
    for (const pin of state.pins) {
      const j = gd.data.findIndex((tr) => tr.uid === `pin-${pin.id}`);
      if (j < 0) return false;
      const view = pinPlotView(pin, t);
      ys.push(view.y);
      names.push(view.label);
      indices.push(j);
      const restY = pinRestY(pin, t);
      if (
        restY &&
        !pushGhost(
          `pin-ghost-${pin.id}`,
          pin.frames.wavelength,
          restY,
          pinObservedZ(pin),
          pinIgmFactor(pin),
        )
      ) {
        return false;
      }
    }
  }
  if (wantPinSum(state)) {
    const sumIdx = gd.data.findIndex((tr) => tr.uid === "sum-sed");
    if (sumIdx < 0) return false;
    const summed = sumVisibleSed(t, cur);
    if (!summed) return false;
    ys.push(summed.y);
    names.push("Σ visible spectra");
    indices.push(sumIdx);
  }
  Plotly.restyle(gd, { y: ys, name: names }, indices);
  renderColorKey(logAge);
  return true;
}

let lastSedDrawMs = 0;

function renderFrame(t, initial = false) {
  if (!state.frames) return;
  const { y, w, logAge } = interpFromFrames(state.frames, t);
  const cur = observedPlot(state.frames.wavelength, y, state.redshift, igmFactorFor(state.redshift));
  updateAgeChrome(t, w);

  const playing = clock.playing;
  const now = performance.now();
  // Timeseries curves never change with age. While playing, only slide shapes.
  if (playing && !initial) {
    if (auxPlotsReady()) scrubAuxPlots(logAge);
  } else {
    renderAuxPlots(state, logAge);
  }

  // The SED actually changes with age — restyle the live curve, but not at 60 Hz.
  if (!initial && playing && !state.trailOn && now - lastSedDrawMs < 40) {
    return;
  }
  lastSedDrawMs = now;
  if (!initial && playing && !state.trailOn && restyleLiveSed(cur, logAge, t)) {
    updateExportLinks();
    return;
  }
  drawSedFrame(t);
}

/* --------------------------------------------------------------- photometry */

let photTimer = null;

function photometryKey() {
  return JSON.stringify({
    popId: state.popId,
    ageIndex: Math.round(Number($("sl-age").value)),
    mass: massMsun(),
    ...dustParams(),
    redshift: state.redshift,
    ...igmParams(),
  });
}

function hidePhotometryMarkers() {
  const gd = $("sed-plot");
  if (!gd || !gd.data) return;
  let changed = false;
  for (const trace of gd.data) {
    if (trace.mode === "markers") {
      trace.x = [];
      trace.y = [];
      trace.text = [];
      changed = true;
    }
  }
  if (changed) Plotly.redraw(gd);
}

function invalidatePhotometry() {
  if (state.photFresh) hidePhotometryMarkers();
  state.photFresh = false;
}

function schedulePhotometry() {
  clearTimeout(photTimer);
  photTimer = null;
  if (clock.playing || state.popId === null) return;
  photTimer = setTimeout(runPhotometry, 380);
}

async function runPhotometry() {
  if (state.popId === null || clock.playing) return;
  const key = photometryKey();
  const ageIndex = Math.round(Number($("sl-age").value));
  const token = ++state.photRequest;
  try {
    const data = await apiGet("/photometry", {
      population_id: state.popId,
      age_index: ageIndex,
      mass: massMsun(),
      ...dustParams(),
      ...(state.redshift > 0 ? { redshift: state.redshift } : {}),
      ...igmParams(),
    });
    if (token !== state.photRequest) return;
    state.dlMpc = data.luminosity_distance_mpc;
    const rows = data.photometry.map((r) => ({ ...r, key: r.filter, isCustom: false }));
    for (const custom of state.customFilters) {
      const result = await customPhotometry(custom, ageIndex);
      if (result) rows.push(result);
    }
    if (token !== state.photRequest || clock.playing) return;
    // Drop the result if the user has already moved on; recalc for the new SED.
    if (key !== photometryKey()) {
      schedulePhotometry();
      return;
    }
    state.photRows = rows;
    state.photKey = key;
    state.photFresh = true;
    $("phot-age").textContent = `log age ${(6 + ageIndex * 0.1).toFixed(1)}`;
    renderPhotTable();
    updateFrameNotes();
    renderFrame(clock.t); // markers appear only now
  } catch (err) {
    reportError(err);
  }
}

function renderPhotTable() {
  const partial = state.photRows.filter((r) => r.coverage < 0.999);
  const visible = (
    state.showPartial ? state.photRows : state.photRows.filter((r) => r.coverage >= 0.999)
  ).slice().sort((a, b) => {
    const ga = groupRank(a.group),
      gb = groupRank(b.group);
    if (ga !== gb) return ga - gb;
    return a.lambda_eff - b.lambda_eff;
  });
  $("phot-table").querySelector("tbody").innerHTML = visible.map(rowHtml).join("");

  const note = $("hidden-filters");
  note.hidden = partial.length === 0;
  if (partial.length) {
    $("lnk-partial").textContent = state.showPartial
      ? `hide ${partial.length} partially-covered filter${partial.length > 1 ? "s" : ""}`
      : `${partial.length} filter${partial.length > 1 ? "s" : ""} outside SED coverage hidden — show`;
  }
}

function escapeHtml(value) {
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function sanitizeFilterName(name) {
  const base = String(name || "custom").replace(/^.*[/\\]/, "");
  const cleaned = base.replace(/[<>&"'`]/g, "").replace(/[^\x20-\x7E]/g, "").trim();
  return cleaned.slice(0, 80) || "custom";
}

/** Requested-but-not-applied flags for one photometry row: [{text, title}]. */
/**
 * "Correction applied" pills for one photometry row — one pill per effect that
 * matters in this passband, `None` when nothing does. `warn` pills mark a
 * requested effect that could not be applied (fully) here.
 */
function rowPills(entry) {
  const pills = [];
  if (entry.dust_status === "applied") {
    pills.push({
      kind: "ok",
      text: "Dust",
      title: "Extinction applied: the passband lies inside the dust law's validity window (rest frame).",
    });
  } else if (entry.dust_status === "partial") {
    pills.push({
      kind: "warn",
      text: "Dust (partial)",
      title:
        "The passband straddles an edge of the dust law's validity window (rest frame). Extinction " +
        "was applied only where the law is defined — nothing is extrapolated — so this magnitude " +
        "is less reddened than a full application would give. It is exactly the plotted SED " +
        "integrated through the filter.",
    });
  } else if (entry.dust_status === "not_applied") {
    pills.push({
      kind: "warn",
      text: "No dust (outside window)",
      title:
        "Dust was requested but this passband lies entirely outside the law's validity window " +
        "(rest frame), so no extinction was applied here.",
    });
  }
  if (entry.igm_status === "applied") {
    pills.push({
      kind: "ok",
      text: "IGM",
      title: "IGM attenuation applied: the passband reaches observed wavelengths below Lyα(1+z).",
    });
  } else if (entry.igm_status === "not_applied") {
    pills.push({
      kind: "warn",
      text: "IGM ignored",
      title:
        "This passband reaches below Lyα(1+z) but IGM attenuation is switched off, so this " +
        "magnitude is not IGM-corrected (brighter than a real high-z observation would be).",
    });
  }
  if (!pills.length) {
    pills.push({ kind: "", text: "None", title: "No dust or IGM correction acts in this passband." });
  }
  return pills;
}

/** Pills that mark a requested effect not (fully) applied (passband overlay). */
function rowFlags(entry) {
  return rowPills(entry).filter((p) => p.kind === "warn");
}

function attenuationText(entry) {
  return rowPills(entry)
    .map((p) => p.text)
    .join(" · ");
}

function rowHtml(entry) {
  const mag = entry.ab_mag === null || entry.ab_mag === undefined ? "—" : entry.ab_mag.toFixed(3);
  const name = entry.isCustom ? `<em>${escapeHtml(entry.display_name)}</em>` : entry.display_name;
  const keyAttr = entry.isCustom ? escapeHtml(entry.key) : entry.key;
  const checked = state.ticked.has(entry.key) ? " checked" : "";
  const partial =
    entry.coverage < 0.999
      ? ` <span class="badge warn" title="Filter partially outside the SED wavelength range">partial coverage</span>`
      : "";
  const pills = rowPills(entry)
    .map((p) => `<span class="badge ${p.kind}" title="${escapeHtml(p.title)}">${p.text}</span>`)
    .join(" ");
  return (
    `<tr><td><input type="checkbox" data-key="${keyAttr}"${checked} title="Show passband + measured point on the plot"></td>` +
    `<td>${name}${partial}</td><td class="muted">${entry.group}</td>` +
    `<td>${Math.round(entry.lambda_eff)}</td><td><strong>${mag}</strong></td>` +
    `<td class="small">${pills}</td></tr>`
  );
}

async function customPhotometry(custom, ageIndex) {
  const form = new FormData();
  form.append("file", new Blob([custom.text]), custom.name);
  form.append("population_id", String(state.popId));
  form.append("age_index", String(ageIndex));
  form.append("mass", String(massMsun()));
  const dust = dustParams();
  if (dust.dust_law) {
    form.append("dust_law", dust.dust_law);
    form.append("ebv", String(dust.ebv));
    if (dust.rv) form.append("rv", String(dust.rv));
  }
  if (state.redshift > 0) form.append("redshift", String(state.redshift));
  const igm = igmParams();
  if (igm.igm) form.append("igm", igm.igm);
  const response = await fetch("/api/v1/photometry/custom", { method: "POST", body: form });
  if (!response.ok) {
    reportError(new Error((await response.json()).detail || "custom filter failed"));
    return null;
  }
  const payload = await response.json();
  const key = `custom:${custom.name}`;
  if (payload.curve_preview) {
    state.curveCache.set(key, {
      display_name: custom.name,
      lambda_eff: payload.result.lambda_eff,
      wavelength: payload.curve_preview.wavelength,
      transmission: normalizeTransmission(payload.curve_preview.transmission),
    });
  }
  if (custom.autoTick) {
    state.ticked.add(key);
    custom.autoTick = false;
  }
  return { ...payload.result, key, isCustom: true, display_name: custom.name };
}

/* --------------------------------------------------------------- frame notes */

function fmtDistance(mpc) {
  if (!mpc) return "";
  return mpc >= 1000 ? `${(mpc / 1000).toFixed(2)} Gpc` : `${mpc.toFixed(1)} Mpc`;
}

function updateFrameNotes() {
  const z = state.redshift;
  const dl =
    z > 0 && state.dlMpc
      ? `D<sub>L</sub> = ${fmtDistance(state.dlMpc)}`
      : z > 0
        ? "D<sub>L</sub> = …"
        : "D<sub>L</sub> = 10 pc";
  if (z > 0) {
    $("phot-frame").innerHTML = `(apparent AB · z = ${z.toFixed(2)} · ${dl})`;
    $("th-mag").innerHTML = "m<sub>AB</sub>";
    $("dl-note").innerHTML = `${dl} · apparent mags`;
  } else {
    $("phot-frame").innerHTML = `(absolute AB · ${dl})`;
    $("th-mag").innerHTML = "M<sub>AB</sub>";
    $("dl-note").innerHTML = `${dl} · absolute mags`;
  }
}

/* ------------------------------------------------------------ filter curves */

async function ensureCurve(key) {
  if (state.curveCache.has(key) || key.startsWith("custom:")) return;
  try {
    const curve = await apiGet(`/filters/${encodeURIComponent(key)}/curve`);
    curve.transmission = normalizeTransmission(curve.transmission);
    state.curveCache.set(key, curve);
  } catch (err) {
    reportError(err);
  }
}

/* ------------------------------------------------------------------ exports */

function updateExportLinks() {
  if (state.popId === null) return;
  const ageIndex = Math.round(Number($("sl-age").value));
  const logAge = (6 + ageIndex * 0.1).toFixed(1);
  const common = { log_age: logAge, mass: massMsun(), ...dustParams(), ...igmParams() };
  if (state.redshift > 0) common.redshift = state.redshift;
  $("lnk-csv").href = apiUrl(`/populations/${state.popId}/sed`, {
    ...common,
    format: "csv",
  });
  $("lnk-json").href = apiUrl(`/populations/${state.popId}/sed`, {
    ...common,
  });
}

/* --------------------------------------------------------------------- pins */

function esc(value) {
  return String(value).replace(/[&<>]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[ch]));
}

function liveLegendSpec(logAge) {
  const sel = currentSelection();
  const dust = dustParams();
  return {
    imfLabel: imfLabel(sel.imf),
    z: sel.z,
    poptype: sel.poptype,
    alpha: sel.alpha,
    massLog: Number($("sl-mass").value),
    dustLaw: dust.dust_law || "",
    ebv: dust.ebv,
    redshift: state.redshift,
    igm: igmModelKey(),
    logAge,
  };
}

/** Named bits of an SSP label. Optional bits are omitted when every SSP is at the default. */
function legendParts(spec) {
  const mass = Math.round(Number(spec.massLog) * 10) / 10;
  const z = Number(spec.redshift) || 0;
  const dust = spec.dustLaw
    ? `${spec.dustLaw} E(B−V)=${Number(spec.ebv).toFixed(2)}`
    : "";
  const exp = Number.isInteger(mass) ? String(mass) : mass.toFixed(1);
  return [
    { key: "imf", text: esc(spec.imfLabel), html: true, relevant: true },
    { key: "z", text: esc(spec.z), html: true, relevant: true },
    { key: "pop", text: spec.poptype === "bin" ? "binary" : "single", relevant: true },
    { key: "alpha", text: spec.alpha ? esc(spec.alpha) : "no [α/Fe]", relevant: Boolean(spec.alpha) },
    { key: "mass", text: `10<sup>${exp}</sup> M☉`, html: true, relevant: mass !== 6 },
    { key: "dust", text: dust ? esc(dust) : "no dust", html: true, relevant: Boolean(dust) },
    { key: "redshift", text: `z=${z.toFixed(2)}`, relevant: z > 0 },
    {
      key: "igm",
      text: spec.igm && spec.igm !== "none" ? `IGM ${esc(igmLabel(spec.igm))}` : "no IGM",
      html: true,
      relevant: Boolean(spec.igm && spec.igm !== "none"),
    },
    {
      key: "age",
      text: Number.isFinite(spec.logAge) ? `logA=${Number(spec.logAge).toFixed(2)}` : "",
      relevant: Number.isFinite(spec.logAge),
    },
  ];
}

function legendRows(entries) {
  const parts = entries.map((entry) => legendParts(entry.spec));
  const n = parts[0].length;
  const shared = [];
  const varying = [];
  for (let i = 0; i < n; i++) {
    if (!parts.some((row) => row[i].relevant)) continue;
    const texts = parts.map((row) => row[i].text);
    if (entries.length > 1 && texts.every((text) => text === texts[0])) shared.push(texts[0]);
    else varying.push(i);
  }
  const rows = entries.map((entry, i) => ({
    color: entry.color,
    label: varying.map((idx) => parts[i][idx].text).filter(Boolean).join(" · "),
  }));
  return { shared, rows };
}

function renderColorKey(logAge) {
  const host = $("ssp-color-key");
  if (!host) return;
  const liveColor = css("--brand-primary") || "#5aa9ff";
  const age = Number.isFinite(logAge) ? logAge : logAgeFromT(clock.t);
  const t = clock.t;
  const entries = [{ color: liveColor, spec: liveLegendSpec(age) }];
  const fallbacks = [];
  for (const pin of state.pins) {
    if (!pin.legend) {
      fallbacks.push({ color: pin.color, label: pinView(pin, t).label });
      continue;
    }
    let spec = pin.legend;
    if (state.syncPins && pin.frames) {
      spec = { ...spec, logAge: interpFromFrames(pin.frames, t).logAge };
    }
    if (state.syncZ) spec = { ...spec, redshift: state.redshift };
    entries.push({ color: pin.color, spec });
  }
  const { shared, rows } = legendRows(entries);
  rows.push(...fallbacks);
  if (wantPinSum(state)) rows.push({ color: SUM_COLOR, label: "Σ visible spectra" });
  const head = shared.length ? `<p class="key-shared">${shared.join(" · ")}</p>` : "";
  host.innerHTML =
    head +
    rows
      .map(
        (row) =>
          `<div class="key-row"><span class="key-dot" style="--key-color:${row.color}"></span>` +
          `<span class="key-label">${row.label}</span></div>`,
      )
      .join("");
}

function renderPins() {
  const host = $("pin-chips");
  host.innerHTML = "";
  $("chip-sync").hidden = state.pins.length === 0;
  $("chip-sync").title =
    "Lock every visible SED to the playhead age. Dust, mass and (unless redshift-sync is on) redshift stay as they were when you pinned.";
  $("chip-sync-z").hidden = state.pins.length === 0;
  $("chip-sync-z").title =
    "Show every pinned SED at the live redshift (wavelength stretch and dimming). A pin that had IGM on is recomputed at this z; dust and mass stay as pinned.";
  $("chk-sum").checked = state.sumPins;
  $("chip-sum").hidden = state.pins.length === 0;
  $("chip-sum").classList.toggle("is-ready", state.pins.length >= 1);
  $("chip-sum").title =
    state.pins.length >= 1
      ? "Sum the live SSP with every pin. Each pin keeps the mass and dust it had when pinned; redshift follows redshift-sync if that is on."
      : "Pin an SSP to sum it with the live spectrum.";
  for (const pin of state.pins) {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.style.setProperty("--chip-color", pin.color);
    const linked = state.syncPins || state.syncZ;
    const label = linked ? `${pin.basebits} 🔗` : pin.basebits;
    chip.innerHTML = `<span class="dot"></span>${label} <button title="Remove">×</button>`;
    chip.querySelector("button").addEventListener("click", () => {
      state.pins = state.pins.filter((p) => p !== pin);
      renderPins();
      renderFrame(clock.t, true);
    });
    host.appendChild(chip);
  }
  renderColorKey();
  updateTrailUi();
}

/* --------------------------------------------------------------------- init */

const clock = new PlaybackClock({
  duration: 18,
  onTick: (t) => {
    const logAge = logAgeFromT(t);
    if (state.trailOn) {
      if (clock.playing) harvestTrail(logAge);
      pruneTrail(logAge);
    }
    invalidatePhotometry();
    renderFrame(t);
    if (clock.playing) {
      clearTimeout(photTimer);
      photTimer = null;
    } else {
      schedulePhotometry();
    }
  },
  onPlayState: (playing) => {
    if (playing) {
      if (clock.t < 1e-6) clearTrail();
      invalidatePhotometry();
      clearTimeout(photTimer);
      photTimer = null;
      renderFrame(clock.t);
    } else {
      schedulePhotometry();
    }
  },
});

async function init() {
  try {
    const [meta, filters] = await Promise.all([apiGet("/meta"), apiGet("/filters")]);
    state.meta = meta;
    state.filters = filters;

    releaseIdByVersion = new Map(meta.releases.map((r) => [r.version, r.id]));

    // dust selector
    for (const law of meta.dust_laws) {
      const option = document.createElement("option");
      option.value = law.key;
      option.textContent = law.label;
      option.title = law.note;
      $("sel-dust").appendChild(option);
    }
    for (const model of meta.igm_models || []) {
      const option = document.createElement("option");
      option.value = model.key;
      option.textContent = model.label;
      option.title = model.note;
      $("sel-igm").appendChild(option);
    }
    state.igmModel = meta.igm_default || state.igmModel;
    $("sel-igm").value = state.igmModel;
    updateIgmUi();
    if (meta.cosmology) {
      $("cosmo-note").title = meta.cosmology.label;
      $("sl-redshift").max = String(redshiftSliderMax());
      $("sl-redshift").step = "1";
      syncRangeFill($("sl-redshift"));
    }

    rebuildSelectors();
    setAuxAgeClickHandler((logAge) => {
      clock.pause();
      clock.scrub(Math.min(1, Math.max(0, tFromLogAge(logAge))));
    });
    attachPlaybar($("sed-playbar"), clock, (t) => `log(age/yr) = ${logAgeFromT(t).toFixed(2)}`);
    renderPins();
    updateTrailUi();
    $("sl-age").max = String((UI_MAX_LOG_AGE - 6) / 0.1);
    clock.scrub(Number($("sl-age").value) / Number($("sl-age").max));
    await loadFrames();
  } catch (err) {
    reportError(err);
  }
}

/* ------------------------------------------------------------------- events */

for (const id of ["sel-release", "sel-imf", "sel-z", "sel-alpha"]) {
  $(id).addEventListener("change", () => {
    rebuildSelectors();
    loadFrames();
  });
}
$("seg-poptype").addEventListener("change", () => {
  rebuildSelectors();
  loadFrames();
});

$("sl-age").addEventListener("input", () => {
  clock.pause();
  clock.scrub(Number($("sl-age").value) / Number($("sl-age").max));
});

$("sl-mass").addEventListener("input", () => {
  const value = Math.round(Number($("sl-mass").value) * 10) / 10;
  const exp = Number.isInteger(value) ? String(value) : value.toFixed(1);
  $("out-mass").innerHTML = `10<sup>${exp}</sup>`;
  syncRangeFill($("sl-mass"));
  // Flux scales linearly with formed mass; keep a zoomed view on the SED.
  shiftLockedView(1, Math.pow(10, value - state.viewMassLog));
  state.viewMassLog = value;
  if (state.series) {
    renderAuxPlots(state, logAgeFromT(clock.t));
  }
  debounceReload();
});

function updateDustWindowNote() {
  const law = $("sel-dust").value;
  const lawMeta = state.meta.dust_laws.find((l) => l.key === law);
  const note = $("dust-window-note");
  note.hidden = !lawMeta;
  if (lawMeta) {
    const [lo, hi] = lawMeta.valid_range_a;
    note.textContent = `Defined for ${Math.round(lo)}–${Math.round(hi)} Å (rest); not extrapolated outside`;
  }
}

$("sel-dust").addEventListener("change", () => {
  const law = $("sel-dust").value;
  const lawMeta = state.meta.dust_laws.find((l) => l.key === law);
  $("grp-ebv").hidden = !law;
  $("grp-rv").hidden = !law || !lawMeta || lawMeta.fixed_rv !== null;
  updateDustWindowNote();
  debounceReload();
});

$("chk-igm").addEventListener("change", () => {
  state.igmOn = $("chk-igm").checked;
  updateIgmUi();
  invalidatePhotometry();
  scheduleIgm();
  schedulePhotometry();
  updateExportLinks();
});
$("sel-igm").addEventListener("change", () => {
  state.igmModel = $("sel-igm").value;
  updateIgmUi();
  invalidatePhotometry();
  scheduleIgm();
  schedulePhotometry();
  updateExportLinks();
});
$("sl-ebv").addEventListener("input", () => {
  $("out-ebv").textContent = Number($("sl-ebv").value).toFixed(2);
  syncRangeFill($("sl-ebv"));
  debounceReload();
});
$("sl-rv").addEventListener("input", () => {
  $("out-rv").textContent = Number($("sl-rv").value).toFixed(1);
  syncRangeFill($("sl-rv"));
  debounceReload();
});

$("sl-redshift").addEventListener("input", () => {
  const zPrev = state.redshift;
  state.redshift = zFromSlider($("sl-redshift").value);
  // λ_obs ∝ (1+z); plotted flux ∝ distanceDimming(z)/(1+z) (see toObserved).
  shiftLockedView(
    (1 + state.redshift) / (1 + zPrev),
    (distanceDimming(state.redshift) / (1 + state.redshift)) /
      (distanceDimming(zPrev) / (1 + zPrev)),
  );
  $("out-redshift").textContent = state.redshift.toFixed(2);
  updateCosmoWarn(logAgeFromT(clock.t));
  syncRangeFill($("sl-redshift"));
  if (state.redshift === 0) state.dlMpc = null;
  invalidatePhotometry();
  updateFrameNotes();
  updateIgmUi();
  renderFrame(clock.t); // cheap client-side stretch — instant feedback
  scheduleIgm(); // IGM transmission for the new z (server-side science)
  schedulePhotometry(); // authoritative mags + D_L from the server
});
$("chk-lyman").addEventListener("change", () => {
  state.showLyman = $("chk-lyman").checked;
  renderFrame(clock.t);
});
$("chk-balmer").addEventListener("change", () => {
  state.showBalmer = $("chk-balmer").checked;
  renderFrame(clock.t);
});

$("chk-xlog").addEventListener("change", () => {
  state.xLog = $("chk-xlog").checked;
  state.userX = null;
  renderFrame(clock.t);
});
$("chk-ylog").addEventListener("change", () => {
  state.yLog = $("chk-ylog").checked;
  state.userY = null;
  renderFrame(clock.t);
});
$("seg-xunit").addEventListener("change", () => {
  state.xNu = document.querySelector('input[name="xunit"]:checked').value === "nu";
  state.userX = null;
  $("xlog-sym").textContent = state.xNu ? "ν" : "λ";
  renderFrame(clock.t);
});

let reloadTimer = null;
function debounceReload() {
  clearTimeout(reloadTimer);
  reloadTimer = setTimeout(loadFrames, 350);
}

$("chk-trail").addEventListener("change", () => {
  if (state.pins.length) {
    $("chk-trail").checked = false;
    state.trailOn = false;
    updateTrailUi();
    return;
  }
  state.trailOn = $("chk-trail").checked;
  if (!state.trailOn) clearTrail();
  updateTrailUi();
  renderFrame(clock.t);
});

function nextPinColor() {
  const used = new Set(state.pins.map((pin) => pin.color));
  return PIN_COLORS.find((color) => !used.has(color)) || PIN_COLORS[state.pins.length % PIN_COLORS.length];
}

$("btn-pin").addEventListener("click", () => {
  if (!state.frames || state.trailOn) return;
  const { y, logAge } = interpFromFrames(state.frames, clock.t);
  const z = state.redshift;
  const igm = igmFactorFor(z);
  const view = toObserved(state.frames.wavelength, y, z, igm);
  const basebits = labelBits().join(" · ");
  state.pins.push({
    id: ++state.pinSeq,
    color: nextPinColor(),
    popId: state.popId,
    basebits,
    legend: liveLegendSpec(logAge),
    z,
    igm: igm ? igm.slice() : null,
    igmModel: igmModelKey(z),
    dust: dustParams(), // law/E(B−V) baked into `frames` server-side; kept for the marks
    restY: y.slice(), // rest-frame flux at pin time, for the IGM ghost when not synced
    massLog: Number($("sl-mass").value),
    frames: structuredClone(state.frames),
    series: cloneSeries(state.series),
    yLog10: state.yLog10 ? { ...state.yLog10 } : null,
    logAge,
    frozen: {
      x: view.x.slice(),
      y: view.y.slice(),
      logAge,
      label: `${basebits} · logA=${logAge.toFixed(2)}`,
    },
  });
  renderPins();
  renderFrame(clock.t, true);
});

$("chk-sync").addEventListener("change", () => {
  state.syncPins = $("chk-sync").checked;
  renderPins();
  renderFrame(clock.t, true);
});

$("chk-sync-z").addEventListener("change", () => {
  state.syncZ = $("chk-sync-z").checked;
  renderPins();
  scheduleIgm();
  renderFrame(clock.t, true);
});

$("chk-sum").addEventListener("change", () => {
  state.sumPins = $("chk-sum").checked;
  if (!state.frames) return;
  renderFrame(clock.t, true);
});

$("phot-table").addEventListener("change", async (event) => {
  const box = event.target.closest("input[data-key]");
  if (!box) return;
  const key = box.dataset.key;
  if (box.checked) {
    state.ticked.add(key);
    await ensureCurve(key);
  } else {
    state.ticked.delete(key);
  }
  renderFrame(clock.t);
});

$("lnk-partial").addEventListener("click", (event) => {
  event.preventDefault();
  state.showPartial = !state.showPartial;
  renderPhotTable();
});

$("btn-png").addEventListener("click", () => {
  Plotly.downloadImage("sed-plot", {
    format: "png",
    width: 1400,
    height: 800,
    scale: 2,
    filename: "bib-ssp",
  });
});

$("lbl-file-filter")?.addEventListener("click", (event) => event.stopPropagation());
$("file-filter").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const text = await file.text();
  state.customFilters.push({ name: sanitizeFilterName(file.name), text, autoTick: true });
  event.target.value = "";
  schedulePhotometry();
});

syncAllRangeFills();

document.querySelectorAll("#sed-controls input[data-panel]").forEach((box) => {
  const apply = (redraw) => {
    const panel = $(`panel-${box.dataset.panel}`);
    if (!panel) return;
    panel.hidden = !box.checked;
    if (redraw && box.checked && state.frames) {
      renderFrame(clock.t);
      requestAnimationFrame(() => {
        for (const host of panel.querySelectorAll(".js-plotly-plot, .plot-host")) {
          if (host.data) Plotly.Plots.resize(host);
        }
      });
    }
  };
  apply(false);
  box.addEventListener("change", () => apply(true));
});

init();
