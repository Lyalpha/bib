/* Star Explorer: animated stellar tracks on the HRD + binary visualiser + readout. */
"use strict";

import { apiGet, decodeB64U8, reportError } from "./api.js";
import { BinaryViz } from "./binaryviz.js";
import { PlaybackClock, attachPlaybar, lerp, locate, syncAllRangeFills, syncRangeFill } from "./playback.js";

const $ = (id) => document.getElementById(id);
const css = (name) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const EVENT_SYMBOLS = {
  zams: "circle",
  tams: "diamond",
  he_exhaustion: "square",
  c_burning: "pentagon",
  giant_branch: "triangle-up",
  wr_onset: "star",
  rlof_start: "triangle-right",
  rlof_end: "triangle-left",
  cee: "hexagram",
  thermal_pulses: "cross",
  endpoint: "x",
};

const state = {
  models: [],
  track: null, // /models/{id}/track payload
  hrd: null, // decoded backdrop {frames: Float32-like z per age}, or null
  hrdIdx: -1,
  ceeWindows: [], // [start, end] index ranges
  viz: null,
};

/* ------------------------------------------------------------------ helpers */

function arr(name) {
  return state.track.arrays[name];
}

function interpAt(values, fidx) {
  const i0 = Math.floor(fidx);
  const i1 = Math.min(i0 + 1, values.length - 1);
  const w = fidx - i0;
  const a = values[i0];
  const b = values[i1];
  if (a === null || a === undefined) return b === null || b === undefined ? NaN : b;
  if (b === null || b === undefined) return a;
  return lerp(a, b, w);
}

function fmtAge(ageYr) {
  if (!isFinite(ageYr)) return "—";
  if (ageYr < 1e6) return `${(ageYr / 1e3).toFixed(1)} kyr`;
  if (ageYr < 1e9) return `${(ageYr / 1e6).toFixed(2)} Myr`;
  return `${(ageYr / 1e9).toFixed(3)} Gyr`;
}

function fmtPeriod(periodYr) {
  if (!isFinite(periodYr) || periodYr <= 0) return "—";
  const days = periodYr * 365.25;
  if (days < 1000) return `${days.toFixed(days < 10 ? 2 : 1)} d`;
  return `${periodYr.toFixed(1)} yr`;
}

function fmtSci(v, digits = 2) {
  if (!isFinite(v)) return "—";
  if (v === 0) return "0";
  const exp = Math.floor(Math.log10(Math.abs(v)));
  if (exp >= -2 && exp <= 3) return v.toPrecision(3);
  return `${(v / Math.pow(10, exp)).toFixed(digits)}e${exp}`;
}

/* ------------------------------------------------------------- model picker */

function rebuildModelList() {
  const z = $("sel-z").value;
  const kind = $("sel-kind").value;
  const models = state.models.filter(
    (m) => (!z || m.z_label === z) && (!kind || m.kind === kind)
  );
  const select = $("sel-model");
  select.innerHTML = "";
  for (const m of models) {
    const option = document.createElement("option");
    option.value = String(m.id);
    const params =
      m.kind === "single"
        ? `${m.m1_init ?? "?"} M☉`
        : m.kind === "primary"
          ? `${m.m1_init} M☉, q=${m.q_init}, logP=${m.logp_init}`
          : `${m.m1_init} M☉ + ${m.mrem_init} M☉ remnant`;
    option.textContent = m.title ? `${m.title}` : `${m.filename} (${params})`;
    option.title = params;
    select.appendChild(option);
  }
  if (models.length) {
    select.value = String(models[0].id);
    loadTrack(Number(select.value));
  }
}

function renderModelInfo(model) {
  const bits = [];
  bits.push(`<strong>${model.title || model.filename}</strong>`);
  const params = [];
  if (model.m1_init) params.push(`M<sub>1</sub>=${model.m1_init} M☉`);
  if (model.q_init) params.push(`q=${model.q_init}`);
  if (model.logp_init !== null && model.logp_init !== undefined)
    params.push(`log P=${model.logp_init}`);
  if (model.mrem_init) params.push(`M<sub>rem</sub>=${model.mrem_init} M☉`);
  params.push(`Z=${model.z_value}`);
  bits.push(`<div class="small muted">${params.join(" · ")}</div>`);
  if (model.description) bits.push(`<div class="small" style="margin-top:0.4rem;">${model.description}</div>`);
  bits.push(
    `<div class="small muted" style="margin-top:0.4rem;">${state.track.n_points} plotted points` +
      (state.track.n_points_full > state.track.n_points
        ? ` (decimated from ${state.track.n_points_full})`
        : "") +
      `</div>`
  );
  $("model-info").innerHTML = bits.join("");
}

/* ------------------------------------------------------------------- track */

async function loadTrack(modelId) {
  try {
    const track = await apiGet(`/models/${modelId}/track`);
    state.track = track;
    computeCeeWindows();
    renderModelInfo(track.model);
    renderEventChips();
    await loadBackdrop(track.model.z_label);
    clock.pause();
    clock.scrub(0);
    updateVizCaption();
  } catch (err) {
    reportError(err);
  }
}

function computeCeeWindows() {
  const events = state.track.events;
  state.ceeWindows = [];
  for (const event of events) {
    if (event.event_type !== "cee") continue;
    const end = events.find(
      (e) => e.event_type === "rlof_end" && e.index > event.index
    );
    state.ceeWindows.push([event.index - 0.5, end ? end.index : event.index + 6]);
  }
}

function ceeActiveAt(fidx) {
  return state.ceeWindows.some(([a, b]) => fidx >= a && fidx <= b);
}

/* ---------------------------------------------------------------- backdrop */

async function loadBackdrop(zLabel) {
  state.hrd = null;
  state.hrdIdx = -1;
  try {
    const meta = await apiGet("/meta");
    const candidate = meta.populations.find(
      (p) => p.z_label === zLabel && p.pop_type === "bin" && !p.alpha_label
    );
    if (!candidate) return;
    const payload = await apiGet(`/populations/${candidate.id}/hrd`, { diagram: "TL" });
    const { lo, hi } = payload.scale;
    state.hrd = {
      logAges: payload.frames.map((f) => f.log_age),
      frames: payload.frames.map((f) => {
        const q = decodeB64U8(f.grid);
        // z[col][row] for plotly: y=logL (columns of the stored grid), x=logT (rows)
        const z = [];
        for (let c = 0; c < 100; c++) {
          const rowArr = new Array(100);
          for (let r = 0; r < 100; r++) {
            const v = q[r * 100 + c];
            rowArr[r] = v === 0 ? null : lo + (v / 255) * (hi - lo);
          }
          z.push(rowArr);
        }
        return z;
      }),
      x: Array.from({ length: 100 }, (_, r) => 0.1 + 0.1 * r),
      y: Array.from({ length: 100 }, (_, c) => -2.9 + 0.1 * c),
    };
  } catch {
    state.hrd = null; // no backdrop available: fine
  }
}

/* -------------------------------------------------------------------- plot */

function trackRanges() {
  const lt = arr("log_t1").filter((v) => v !== null);
  const ll = arr("log_l1").filter((v) => v !== null);
  const lt2 = (arr("log_t2") || []).filter((v) => v !== null && isFinite(v));
  const ll2 = (arr("log_l2") || []).filter((v) => v !== null && isFinite(v));
  const allT = lt.concat(lt2);
  const allL = ll.concat(ll2);
  return {
    x: [Math.max(...allT) + 0.15, Math.min(...allT) - 0.15], // reversed
    y: [Math.min(...allL) - 0.35, Math.max(...allL) + 0.35],
  };
}

function renderHrd(fidx) {
  const track = state.track;
  const n = arr("age_yr").length;
  const idx = Math.floor(fidx);
  const text = css("--brand-text") || "#e7ecf3";
  const grid = "rgba(154, 167, 199, 0.16)";
  const border = css("--brand-border") || "#2a3348";
  const primary = css("--brand-primary") || "#5aa9ff";
  const accent = css("--brand-accent") || "#ffb454";
  const ranges = trackRanges();

  const traces = [];

  // density backdrop, synced to the current stellar age
  if (state.hrd && $("chk-backdrop").checked) {
    const age = interpAt(arr("age_yr"), fidx);
    const logAge = Math.log10(Math.max(age, 1));
    const [i0, i1, w] = locate(state.hrd.logAges, logAge);
    const hrdIdx = w < 0.5 ? i0 : i1;
    traces.push({
      type: "heatmap",
      x: state.hrd.x,
      y: state.hrd.y,
      z: state.hrd.frames[hrdIdx],
      colorscale: [
        [0, "rgba(90,169,255,0.03)"],
        [0.6, "rgba(90,169,255,0.20)"],
        [1, "rgba(160,210,255,0.45)"],
      ],
      zsmooth: "best",
      showscale: false,
      hoverinfo: "skip",
      name: "population",
    });
  }

  // full track (faint) + traversed portion (bright)
  traces.push({
    x: arr("log_t1"),
    y: arr("log_l1"),
    mode: "lines",
    line: { color: "rgba(160,175,200,0.35)", width: 1.4 },
    name: "full track",
    hoverinfo: "skip",
  });
  traces.push({
    x: arr("log_t1").slice(0, idx + 2),
    y: arr("log_l1").slice(0, idx + 2),
    mode: "lines",
    line: { color: primary, width: 2.4 },
    name: "so far",
    hoverinfo: "skip",
  });

  // events
  traces.push({
    x: track.events.map((e) => arr("log_t1")[e.index]),
    y: track.events.map((e) => arr("log_l1")[e.index]),
    mode: "markers",
    marker: {
      symbol: track.events.map((e) => EVENT_SYMBOLS[e.event_type] || "circle"),
      size: 10,
      color: "rgba(255,220,150,0.9)",
      line: { color: "rgba(0,0,0,0.6)", width: 1 },
    },
    text: track.events.map((e) => e.label),
    hovertemplate: "%{text}<extra></extra>",
    name: "events",
  });

  // companion position (when it has estimates)
  const lt2 = interpAt(arr("log_t2"), fidx);
  const ll2 = interpAt(arr("log_l2"), fidx);
  if (isFinite(lt2) && isFinite(ll2)) {
    traces.push({
      x: [lt2],
      y: [ll2],
      mode: "markers",
      marker: { size: 9, color: accent, symbol: "circle-open", line: { width: 2 } },
      name: "companion",
      hovertemplate: "companion<extra></extra>",
    });
  }

  // current star
  traces.push({
    x: [interpAt(arr("log_t1"), fidx)],
    y: [interpAt(arr("log_l1"), fidx)],
    mode: "markers",
    marker: {
      size: 13,
      color: primary,
      symbol: "circle",
      line: { color: "white", width: 1.5 },
    },
    name: "star",
    hovertemplate: "log T=%{x:.3f}, log L=%{y:.3f}<extra></extra>",
  });

  Plotly.react(
    "hr-plot",
    traces,
    {
      paper_bgcolor: "rgba(0,0,0,0)",
      plot_bgcolor: "rgba(0,0,0,0)",
      font: { color: text, size: 12.5 },
      margin: { l: 60, r: 15, t: 12, b: 48 },
      xaxis: {
        title: { text: "log₁₀ T_eff (K)" },
        range: ranges.x,
        gridcolor: grid,
        gridwidth: 1,
        zeroline: false,
      },
      yaxis: {
        title: { text: "log₁₀ L (L☉)" },
        range: ranges.y,
        gridcolor: grid,
        gridwidth: 1,
        zeroline: false,
      },
      showlegend: false,
      hovermode: "closest",
      hoverlabel: {
        bgcolor: "#141b30",
        bordercolor: border,
        font: { color: text, size: 12 },
      },
    },
    { responsive: true, displaylogo: false, modeBarButtonsToRemove: ["select2d", "lasso2d"] }
  );
}

/* ------------------------------------------------------------------ readout */

const READOUT_FIELDS = [
  ["age", "Age"],
  ["m1", "Mass M₁"],
  ["logt", "log T_eff"],
  ["logl", "log L"],
  ["r1", "Radius"],
  ["mdot", "Ṁ (wind+strip)"],
  ["he", "He core"],
  ["co", "CO core"],
  ["xsurf", "Surface X"],
  ["ysurf", "Surface Y"],
  ["cno", "Surface CNO"],
  ["m2", "Companion M₂"],
  ["period", "Orbital period"],
  ["sep", "Separation"],
  ["fill", "Roche filling"],
  ["state", "State"],
];

function buildReadout() {
  $("readout").innerHTML = READOUT_FIELDS.map(
    ([key, label]) =>
      `<div class="item"><span class="k">${label}</span><span class="v" id="ro-${key}">—</span></div>`
  ).join("");
}

function updateReadout(fidx) {
  const set = (key, value) => ($(`ro-${key}`).textContent = value);
  const age = interpAt(arr("age_yr"), fidx);
  const m1 = interpAt(arr("m1"), fidx);
  const r1 = interpAt(arr("r1_rsun"), fidx);
  const mdot = interpAt(arr("mdot1"), fidx);
  const rl1 = interpAt(arr("rl1_rsun"), fidx);
  const sep = interpAt(arr("sep_rsun"), fidx);
  const m2 = interpAt(arr("m2"), fidx);
  const fill = r1 / rl1;

  set("age", fmtAge(age));
  set("m1", `${m1.toFixed(2)} M☉`);
  set("logt", interpAt(arr("log_t1"), fidx).toFixed(3));
  set("logl", interpAt(arr("log_l1"), fidx).toFixed(3));
  set("r1", `${fmtSci(r1)} R☉`);
  set("mdot", isFinite(mdot) && mdot > 0 ? `${fmtSci(mdot)} M☉/yr` : "≈0");
  set("he", `${interpAt(arr("he_core"), fidx).toFixed(2)} M☉`);
  set("co", `${interpAt(arr("co_core"), fidx).toFixed(2)} M☉`);
  set("xsurf", interpAt(arr("x_surf"), fidx).toFixed(3));
  set("ysurf", interpAt(arr("y_surf"), fidx).toFixed(3));
  const cno =
    interpAt(arr("c_surf"), fidx) + interpAt(arr("n_surf"), fidx) + interpAt(arr("o_surf"), fidx);
  set("cno", isFinite(cno) ? cno.toFixed(4) : "—");
  set("m2", isFinite(m2) ? `${m2.toFixed(2)} M☉` : "—");
  set("period", fmtPeriod(interpAt(arr("period_yr"), fidx)));
  set("sep", isFinite(sep) ? `${fmtSci(sep)} R☉` : "—");
  set("fill", isFinite(fill) ? `${(fill * 100).toFixed(0)}%` : "—");

  const idx = Math.round(fidx);
  const rlof = state.track.arrays.rlof_active[Math.min(idx, state.track.arrays.rlof_active.length - 1)];
  const cee = ceeActiveAt(fidx);
  set("state", cee ? "common envelope!" : rlof ? "mass transfer (RLOF)" : "detached");
}

/* ---------------------------------------------------------------- event UI */

function renderEventChips() {
  const host = $("event-chips");
  host.innerHTML = "";
  const n = arr("age_yr").length;
  for (const event of state.track.events) {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.style.cursor = "pointer";
    chip.innerHTML = `<span class="dot" style="--chip-color:${
      event.event_type === "cee" || event.event_type.startsWith("rlof")
        ? "var(--brand-accent)"
        : "var(--brand-primary)"
    }"></span>${event.label}`;
    chip.title = (event.note || "") + ` — ${fmtAge(event.age_yr)}`;
    chip.addEventListener("click", () => {
      clock.pause();
      clock.scrub(event.index / (n - 1));
    });
    host.appendChild(chip);
  }
}

/* -------------------------------------------------------------------- tick */

function updateViz(fidx) {
  const model = state.track.model;
  const sep = interpAt(arr("sep_rsun"), fidx);
  const m2 = interpAt(arr("m2"), fidx);
  const isBinary = isFinite(sep) && isFinite(m2);
  const mdot = interpAt(arr("mdot1"), fidx);
  const windHalo = mdot > 1e-8 ? Math.min(Math.log10(mdot / 1e-8) / 3.5, 1) : 0;
  const r2 = interpAt(arr("r2_rsun"), fidx);
  const idx = Math.min(Math.round(fidx), state.track.arrays.rlof_active.length - 1);

  state.viz.setState({
    mode: isBinary ? "binary" : "single",
    r1: interpAt(arr("r1_rsun"), fidx),
    t1: Math.pow(10, interpAt(arr("log_t1"), fidx)),
    m1: interpAt(arr("m1"), fidx),
    r2: r2,
    t2: Math.pow(10, interpAt(arr("log_t2"), fidx)),
    m2: m2,
    sep,
    periodYr: interpAt(arr("period_yr"), fidx),
    rl1: interpAt(arr("rl1_rsun"), fidx),
    rl2: interpAt(arr("rl2_rsun"), fidx),
    fill1: interpAt(arr("r1_rsun"), fidx) / interpAt(arr("rl1_rsun"), fidx),
    fill2: r2 / interpAt(arr("rl2_rsun"), fidx),
    mdot1: mdot,
    windHalo,
    rlofActive: Boolean(state.track.arrays.rlof_active[idx]),
    ceeActive: ceeActiveAt(fidx),
    compact2: model.kind === "secondary" || (isBinary && (!isFinite(r2) || r2 <= 0)),
  });
}

function updateVizCaption() {
  const model = state.track.model;
  $("viz-caption").textContent =
    model.kind === "single"
      ? "Single star — colour from T_eff, size to scale, halo = strong wind."
      : model.kind === "secondary"
        ? "Star + compact remnant. Orbit speed is accelerated for display."
        : "Binary pair to scale: separation, radii and colours track the model. Orbit speed is accelerated for display.";
}

function onTick(t) {
  if (!state.track) return;
  const n = arr("age_yr").length;
  const fidx = t * (n - 1);
  renderHrd(fidx);
  updateReadout(fidx);
  updateViz(fidx);
}

/* -------------------------------------------------------------------- init */

const clock = new PlaybackClock({ duration: 24, onTick });

async function init() {
  buildReadout();
  state.viz = new BinaryViz($("binary-canvas"));
  try {
    state.models = await apiGet("/models");
    const zs = [...new Set(state.models.map((m) => m.z_label))].sort();
    $("sel-z").innerHTML = zs
      .map((z) => `<option value="${z}" ${z === "z020" ? "selected" : ""}>${z}</option>`)
      .join("");
    attachPlaybar($("hr-playbar"), clock, (t) => {
      if (!state.track) return "—";
      const n = arr("age_yr").length;
      return `age = ${fmtAge(interpAt(arr("age_yr"), t * (n - 1)))}`;
    });
    rebuildModelList();
  } catch (err) {
    reportError(err);
  }
}

$("sel-z").addEventListener("change", rebuildModelList);
$("sel-kind").addEventListener("change", rebuildModelList);
$("sel-model").addEventListener("change", () => loadTrack(Number($("sel-model").value)));
$("chk-backdrop").addEventListener("change", () => onTick(clock.t));
$("chk-truescale").addEventListener("change", () => {
  state.viz.fitMode = $("chk-truescale").checked ? "true" : "auto";
});
$("sl-orbit").addEventListener("input", () => {
  const boost = Math.pow(2, Number($("sl-orbit").value));
  state.viz.orbitBoost = boost;
  $("out-orbit").textContent = `${boost >= 1 ? boost.toFixed(1) : boost.toFixed(2)}×`;
  syncRangeFill($("sl-orbit"));
});
$("chk-orbit-stop").addEventListener("change", () => {
  const frozen = $("chk-orbit-stop").checked;
  state.viz.orbitFrozen = frozen;
  $("sl-orbit").disabled = frozen;
});

syncAllRangeFills();
init();
