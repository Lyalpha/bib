/* Age-locked SSP timeseries plots (star counts, ionizing, SN rates, …). */
"use strict";

import { apiGet } from "./api.js";
import { PLOT_GRID, logAxisTicks } from "./plot-axis.js";

const TABLES = ["ionizing", "starmass", "sn_rates", "yields", "star_counts"];

export const AUX_PANELS = [
  { id: "counts", table: "star_counts", title: "Star counts", defaultOn: true },
  { id: "ionizing", table: "ionizing", title: "Ionizing photons", defaultOn: true },
  { id: "sn", table: "sn_rates", title: "Supernova rates", defaultOn: true },
  { id: "mass", table: "starmass", title: "Surviving mass", defaultOn: false },
  { id: "yields", table: "yields", title: "Chemical yields", defaultOn: false },
];

const css = (name) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

function sumAt(columns, names, i) {
  let s = 0;
  for (const name of names) s += columns[name][i] || 0;
  return s;
}

function seriesOf(columns, names) {
  const n = columns[names[0]].length;
  const y = new Array(n);
  for (let i = 0; i < n; i++) y[i] = sumAt(columns, names, i);
  return y;
}

function scaleArr(values, factor) {
  return values.map((v) => (v == null ? null : v * factor));
}

function massFactor(logM) {
  return 10 ** (logM - 6);
}

export async function fetchSeries(popId) {
  const out = {};
  await Promise.all(
    TABLES.map(async (table) => {
      try {
        out[table] = await apiGet(`/populations/${popId}/timeseries`, { table });
      } catch {
        out[table] = null;
      }
    }),
  );
  return out;
}

export function cloneSeries(series) {
  return series ? structuredClone(series) : null;
}

export function hoverLabel() {
  const text = css("--brand-text") || "#e8ecf8";
  const bg = css("--brand-bg") || "#0b1020";
  const accent = css("--brand-primary") || "#5aa9ff";
  return {
    bgcolor: bg,
    bordercolor: accent,
    font: { color: text, size: 13, family: "system-ui, sans-serif" },
    namelength: -1,
    align: "left",
  };
}

function yAxisRange(ysList, yLog) {
  let lo = Infinity;
  let hi = -Infinity;
  for (const ys of ysList) {
    for (const v of ys) {
      if (v == null || !Number.isFinite(v)) continue;
      if (yLog && !(v > 0)) continue;
      if (v < lo) lo = v;
      if (v > hi) hi = v;
    }
  }
  if (!Number.isFinite(lo)) return yLog ? [-2, 2] : [0, 1];
  if (yLog) {
    const a = Math.log10(lo);
    const b = Math.log10(hi);
    const pad = 0.12 * (b - a || 1);
    return [a - pad, b + pad];
  }
  const pad = 0.08 * (hi - lo || 1);
  return [Math.min(0, lo - pad), hi + pad];
}

/** Solid age rule with a contrasting edge, so it is not another dashed series. */
function ageMarker(logAge, color) {
  const ink = color || "#5aa9ff";
  const edge = ink.toLowerCase() === "#ffffff" ? "rgba(0,0,0,0.72)" : "rgba(255,255,255,0.78)";
  const geom = {
    type: "line",
    x0: logAge,
    x1: logAge,
    y0: 0,
    y1: 1,
    yref: "paper",
    layer: "above",
  };
  return [
    { ...geom, line: { color: edge, width: 4.2 } },
    { ...geom, line: { color: ink, width: 1.35 } },
  ];
}

function pinLogAge(pin) {
  if (Number.isFinite(pin.logAge)) return pin.logAge;
  if (Number.isFinite(pin.frozen?.logAge)) return pin.frozen.logAge;
  const m = /logA=([0-9.]+)/.exec(pin.frozen?.label || "");
  return m ? Number(m[1]) : null;
}

/** Shared playhead colour: white when every displayed SSP is locked to one age. */
function livePlayheadColor(state, liveColor) {
  if (state.syncPins && state.pins.length) return "#ffffff";
  return liveColor;
}

function pinAgeLines(state) {
  if (state.syncPins) return [];
  const out = [];
  for (const pin of state.pins) {
    const age = pinLogAge(pin);
    if (Number.isFinite(age)) out.push({ logAge: age, color: pin.color });
  }
  return out;
}

function playheadShapes(logAge, color, extraLines) {
  const accent = color || css("--brand-primary") || "#5aa9ff";
  const shapes = ageMarker(logAge, accent);
  for (const extra of extraLines || []) {
    shapes.push(...ageMarker(extra.logAge, extra.color));
  }
  return shapes;
}

function playheadRelayout(logAge) {
  return {
    "shapes[0].x0": logAge,
    "shapes[0].x1": logAge,
    "shapes[1].x0": logAge,
    "shapes[1].x1": logAge,
  };
}

function plotTheme(title, yTitle, logAge, yLog, yRange, shapes, linkedLog, hoverY, panelId) {
  const text = css("--brand-text") || "#e7ecf3";
  const grid = PLOT_GRID;
  const lock = auxLocks.get(`${panelId}-plot`) || {};
  const xRange = lock.xaxis || [5.95, UI_MAX_LOG_AGE + 0.05];
  const yUsed = lock.yaxis || yRange;
  const ySpan = yUsed ? yUsed[1] - yUsed[0] : 6;
  const layout = {
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { color: text, size: 12 },
    margin: { l: 70, r: linkedLog ? 78 : 16, t: 8, b: 64 },
    uirevision: "ssp-aux-v10",
    xaxis: {
      title: { text: "log<sub>10</sub>(age / yr)", standoff: 14 },
      range: xRange,
      autorange: false,
      gridcolor: grid,
      gridwidth: 1,
      zeroline: false,
      unifiedhovertitle: { text: "log(age) = %{x:.2f} yr" },
    },
    yaxis: {
      type: yLog ? "log" : "linear",
      title: { text: yTitle, standoff: 8 },
      range: yUsed,
      autorange: false,
      gridcolor: grid,
      gridwidth: 1,
      zeroline: false,
      exponentformat: "power",
      ...(hoverY && hoverY.startsWith(".") ? { hoverformat: hoverY } : {}),
      ...(yLog ? logAxisTicks(ySpan) : {}),
    },
    showlegend: true,
    legend: { orientation: "h", y: -0.28, yanchor: "top", font: { size: 11 } },
    hovermode: "x unified",
    hoverlabel: hoverLabel(),
    shapes,
  };
  if (linkedLog) {
    layout.yaxis2 = {
      type: "log",
      title: { text: linkedLog.title, standoff: 8 },
      range: [yUsed[0] - linkedLog.logOffset, yUsed[1] - linkedLog.logOffset],
      autorange: false,
      overlaying: "y",
      side: "right",
      anchor: "x",
      showgrid: false,
      zeroline: false,
      showticklabels: true,
      ticks: "outside",
      exponentformat: "power",
      ...logAxisTicks(ySpan),
    };
  }
  return layout;
}

function countHoverText(values) {
  return values.map((v) => {
    if (v == null || !Number.isFinite(v) || !(v > 0)) return "0";
    if (v < 1) return "<1";
    return String(Math.round(v));
  });
}

function line(x, y, name, color, width, dash, yFmt) {
  const counts = yFmt === "count";
  const tr = {
    x,
    y,
    name,
    mode: "lines",
    line: { color, width: width ?? 2, dash: dash || "solid" },
    hovertemplate: counts
      ? `<b>${name}</b><br>%{text}<extra></extra>`
      : `<b>${name}</b><br>%{y:${yFmt || ".3g"}}<extra></extra>`,
  };
  if (counts) tr.text = countHoverText(y);
  return tr;
}

/** Plotly only draws overlay axes if a trace is assigned to them. */
function linkedScaleTrace(x, y, logOffset) {
  const off = 10 ** logOffset;
  return {
    x,
    y: y.map((v) => (v == null || !Number.isFinite(v) ? null : v / off)),
    yaxis: "y2",
    mode: "lines",
    line: { width: 0 },
    hoverinfo: "skip",
    showlegend: false,
  };
}

const auxLocks = new Map();

function noteAxisLock(ev, lock, prefix) {
  if (ev[`${prefix}.autorange`]) lock[prefix] = null;
  else if (ev[`${prefix}.range[0]`] != null) {
    lock[prefix] = [+ev[`${prefix}.range[0]`], +ev[`${prefix}.range[1]`]];
  } else if (Array.isArray(ev[`${prefix}.range`])) {
    lock[prefix] = ev[`${prefix}.range`].map(Number);
  }
}

function bindAuxViewLock(el, panelId) {
  if (!el || el._bibViewLock || typeof el.on !== "function") return;
  el._bibViewLock = true;
  el.on("plotly_relayout", (ev) => {
    if (!ev || el._bibApplying) return;
    const lock = auxLocks.get(panelId) || { xaxis: null, yaxis: null };
    noteAxisLock(ev, lock, "xaxis");
    noteAxisLock(ev, lock, "yaxis");
    auxLocks.set(panelId, lock);
  });
}

function react(hostId, traces, layout) {
  const el = document.getElementById(hostId);
  if (!el || el.hidden) return;
  el._bibApplying = true;
  Promise.resolve(
    Plotly.react(hostId, traces, layout, {
      responsive: true,
      displaylogo: false,
      modeBarButtonsToRemove: ["select2d", "lasso2d", "autoScale2d"],
    }),
  ).then(() => {
    bindAuxViewLock(el, hostId);
    setTimeout(() => {
      el._bibApplying = false;
    }, 0);
  });
}

const SERIES_DASHES = ["solid", "dash", "dot", "longdash", "dashdot"];
export const SUM_COLOR = "#f4efe4";
/** Explorer playback and property plots stop here: log10(age of the Universe / yr). */
export const UI_MAX_LOG_AGE = 10.13;

export function wantPinSum(state) {
  return Boolean(state.sumPins && state.pins.length >= 1);
}

function addSeries(a, b) {
  const n = Math.max(a.length, b.length);
  const out = new Array(n);
  for (let i = 0; i < n; i++) {
    const va = a[i];
    const vb = b[i];
    const na = va == null || !Number.isFinite(va);
    const nb = vb == null || !Number.isFinite(vb);
    out[i] = na && nb ? null : (na ? 0 : va) + (nb ? 0 : vb);
  }
  return out;
}

/** Linear sum of the live timeseries plus every pin, each at its own mass. */
export function sumVisibleSeries(state, tableKey, pack, livePay, liveFactor) {
  let names = null;
  let acc = null;
  let x = null;
  if (livePay) {
    const packed = pack(livePay, liveFactor);
    names = packed.names;
    acc = packed.ys.map((y) => y.slice());
    x = livePay.log_age;
  }
  for (const pin of state.pins) {
    const pay = pin.series?.[tableKey];
    if (!pay) continue;
    const packed = pack(pay, massFactor(pin.massLog));
    if (!acc) {
      names = packed.names;
      acc = packed.ys.map((y) => y.slice());
      x = pay.log_age;
      continue;
    }
    const n = Math.min(acc.length, packed.ys.length);
    for (let i = 0; i < n; i++) acc[i] = addSeries(acc[i], packed.ys[i]);
  }
  return acc ? { names, ys: acc, x } : null;
}

function addOverlay(traces, x, ys, names, color, width, yFmt) {
  for (let i = 0; i < ys.length; i++) {
    const tr = line(
      x,
      ys[i],
      names[i],
      color,
      width,
      SERIES_DASHES[i % SERIES_DASHES.length],
      yFmt,
    );
    tr.showlegend = false;
    traces.push(tr);
  }
}

function styleKeyTraces(names) {
  const ink = css("--brand-muted") || "#c5c9d6";
  return names.map((name, i) => ({
    x: [null],
    y: [null],
    name,
    mode: "lines",
    line: { color: ink, width: 2, dash: SERIES_DASHES[i % SERIES_DASHES.length] },
    hoverinfo: "skip",
    showlegend: true,
  }));
}

function countsYs(payload, factor) {
  const c = payload.columns;
  const names = ["O-type", "Wolf–Rayet", "B-type"];
  const ys = [
    scaleArr(seriesOf(c, ["n_o_hi", "n_of_hi", "n_o_lo", "n_of_lo"]), factor),
    scaleArr(seriesOf(c, ["n_wnh_hi", "n_wn_hi", "n_wc_hi", "n_wnh_lo", "n_wn_lo", "n_wc_lo"]), factor),
    scaleArr(seriesOf(c, ["n_b_hi", "n_b_lo"]), factor),
  ];
  return { names, ys };
}

function snYs(payload, factor) {
  const c = payload.columns;
  const dt = c.bin_width_yr;
  const rate = (arr) => arr.map((v, i) => (dt[i] > 0 ? (v * factor) / dt[i] : 0));
  const names = ["Core-collapse", "Type Ia", "PISN"];
  const ys = [
    rate(c.n_iip.map((v, i) => v + c.n_ii_other[i] + c.n_ib[i] + c.n_ic[i])),
    rate(c.n_ia),
    rate(c.n_pisn),
  ];
  return { names, ys };
}

/** BPASS ionizing files: log10 L(Hα / erg s⁻¹) = log10 N_ion − 11.87 (Case B). */
const BPASS_LOG_LHA_OFFSET = 11.87;

function ionizingYs(payload, factor) {
  const logF = Math.log10(factor);
  const names = ["N<sub>ion</sub>"];
  const ys = [
    payload.columns.log_nion.map((v) =>
      v == null || !Number.isFinite(v) ? null : 10 ** (v + logF),
    ),
  ];
  return { names, ys };
}

function massYs(payload, factor) {
  const c = payload.columns;
  const names = ["Live stars", "Remnants"];
  const ys = [
    scaleArr(c.mass_stars, factor),
    scaleArr(c.mass_remnants ?? c.mass_stars.map(() => 0), factor),
  ];
  return { names, ys };
}

function yieldYs(payload, factor) {
  const c = payload.columns;
  const names = ["Wind metals", "SN metals"];
  const ys = [scaleArr(c.wind_z, factor), scaleArr(c.sn_z, factor)];
  return { names, ys };
}

const BUILDERS = {
  counts: { pack: countsYs, yTitle: "number of stars", yLog: true, hoverY: "count" },
  ionizing: {
    pack: ionizingYs,
    yTitle: "N<sub>ion</sub> (s<sup>−1</sup>)",
    yLog: true,
    linkedLog: { title: "L(Hα) (erg s<sup>−1</sup>)", logOffset: BPASS_LOG_LHA_OFFSET },
  },
  sn: { pack: snYs, yTitle: "SN yr<sup>−1</sup>", yLog: true },
  mass: { pack: massYs, yTitle: "M<sub>☉</sub>", yLog: false },
  yields: { pack: yieldYs, yTitle: "M<sub>☉</sub> yr<sup>−1</sup>", yLog: true },
};

const auxCache = new Map();
let onAgeClick = null;

export function setAuxAgeClickHandler(fn) {
  onAgeClick = fn;
}

function ensureAgeClick(host) {
  if (!host || host._bibAgeClick || typeof host.on !== "function") return;
  host._bibAgeClick = true;
  host.on("plotly_click", (ev) => {
    const x = ev?.points?.[0]?.x;
    if (Number.isFinite(x) && onAgeClick) onAgeClick(x);
  });
}

export function auxPlotsReady() {
  return auxCache.size > 0;
}

/** Move only the playhead shapes. Curves and axes are not touched. */
let lastAuxScrubMs = 0;
export function scrubAuxPlots(logAge) {
  const now = performance.now();
  if (now - lastAuxScrubMs < 50) return;
  lastAuxScrubMs = now;
  for (const panel of AUX_PANELS) {
    const host = document.getElementById(`${panel.id}-plot`);
    const wrap = document.getElementById(`panel-${panel.id}`);
    const cached = auxCache.get(panel.id);
    if (!host || !wrap || wrap.hidden || !host.layout || !cached) continue;
    Plotly.relayout(host, playheadRelayout(logAge));
  }
}

function clipShownAges(x, ys) {
  const xIn = x || [];
  const series = ys || [];
  const xi = [];
  const yOut = series.map(() => []);
  let i = 0;
  for (; i < xIn.length; i++) {
    if (Number(xIn[i]) > UI_MAX_LOG_AGE + 1e-6) break;
    xi.push(xIn[i]);
    series.forEach((y, k) => yOut[k].push(y[i]));
  }
  if (i > 0 && i < xIn.length && Number(xIn[i - 1]) < UI_MAX_LOG_AGE - 1e-4) {
    const x0 = Number(xIn[i - 1]);
    const x1 = Number(xIn[i]);
    const w = (UI_MAX_LOG_AGE - x0) / (x1 - x0 || 1);
    xi.push(UI_MAX_LOG_AGE);
    series.forEach((y, k) => {
      const a = y[i - 1];
      const b = y[i];
      const fa = a != null && Number.isFinite(a);
      const fb = b != null && Number.isFinite(b);
      yOut[k].push(fa && fb ? a + (b - a) * w : fa ? a : b);
    });
  }
  return { x: xi, ys: yOut };
}

export function renderAuxPlots(state, logAge) {
  const liveFactor = massFactor(Number(document.getElementById("sl-mass").value));
  const liveColor = css("--brand-primary") || "#5aa9ff";
  auxCache.clear();

  for (const panel of AUX_PANELS) {
    const host = document.getElementById(`${panel.id}-plot`);
    const wrap = document.getElementById(`panel-${panel.id}`);
    if (!host || !wrap || wrap.hidden) continue;
    const spec = BUILDERS[panel.id];
    const tableKey = panel.table;
    const live = state.series?.[tableKey];
    if (!live) {
      auxCache.delete(panel.id);
      host.innerHTML = `<p class="muted small" style="padding:1rem;">No ${panel.title.toLowerCase()} table for this population.</p>`;
      continue;
    }
    const packed = spec.pack(live, liveFactor);
    const shown = clipShownAges(live.log_age, packed.ys);
    const allYs = shown.ys.slice();
    const traces = shown.ys.map((y, i) => {
      const tr = line(
        shown.x,
        y,
        packed.names[i],
        liveColor,
        2.1,
        SERIES_DASHES[i % SERIES_DASHES.length],
        spec.hoverY,
      );
      tr.showlegend = false;
      return tr;
    });
    for (const pin of state.pins) {
      const pinPay = pin.series?.[tableKey];
      if (!pinPay) continue;
      const pinPacked = spec.pack(pinPay, massFactor(pin.massLog));
      const pinShown = clipShownAges(pinPay.log_age, pinPacked.ys);
      allYs.push(...pinShown.ys);
      addOverlay(traces, pinShown.x, pinShown.ys, pinPacked.names, pin.color, 1.55, spec.hoverY);
    }
    if (wantPinSum(state)) {
      const summed = sumVisibleSeries(state, tableKey, spec.pack, live, liveFactor);
      if (summed) {
        const sumShown = clipShownAges(summed.x, summed.ys);
        addOverlay(traces, sumShown.x, sumShown.ys, summed.names, SUM_COLOR, 2.35, spec.hoverY);
      }
    }
    if (spec.linkedLog && shown.ys[0]) {
      traces.push(linkedScaleTrace(shown.x, shown.ys[0], spec.linkedLog.logOffset));
    }
    traces.push(...styleKeyTraces(packed.names));
    if (spec.linkedLog) {
      const off = 10 ** spec.linkedLog.logOffset;
      for (const tr of traces) {
        if (!tr.y || tr.hoverinfo === "skip") continue;
        tr.customdata = tr.y.map((v) => (v == null || !Number.isFinite(v) ? null : v / off));
        tr.hovertemplate =
          `<b>${tr.name}</b>` +
          `<br>N<sub>ion</sub> = %{y:.3g} s<sup>−1</sup>` +
          `<br>L(Hα) = %{customdata:.3g} erg s<sup>−1</sup>` +
          `<extra></extra>`;
      }
    }
    const yRange = yAxisRange(allYs, spec.yLog);
    const headColor = livePlayheadColor(state, liveColor);
    auxCache.set(panel.id, true);
    react(
      `${panel.id}-plot`,
      traces,
      plotTheme(
        panel.title,
        spec.yTitle,
        logAge,
        spec.yLog,
        yRange,
        playheadShapes(logAge, headColor, pinAgeLines(state)),
        spec.linkedLog,
        spec.hoverY,
        panel.id,
      ),
    );
    ensureAgeClick(host);
  }
}
