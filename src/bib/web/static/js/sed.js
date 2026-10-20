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
} from "./ssp-plots.js?v=15";

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
const DUST_OUTSIDE_FILL = "rgba(255, 180, 84, 0.10)"; // where a requested dust law is NOT applied
const DUST_EDGE_COLOR = "rgba(255, 180, 84, 0.75)";
const IGM_FILL = "rgba(120, 150, 255, 0.10)"; // observer-frame region attenuated by the IGM
const IGM_EDGE_COLOR = "rgba(120, 150, 255, 0.8)";
const TRAIL_DEX = 0.5; // log-age spacing of play-trail snapshots

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
  pins: [],
  pinSeq: 0,
  syncPins: false,
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

/** Fetch (or reuse) the IGM transmission for the current z / model / population. */
async function ensureIgm() {
  const z = state.redshift;
  if (!(z > 0) || !state.igmOn || state.popId === null) {
    state.igm = null;
    return;
  }
  if (igmFactorFor(z)) return;
  const cacheKey = `${state.popId}:${state.igmModel}:${z}`;
  const cached = state.igmCache.get(cacheKey);
  if (cached) {
    state.igm = { popId: state.popId, z, model: state.igmModel, transmission: cached };
    return;
  }
  const token = ++state.igmRequest;
  try {
    const data = await apiGet("/igm_transmission", {
      population_id: state.popId,
      redshift: z,
      model: state.igmModel,
    });
    if (token !== state.igmRequest) return;
    state.igmCache.set(cacheKey, data.transmission);
    if (state.igmCache.size > 400) {
      state.igmCache.delete(state.igmCache.keys().next().value);
    }
    state.igm = { popId: state.popId, z, model: state.igmModel, transmission: data.transmission };
  } catch (err) {
    reportError(err);
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

function sedHover(extra) {
  const xUnit = state.xNu ? "Hz" : "Å";
  return `%{x:.4g} ${xUnit} · %{y:.3g} L☉/Å<extra>` + extra + "</extra>";
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
  let lo = Infinity,
    hi = -Infinity;
  for (const frame of payload.frames) {
    for (const v of frame.flux) {
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

/** Rainbow-ish colour keyed to a filter's effective wavelength. */
function filterColor(lambdaEff, alpha = 1) {
  const t = Math.min(1, Math.max(0, (Math.log10(lambdaEff) - 3.45) / 0.95));
  const hue = Math.round(285 * (1 - t));
  return alpha >= 1 ? `hsl(${hue}, 75%, 62%)` : `hsla(${hue}, 75%, 62%, ${alpha})`;
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

/**
 * Shade (a) the observer-frame wavelengths where the chosen dust law is undefined, so it
 * is obvious that no extinction was applied there, and (b) the region blueward of
 * Lyα(1+z) where the IGM prescription acts.
 */
function addAttenuationRegions(layout, xExtent) {
  const z = state.redshift;
  const stretch = 1 + z;
  const xLo = Math.min(xExtent[0], xExtent[1]);
  const xHi = Math.max(xExtent[0], xExtent[1]);
  const band = (wlA, wlB, fill, edgeColor, label, edges) => {
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
      fillcolor: fill,
      line: { width: 0 },
      layer: "below",
    });
    for (const wl of edges) {
      const xe = spectralX(wl);
      if (!(xe >= xLo && xe <= xHi)) continue;
      layout.shapes.push({
        type: "line",
        xref: "x",
        yref: "paper",
        x0: xe,
        x1: xe,
        y0: 0,
        y1: 1,
        line: { color: edgeColor, width: 1, dash: "dashdot" },
        layer: "below",
      });
    }
    const mid = state.xLog ? Math.sqrt(x0 * x1) : 0.5 * (x0 + x1);
    layout.annotations.push({
      x: state.xLog ? Math.log10(mid) : mid,
      y: 0.985,
      yref: "paper",
      yanchor: "top",
      xanchor: "center",
      text: label,
      showarrow: false,
      font: { size: 9.5, color: edgeColor },
      bgcolor: "rgba(10,14,22,0.6)",
    });
  };

  const dust = dustParams();
  if (dust.dust_law && dust.ebv > 0) {
    const lawMeta = state.meta.dust_laws.find((l) => l.key === dust.dust_law);
    if (lawMeta?.valid_range_a) {
      const lo = lawMeta.valid_range_a[0] * stretch;
      const hi = lawMeta.valid_range_a[1] * stretch;
      const label = "no extinction applied<br>(outside dust-law window)";
      band(1e-6, lo, DUST_OUTSIDE_FILL, DUST_EDGE_COLOR, label, [lo]);
      band(hi, 1e12, DUST_OUTSIDE_FILL, DUST_EDGE_COLOR, label, [hi]);
    }
  }
  if (igmModelKey() !== "none" && igmFactorFor(z)) {
    const lya = 1215.67 * stretch;
    band(1e-6, lya, IGM_FILL, IGM_EDGE_COLOR, `IGM-attenuated<br>(${esc(igmLabel(state.igmModel))})`, [lya]);
  }
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
  if (state.syncPins && pin.frames) {
    const { y, logAge } = interpFromFrames(pin.frames, t);
    const view = toObserved(pin.frames.wavelength, y, pin.z, pin.igm);
    return { ...view, label: `${pin.basebits} · logA=${logAge.toFixed(2)} 🔗` };
  }
  return { x: pin.frozen.x, y: pin.frozen.y, label: pin.frozen.label };
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
    if (!ev || host._bibApplying) return;
    const box = { xaxis: state.userX, yaxis: state.userY };
    noteAxisLock(ev, box, "xaxis");
    noteAxisLock(ev, box, "yaxis");
    state.userX = box.xaxis;
    state.userY = box.yaxis;
  });
}

function drawSedFrame(t) {
  if (!state.frames) return;
  const { y, logAge } = interpFromFrames(state.frames, t);
  const cur = toObserved(state.frames.wavelength, y, state.redshift, igmFactorFor(state.redshift));
  const liveName = liveLabel(logAge);

  // ---- axis extents: union of current view, pins, and marker levels
  let xMin = cur.x[0],
    xMax = cur.x[cur.x.length - 1];
  const zShift = fluxLogShift(state.redshift);
  let yLo = state.yLog10.lo - zShift,
    yHi = state.yLog10.hi - zShift;

  const traces = [];
  for (const pin of state.pins) {
    const view = pinView(pin, t);
    xMin = Math.min(xMin, view.x[0], view.x[view.x.length - 1]);
    xMax = Math.max(xMax, view.x[0], view.x[view.x.length - 1]);
    if (pin.yLog10) {
      const shift = fluxLogShift(pin.z);
      yLo = Math.min(yLo, pin.yLog10.lo - shift);
      yHi = Math.max(yHi, pin.yLog10.hi - shift);
    }
    traces.push({
      uid: `pin-${pin.id}`,
      x: spectralXs(copyArr(view.x)),
      y: copyArr(view.y),
      name: view.label,
      showlegend: false,
      mode: "lines",
      line: { color: pin.color, width: 1.3 },
      hovertemplate: sedHover(view.label),
    });
  }

  if (state.trailOn && state.trail.length && !state.pins.length) {
    for (const snap of state.trail) {
      const view = toObserved(
        state.frames.wavelength,
        snap.y,
        state.redshift,
        igmFactorFor(state.redshift),
      );
      const { color, width } = trailStyle(snap.logAge);
      const trailName = `logA=${snap.logAge.toFixed(1)}`;
      traces.push({
        x: spectralXs(view.x),
        y: view.y,
        name: trailName,
        showlegend: false,
        mode: "lines",
        line: { color, width },
        hovertemplate: sedHover(trailName),
      });
    }
  }

  traces.push({
    uid: "live-sed",
    x: spectralXs(copyArr(cur.x)),
    y: copyArr(cur.y),
    name: liveName,
    showlegend: false,
    mode: "lines",
    line: { color: css("--brand-primary") || "#5aa9ff", width: 2.1 },
    hovertemplate: sedHover(liveName),
  });

  if (wantPinSum(state)) {
    const summed = sumVisibleSed(t, cur);
    if (summed) {
      traces.push({
        uid: "sum-sed",
        x: spectralXs(copyArr(summed.x)),
        y: copyArr(summed.y),
        name: "Σ visible spectra",
        showlegend: false,
        mode: "lines",
        line: { color: SUM_COLOR, width: 2.8 },
        hovertemplate: sedHover("Σ visible spectra"),
      });
    }
  }

  // ---- ticked filter passbands hugging the plot floor (hidden y2 axis)
  const xUnit = state.xNu ? "Hz" : "Å";
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
      fillcolor: filterColor(curve.lambda_eff, flagged ? 0.07 : 0.16),
      hovertemplate:
        `%{x:.4g} ${xUnit} · T=%{y:.2f}<extra>` +
        curve.display_name +
        (row ? ` · ${attenuationText(row)}` : "") +
        "</extra>",
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
        // ◇ when every requested effect was applied inside the passband,
        // crossed ◇ when dust or IGM was requested but could not be applied there.
        symbol: marks.map((r) => (rowFlags(r).length ? "diamond-x" : "diamond")),
        size: marks.map((r) => (rowFlags(r).length ? 11 : 9.5)),
        color: marks.map((r) => filterColor(r.lambda_eff)),
        line: {
          color: marks.map((r) => (rowFlags(r).length ? css("--brand-warn") || "#ffb454" : "#ffffff")),
          width: marks.map((r) => (rowFlags(r).length ? 1.6 : 1)),
        },
      },
      text: marks.map(
        (r) =>
          `${r.display_name}: ${state.redshift > 0 ? "m" : "M"}<sub>AB</sub> = ${r.ab_mag}` +
          `<br>${attenuationText(r)}`,
      ),
      hovertemplate: "%{text}<extra>photometry</extra>",
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
      Plotly.react("sed-plot", traces, plotLayout([xLo, xHi], [yLo, yHi]), {
        responsive: true,
        displaylogo: false,
        modeBarButtonsToRemove: ["select2d", "lasso2d", "autoScale2d"],
      }),
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
  const hover = [sedHover(liveName)];
  const indices = [live];
  if (state.syncPins) {
    for (const pin of state.pins) {
      const j = gd.data.findIndex((tr) => tr.uid === `pin-${pin.id}`);
      if (j < 0) return false;
      const view = pinView(pin, t);
      ys.push(view.y);
      names.push(view.label);
      hover.push(sedHover(view.label));
      indices.push(j);
    }
  }
  if (wantPinSum(state)) {
    const sumIdx = gd.data.findIndex((tr) => tr.uid === "sum-sed");
    if (sumIdx < 0) return false;
    const summed = sumVisibleSed(t, cur);
    if (!summed) return false;
    ys.push(summed.y);
    names.push("Σ visible spectra");
    hover.push(sedHover("Σ visible spectra"));
    indices.push(sumIdx);
  }
  Plotly.restyle(gd, { y: ys, name: names, hovertemplate: hover }, indices);
  renderColorKey(logAge);
  return true;
}

let lastSedDrawMs = 0;

function renderFrame(t, initial = false) {
  if (!state.frames) return;
  const { y, w, logAge } = interpFromFrames(state.frames, t);
  const cur = toObserved(state.frames.wavelength, y, state.redshift, igmFactorFor(state.redshift));
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
function rowFlags(entry) {
  const flags = [];
  if (entry.dust_status === "partial") {
    flags.push({
      text: "partial dust window",
      title:
        "Part of this passband lies outside the dust law's validity window (rest frame). " +
        "Extinction was applied only where the law is defined; nothing was extrapolated.",
    });
  } else if (entry.dust_status === "not_applied") {
    flags.push({
      text: "outside dust window",
      title:
        "This passband lies entirely outside the dust law's validity window (rest frame), " +
        "so the requested extinction was not applied here.",
    });
  }
  if (entry.igm_status === "not_applied") {
    flags.push({
      text: "no IGM",
      title:
        "This passband reaches observed wavelengths below Lyα(1+z) but no IGM prescription " +
        "is applied, so the magnitude is brighter than a real high-z observation would be.",
    });
  }
  return flags;
}

function attenuationText(entry) {
  const label = entry.attenuation_label || "unattenuated";
  const flags = rowFlags(entry).map((f) => f.text);
  return flags.length ? `${label} (${flags.join(", ")})` : label;
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
  const label = escapeHtml(entry.attenuation_label || "unattenuated");
  const flags = rowFlags(entry)
    .map((f) => ` <span class="badge warn" title="${escapeHtml(f.title)}">${f.text}</span>`)
    .join("");
  return (
    `<tr><td><input type="checkbox" data-key="${keyAttr}"${checked} title="Show passband + measured point on the plot"></td>` +
    `<td>${name}${partial}</td><td class="muted">${entry.group}</td>` +
    `<td>${Math.round(entry.lambda_eff)}</td><td><strong>${mag}</strong></td>` +
    `<td class="small">${label}${flags}</td></tr>`
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
    "Lock every visible SED to the playhead age. Redshift, dust and mass stay as they were when you pinned.";
  $("chk-sum").checked = state.sumPins;
  $("chip-sum").hidden = state.pins.length === 0;
  $("chip-sum").classList.toggle("is-ready", state.pins.length >= 1);
  $("chip-sum").title =
    state.pins.length >= 1
      ? "Sum the live SSP with every pin. Each pin keeps the mass, dust and redshift it had when pinned."
      : "Pin an SSP to sum it with the live spectrum.";
  for (const pin of state.pins) {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.style.setProperty("--chip-color", pin.color);
    const label = state.syncPins ? `${pin.basebits} 🔗` : pin.basebits;
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
  state.redshift = zFromSlider($("sl-redshift").value);
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
    basebits,
    legend: liveLegendSpec(logAge),
    z,
    igm: igm ? igm.slice() : null,
    igmModel: igmModelKey(z),
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
