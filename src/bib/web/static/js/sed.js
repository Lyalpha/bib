/* SED Explorer: population selection, age playback, pinning, dust, photometry. */
"use strict";

import { apiGet, apiUrl, reportError } from "./api.js";
import { PlaybackClock, attachPlaybar, lerp, locate } from "./playback.js";

const $ = (id) => document.getElementById(id);
const css = (name) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const PIN_COLORS = ["#ffb454", "#7ed4a5", "#e08bff", "#ff7d94", "#5fd3e8", "#c9d45e", "#f0a3ff"];

const state = {
  meta: null,
  filters: [],
  popId: null,
  frames: null, // sed_frames payload
  yRange: null,
  pins: [],
  pinSeq: 0,
  overlayCurves: [],
  customFilters: [], // {name, text}
  photRequest: 0,
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

  const imfs = [...new Set(pops.map((p) => p.imf))].sort();
  setOptions($("sel-imf"), imfs.map((v) => ({ value: v, label: v })));
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

function paramLabel() {
  const sel = currentSelection();
  const bits = [sel.imf, sel.z, sel.poptype];
  if (sel.alpha) bits.push(sel.alpha);
  bits.push(`logA=${Number($("sl-age").value * 0.1 + 6).toFixed(2)}`);
  const mass = Number($("sl-mass").value);
  if (mass !== 6) bits.push(`10^${mass.toFixed(1)} M☉`);
  const dust = dustParams();
  if (dust.dust_law) bits.push(`${dust.dust_law} E(B-V)=${dust.ebv}`);
  return bits.join(" · ");
}

/* -------------------------------------------------------------------- frames */

let framesToken = 0;

async function loadFrames() {
  const popId = resolvePopulation();
  if (popId === null) return;
  state.popId = popId;
  const token = ++framesToken;
  try {
    const data = await apiGet(`/populations/${popId}/sed_frames`, {
      mass: massMsun(),
      ...dustParams(),
    });
    if (token !== framesToken) return; // superseded
    state.frames = data;
    // Fixed y-range across all frames: keeps playback steady.
    let lo = Infinity,
      hi = -Infinity;
    for (const frame of data.frames) {
      for (const v of frame.flux) {
        if (v > 0) {
          if (v < lo) lo = v;
          if (v > hi) hi = v;
        }
      }
    }
    state.yRange = [Math.log10(Math.max(lo, hi * 1e-12)), Math.log10(hi) + 0.3];
    renderFrame(clock.t, true);
    schedulePhotometry();
  } catch (err) {
    reportError(err);
  }
}

/* ---------------------------------------------------------------------- plot */

function interpolatedFlux(t) {
  const frames = state.frames.frames;
  const ageIdx = t * 50;
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

function plotLayout() {
  const text = css("--brand-text") || "#e7ecf3";
  const grid = css("--brand-border") || "#2a3348";
  const muted = css("--brand-muted") || "#93a0b4";
  return {
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { color: text, size: 12.5 },
    margin: { l: 65, r: 55, t: 10, b: 45 },
    xaxis: {
      type: "log",
      title: { text: "wavelength (Å)" },
      gridcolor: grid,
      zeroline: false,
      range: [Math.log10(state.frames.wavelength[0]), Math.log10(state.frames.wavelength.at(-1))],
    },
    yaxis: {
      type: "log",
      title: { text: "F<sub>λ</sub> (L<sub>☉</sub> / Å)" },
      gridcolor: grid,
      zeroline: false,
      range: state.yRange,
      exponentformat: "power",
    },
    yaxis2: {
      overlaying: "y",
      side: "right",
      range: [0, 1.9],
      showgrid: false,
      tickvals: [0, 0.5, 1],
      title: { text: "filter transmission", font: { color: muted, size: 11 } },
      tickfont: { color: muted, size: 10 },
    },
    showlegend: true,
    legend: { orientation: "h", y: -0.18, font: { size: 11 } },
    hovermode: "closest",
  };
}

function renderFrame(t, relayout = false) {
  if (!state.frames) return;
  const { y, w, logAge } = interpolatedFlux(t);
  const x = state.frames.wavelength;

  const traces = [];
  for (const pin of state.pins) {
    traces.push({
      x: pin.x,
      y: pin.y,
      name: pin.label,
      mode: "lines",
      line: { color: pin.color, width: 1.3 },
      hovertemplate: "%{x:.4g} Å · %{y:.3g} L☉/Å<extra>" + pin.label + "</extra>",
    });
  }
  traces.push({
    x,
    y,
    name: `current (log age ${logAge.toFixed(2)})`,
    mode: "lines",
    line: { color: css("--brand-primary") || "#5aa9ff", width: 2.1 },
    hovertemplate: "%{x:.4g} Å · %{y:.3g} L☉/Å<extra>current</extra>",
  });
  for (const curve of state.overlayCurves) {
    traces.push({
      x: curve.wavelength,
      y: curve.transmission,
      name: curve.display_name,
      yaxis: "y2",
      mode: "lines",
      line: { width: 1, dash: "dot" },
      opacity: 0.75,
      hovertemplate: "%{x:.4g} Å · T=%{y:.2f}<extra>" + curve.display_name + "</extra>",
    });
  }

  Plotly.react("sed-plot", traces, plotLayout(), {
    responsive: true,
    displaylogo: false,
    modeBarButtonsToRemove: ["select2d", "lasso2d", "autoScale2d"],
  });

  // side effects: slider/outputs/notes
  const ageIdx = t * 50;
  $("sl-age").value = String(ageIdx);
  $("sl-age").style.setProperty("--fill", `${(ageIdx / 50) * 100}%`);
  $("out-age").textContent = (6 + ageIdx * 0.1).toFixed(2);
  const interpolating = w > 0.02 && w < 0.98;
  $("interp-note").textContent = interpolating
    ? "Showing an interpolated frame (visual only) — photometry always uses true grid ages."
    : "On-grid age — this frame is exactly as published.";
  updateExportLinks();
}

/* --------------------------------------------------------------- photometry */

let photTimer = null;

function schedulePhotometry() {
  clearTimeout(photTimer);
  photTimer = setTimeout(runPhotometry, 380);
}

async function runPhotometry() {
  if (state.popId === null) return;
  const ageIndex = Math.round(Number($("sl-age").value));
  const token = ++state.photRequest;
  $("phot-age").textContent = `log age ${(6 + ageIndex * 0.1).toFixed(1)}`;
  try {
    const data = await apiGet("/photometry", {
      population_id: state.popId,
      age_index: ageIndex,
      mass: massMsun(),
      ...dustParams(),
    });
    if (token !== state.photRequest) return;
    const rows = data.photometry.map(rowHtml);
    for (const custom of state.customFilters) {
      const result = await customPhotometry(custom, ageIndex);
      if (result) rows.push(rowHtml({ ...result, group: "custom" }, true));
    }
    if (token !== state.photRequest) return;
    $("phot-table").querySelector("tbody").innerHTML = rows.join("");
  } catch (err) {
    reportError(err);
  }
}

function rowHtml(entry, isCustom = false) {
  const mag = entry.ab_mag === null || entry.ab_mag === undefined ? "—" : entry.ab_mag.toFixed(3);
  const coverage =
    entry.coverage < 0.999
      ? `<span class="badge warn" title="Filter partially outside the SED wavelength range">${(entry.coverage * 100).toFixed(0)}%</span>`
      : "100%";
  const name = isCustom ? `<em>${entry.display_name}</em>` : entry.display_name;
  return `<tr><td>${name}</td><td class="muted">${entry.group}</td><td>${Math.round(entry.lambda_eff)}</td><td><strong>${mag}</strong></td><td>${coverage}</td></tr>`;
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
  const response = await fetch("/api/v1/photometry/custom", { method: "POST", body: form });
  if (!response.ok) {
    reportError(new Error((await response.json()).detail || "custom filter failed"));
    return null;
  }
  const payload = await response.json();
  return { ...payload.result, display_name: custom.name };
}

/* ------------------------------------------------------------------ overlay */

async function loadOverlay() {
  const group = $("sel-filtergroup").value;
  state.overlayCurves = [];
  if (group) {
    const names = state.filters.filter((f) => f.group === group).map((f) => f.name);
    try {
      state.overlayCurves = await Promise.all(
        names.map((n) => apiGet(`/filters/${encodeURIComponent(n)}/curve`))
      );
    } catch (err) {
      reportError(err);
    }
  }
  renderFrame(clock.t);
}

/* ------------------------------------------------------------------ exports */

function updateExportLinks() {
  if (state.popId === null) return;
  const ageIndex = Math.round(Number($("sl-age").value));
  const common = { age_index: ageIndex, mass: massMsun(), ...dustParams() };
  $("lnk-csv").href = apiUrl(`/populations/${state.popId}/sed`, {
    ...common,
    resolution: "native",
    format: "csv",
  });
  $("lnk-json").href = apiUrl(`/populations/${state.popId}/sed`, {
    ...common,
    resolution: "native",
  });
}

/* --------------------------------------------------------------------- pins */

function renderPins() {
  const host = $("pin-chips");
  host.innerHTML = "";
  for (const pin of state.pins) {
    const chip = document.createElement("span");
    chip.className = "chip";
    chip.style.setProperty("--chip-color", pin.color);
    chip.innerHTML = `<span class="dot"></span>${pin.label} <button title="Remove">×</button>`;
    chip.querySelector("button").addEventListener("click", () => {
      state.pins = state.pins.filter((p) => p !== pin);
      renderPins();
      renderFrame(clock.t);
    });
    host.appendChild(chip);
  }
}

/* --------------------------------------------------------------------- init */

const clock = new PlaybackClock({
  duration: 18,
  onTick: (t) => {
    renderFrame(t);
    schedulePhotometry();
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
    // filter groups
    for (const group of [...new Set(filters.map((f) => f.group))]) {
      const option = document.createElement("option");
      option.value = group;
      option.textContent = group;
      $("sel-filtergroup").appendChild(option);
    }

    rebuildSelectors();
    attachPlaybar($("sed-playbar"), clock, (t) => `log(age/yr) = ${(6 + t * 5).toFixed(2)}`);
    clock.scrub(Number($("sl-age").value) / 50);
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
  clock.scrub(Number($("sl-age").value) / 50);
});

$("sl-mass").addEventListener("input", () => {
  const value = Number($("sl-mass").value);
  const sup = "⁰¹²³⁴⁵⁶⁷⁸⁹";
  $("out-mass").textContent = Number.isInteger(value)
    ? `10${String(value).split("").map((c) => sup[+c]).join("")}`
    : `10^${value.toFixed(1)}`;
  $("sl-mass").style.setProperty("--fill", `${((value - 3) / 6) * 100}%`);
  debounceReload();
});

$("sel-dust").addEventListener("change", () => {
  const law = $("sel-dust").value;
  const lawMeta = state.meta.dust_laws.find((l) => l.key === law);
  $("grp-ebv").hidden = !law;
  $("grp-rv").hidden = !law || !lawMeta || lawMeta.fixed_rv !== null;
  debounceReload();
});
$("sl-ebv").addEventListener("input", () => {
  $("out-ebv").textContent = Number($("sl-ebv").value).toFixed(2);
  $("sl-ebv").style.setProperty("--fill", `${(Number($("sl-ebv").value) / 2) * 100}%`);
  debounceReload();
});
$("sl-rv").addEventListener("input", () => {
  $("out-rv").textContent = Number($("sl-rv").value).toFixed(1);
  $("sl-rv").style.setProperty("--fill", `${((Number($("sl-rv").value) - 2) / 4) * 100}%`);
  debounceReload();
});

let reloadTimer = null;
function debounceReload() {
  clearTimeout(reloadTimer);
  reloadTimer = setTimeout(loadFrames, 350);
}

$("btn-pin").addEventListener("click", () => {
  if (!state.frames) return;
  const { y } = interpolatedFlux(clock.t);
  state.pins.push({
    label: paramLabel(),
    x: state.frames.wavelength,
    y: y.slice(),
    color: PIN_COLORS[state.pinSeq++ % PIN_COLORS.length],
  });
  renderPins();
  renderFrame(clock.t);
});

$("sel-filtergroup").addEventListener("change", loadOverlay);

$("btn-png").addEventListener("click", () => {
  Plotly.downloadImage("sed-plot", {
    format: "png",
    width: 1400,
    height: 800,
    scale: 2,
    filename: "bib-sed",
  });
});

$("file-filter").addEventListener("change", async (event) => {
  const file = event.target.files[0];
  if (!file) return;
  const text = await file.text();
  state.customFilters.push({ name: file.name, text });
  event.target.value = "";
  schedulePhotometry();
});

init();
