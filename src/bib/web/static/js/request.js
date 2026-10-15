/* Structured SSP data request: selectors in, honest download out. */
"use strict";

import { apiGet, apiUrl, reportError } from "./api.js";
import { syncRangeFill } from "./playback.js";
import { redshiftSliderMax, zFromSlider } from "./redshift-slider.js?v=1";

const $ = (id) => document.getElementById(id);

const RECIPES = [
  {
    id: "sed",
    product: "sed",
    title: "SED",
    blurb: "Spectrum of one population, one age or every age, with optional dust reddening.",
  },
  {
    id: "photometry",
    product: "photometry",
    title: "Photometry",
    blurb: "AB magnitudes in bundled filters at a redshift you choose.",
  },
  {
    id: "products",
    product: "products",
    title: "Population properties",
    blurb: "Ionizing flux, star counts, supernova rates, surviving mass, yields, colours and mass-to-light.",
  },
];

const state = {
  meta: null,
  options: null,
  filters: [],
  product: "sed",
};

function pops() {
  return state.meta?.populations || [];
}

function currentProduct() {
  return (state.options?.products || []).find((p) => p.key === state.product);
}

function popType() {
  return document.querySelector("input[name=poptype]:checked")?.value || "bin";
}

function units() {
  return document.querySelector("input[name=units]:checked")?.value || "native";
}

function format() {
  return document.querySelector("input[name=format]:checked")?.value || "csv";
}

function logAge() {
  return 6 + Number($("sl-age").value) * 0.1;
}

function massLog() {
  return Number($("sl-mass").value);
}

function massMsun() {
  return 10 ** massLog();
}

function formatMass(value) {
  const rounded = Math.round(Number(value) * 10) / 10;
  const exp = Number.isInteger(rounded) ? String(rounded) : rounded.toFixed(1);
  return `10<sup>${exp}</sup>`;
}

function releaseVersion(id) {
  return state.meta.releases.find((r) => r.id === id)?.version || "";
}

function unique(values) {
  return [...new Set(values.filter((v) => v != null && v !== ""))];
}

function setOptions(select, items, keep) {
  const current = keep ?? select.value;
  select.innerHTML = "";
  for (const item of items) {
    const opt = document.createElement("option");
    opt.value = item.value;
    opt.textContent = item.label;
    select.appendChild(opt);
  }
  if ([...select.options].some((o) => o.value === current)) select.value = current;
}

function imfLabel(code) {
  const info = state.meta.imfs?.find((i) => i.code === code);
  return info?.label || code;
}

function rebuildSelectors() {
  const releases = state.meta.releases || [];
  setOptions(
    $("sel-release"),
    releases.map((r) => ({ value: r.version, label: `${r.version}${r.name ? ` — ${r.name}` : ""}` })),
  );
  const release = $("sel-release").value;
  const inRelease = pops().filter((p) => releaseVersion(p.release_id) === release);
  const imfs = unique(inRelease.map((p) => p.imf));
  setOptions(
    $("sel-imf"),
    imfs.map((code) => ({ value: code, label: imfLabel(code) })),
  );
  const imf = $("sel-imf").value;
  const type = popType();
  const pool = inRelease.filter((p) => p.imf === imf && p.pop_type === type);
  const zs = [...pool].sort((a, b) => a.z_value - b.z_value);
  const zItems = [];
  const seen = new Set();
  for (const p of zs) {
    if (seen.has(p.z_label)) continue;
    seen.add(p.z_label);
    zItems.push({ value: p.z_label, label: `${p.z_label}  (Z = ${p.z_value})` });
  }
  setOptions($("sel-z"), zItems);
  if (!$("sel-z").dataset.touched && zItems.some((z) => z.value === "z020")) {
    $("sel-z").value = "z020";
  }
  const z = $("sel-z").value;
  const alphas = unique(pool.filter((p) => p.z_label === z).map((p) => p.alpha_label));
  $("grp-alpha").hidden = alphas.length === 0;
  setOptions(
    $("sel-alpha"),
    alphas.map((a) => ({ value: a, label: a })),
  );
}

function syncVisibility() {
  const spec = currentProduct();
  const physical = units() === "physical";
  $("lab-all-z").hidden = !spec?.allows_all_z;
  if (!spec?.allows_all_z) $("chk-all-z").checked = false;
  $("sel-z").disabled = $("chk-all-z").checked;
  $("grp-dust").hidden = !spec?.uses_dust;
  $("grp-redshift").hidden = !spec?.uses_redshift;
  $("grp-filters").hidden = !spec?.uses_filters;
  $("grp-mass").hidden = !physical || spec?.uses_mass === false;
  $("age-row").hidden = $("chk-all-ages").checked;
  const law = $("sel-dust").value;
  const dustLaw = (state.meta.dust_laws || []).find((d) => d.key === law);
  $("grp-ebv").hidden = !spec?.uses_dust || !law;
  $("grp-rv").hidden = !spec?.uses_dust || !law || !dustLaw || dustLaw.fixed_rv != null;
  const unit = (state.options.units || []).find((u) => u.key === units());
  $("units-note").textContent = unit?.description || "";
  const fmt = (state.options.formats || []).find((f) => f.key === format());
  $("format-note").textContent = fmt?.note || "";
  const z = zFromSlider($("sl-redshift").value);
  $("dl-note").textContent =
    z > 0
      ? `Observer frame · ${state.meta.cosmology?.label || "flat ΛCDM"}`
      : "Rest frame · photometry at 10 pc";
}

function queryParams() {
  const spec = currentProduct();
  const params = {
    product: state.product,
    release: $("sel-release").value,
    imf: $("sel-imf").value,
    pop_type: popType(),
    units: units(),
    format: format(),
  };
  if ($("chk-all-z").checked && spec?.allows_all_z) params.all_z = true;
  else params.z_label = $("sel-z").value;
  if (!$("grp-alpha").hidden && $("sel-alpha").value) params.alpha_label = $("sel-alpha").value;
  if ($("chk-all-ages").checked) params.all_ages = true;
  else params.log_age = logAge().toFixed(1);
  if (spec?.uses_dust && $("sel-dust").value) {
    params.dust_law = $("sel-dust").value;
    params.ebv = $("sl-ebv").value;
    const law = (state.meta.dust_laws || []).find((d) => d.key === $("sel-dust").value);
    if (law && law.fixed_rv == null) params.rv = $("sl-rv").value;
  }
  if (spec?.uses_redshift) params.redshift = String(zFromSlider($("sl-redshift").value));
  if (spec?.uses_filters && $("sel-filters").value) params.filters = $("sel-filters").value;
  if (units() === "physical" && spec?.uses_mass !== false) params.mass = String(massMsun());
  return params;
}

function requestUrl() {
  return apiUrl("/export", queryParams());
}

function sentence() {
  const spec = currentProduct();
  if (!spec) return "";
  const imf = imfLabel($("sel-imf").value);
  const type = popType() === "bin" ? "binary" : "single-star";
  const z = $("chk-all-z").checked ? "every loaded metallicity" : $("sel-z").value;
  const age = $("chk-all-ages").checked
    ? "all 51 grid ages"
    : `log₁₀(age/yr) = ${logAge().toFixed(1)}`;
  const unit = units() === "native" ? "as published by BPASS (10⁶ M☉ formed)" : `physical units for ${formatMass(massLog())} M☉ formed`;
  return `${spec.label} for a ${type} ${imf} population at ${z}, ${age}, ${unit}, as ${format().toUpperCase()}.`;
}

function fillMeta() {
  const spec = currentProduct();
  const rows = [
    ["Product", spec?.label || "—"],
    ["Release", $("sel-release").value],
    ["IMF", imfLabel($("sel-imf").value)],
    ["Type", popType() === "bin" ? "binary" : "single-star"],
    ["Metallicity", $("chk-all-z").checked ? "all loaded Z" : $("sel-z").value],
    ["Age", $("chk-all-ages").checked ? "all grid ages" : logAge().toFixed(1)],
    ["Units", units() === "native" ? "as published" : "physical"],
    ["Format", format().toUpperCase()],
  ];
  if (spec?.uses_dust) {
    rows.push(["Extinction", $("sel-dust").value ? `${$("sel-dust").value}, E(B−V)=${$("sl-ebv").value}` : "none"]);
  }
  if (spec?.uses_redshift) rows.push(["Redshift", zFromSlider($("sl-redshift").value).toFixed(2)]);
  $("request-meta").innerHTML = rows
    .map(([k, v]) => `<div><dt>${k}</dt><dd>${v}</dd></div>`)
    .join("");
}

function esc(value) {
  return String(value).replace(/[&<>]/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[ch]));
}

function fieldCells(field, physical, productKey) {
  if (physical && productKey === "sn_rates" && field.name === "bin_width_yr") return null;
  let description = field.description;
  if (physical && field.kind === "log") description += " (linear)";
  if (physical && productKey === "sn_rates" && field.name.startsWith("n_")) {
    description += " (count × formed-mass scale / age-bin width)";
  }
  return [
    physical ? field.physical_name : field.name,
    physical ? field.unit_physical : field.unit_native,
    description,
  ];
}

function columnHints() {
  const spec = currentProduct();
  const body = $("col-table").querySelector("tbody");
  const physical = units() === "physical";
  const rows = [];
  const add = (name, unit, description) => rows.push(["col", name, unit, description]);
  const group = (label) => rows.push(["group", label]);
  if (spec?.key === "sed") {
    const z = zFromSlider($("sl-redshift").value);
    add(
      z > 0 ? "wavelength_angstrom_observed" : "wavelength_angstrom",
      "Å",
      z > 0 ? "Observer-frame wavelength (λ_rest × (1+z))" : "Rest-frame wavelength",
    );
    add(
      "flux",
      z > 0 ? "erg s⁻¹ cm⁻² Å⁻¹" : physical ? "L☉ Å⁻¹" : "L☉ Å⁻¹ / 10⁶ M☉ formed",
      z > 0 ? "Observer-frame f_λ at D_L; extinction applied in the rest frame" : "Rest-frame luminosity density",
    );
  } else if (spec?.key === "photometry") {
    if ($("chk-all-ages").checked) add("log_age", "dex (yr)", "log₁₀(age / yr) on the BPASS 0.1 dex grid");
    add("filter", "", "Bundled filter id");
    add("display_name", "", "Filter display name");
    add("group", "", "Instrument or survey");
    add("lambda_eff", "Å", "Effective wavelength");
    add("ab_mag", "mag (AB)", zFromSlider($("sl-redshift").value) > 0 ? "Apparent AB magnitude" : "Absolute AB magnitude at 10 pc");
    add("coverage", "fraction", "Fraction of the filter transmission that overlaps the SED");
  } else if (spec?.bundle) {
    group("Age");
    add("log_age", "dex (yr)", "log₁₀(age / yr) on the BPASS 0.1 dex grid");
    add("age_yr", "yr", "Age in years, 10^log_age");
    for (const child of state.options?.products || []) {
      if (!child.fields?.length) continue;
      group(child.label);
      for (const field of child.fields) {
        const cells = fieldCells(field, physical, child.key);
        if (!cells) continue;
        add(`${child.key}__${cells[0]}`, cells[1], cells[2]);
      }
    }
  }
  body.innerHTML = rows
    .map((row) =>
      row[0] === "group"
        ? `<tr class="col-group"><td colspan="3">${esc(row[1])}</td></tr>`
        : `<tr><td>${esc(row[1])}</td><td>${esc(row[2])}</td><td class="wrap">${esc(row[3])}</td></tr>`,
    )
    .join("");
}

function refresh() {
  syncVisibility();
  $("request-sentence").innerHTML = sentence();
  fillMeta();
  columnHints();
  $("request-url").textContent = requestUrl();
}

function applyRecipe(recipe) {
  state.product = recipe.product;
  $("chk-all-z").checked = Boolean(recipe.all_z);
  highlightRecipes();
  refresh();
}

function highlightRecipes() {
  for (const btn of document.querySelectorAll(".recipe")) {
    btn.classList.toggle("is-active", btn.dataset.product === state.product && (btn.dataset.allZ === "1") === $("chk-all-z").checked);
  }
  const exact = [...document.querySelectorAll(".recipe")].find(
    (b) => b.dataset.product === state.product && (b.dataset.allZ === "1") === $("chk-all-z").checked,
  );
  if (!exact) {
    for (const btn of document.querySelectorAll(".recipe")) {
      btn.classList.toggle("is-active", btn.dataset.product === state.product && btn.dataset.allZ !== "1");
    }
  }
}

function renderRecipes() {
  const host = $("recipe-list");
  host.innerHTML = "";
  for (const recipe of RECIPES) {
    const btn = document.createElement("button");
    btn.type = "button";
    btn.className = "recipe";
    btn.dataset.product = recipe.product;
    btn.dataset.allZ = recipe.all_z ? "1" : "0";
    btn.innerHTML = `<strong>${recipe.title}</strong><span>${recipe.blurb}</span>`;
    btn.addEventListener("click", () => applyRecipe(recipe));
    host.appendChild(btn);
  }
}

function updateAge() {
  $("out-age").textContent = logAge().toFixed(1);
  syncRangeFill($("sl-age"));
}

async function init() {
  try {
    const [meta, options, filters] = await Promise.all([
      apiGet("/meta"),
      apiGet("/export/options"),
      apiGet("/filters"),
    ]);
    state.meta = meta;
    state.options = options;
    state.filters = filters;
    for (const law of meta.dust_laws || []) {
      const opt = document.createElement("option");
      opt.value = law.key;
      opt.textContent = law.label;
      $("sel-dust").appendChild(opt);
    }
    const groups = [...new Set(filters.map((f) => f.group).filter(Boolean))];
    for (const group of groups) {
      const opt = document.createElement("option");
      const names = filters.filter((f) => f.group === group).map((f) => f.name);
      opt.value = names.join(",");
      opt.textContent = `${group} (${names.length})`;
      $("sel-filters").appendChild(opt);
    }
    if (meta.cosmology) {
      $("sl-redshift").max = String(redshiftSliderMax());
      $("sl-redshift").step = "1";
    }
    renderRecipes();
    rebuildSelectors();
    applyRecipe(RECIPES[0]);
    updateAge();
    syncRangeFill($("sl-redshift"));
    syncRangeFill($("sl-ebv"));
    syncRangeFill($("sl-rv"));
    updateMass();
    refresh();
  } catch (err) {
    reportError(err);
  }
}

$("sel-release").addEventListener("change", () => {
  rebuildSelectors();
  refresh();
});
$("sel-imf").addEventListener("change", () => {
  rebuildSelectors();
  refresh();
});
$("sel-z").addEventListener("change", () => {
  $("sel-z").dataset.touched = "1";
  rebuildSelectors();
  refresh();
});
$("sel-alpha").addEventListener("change", refresh);
$("seg-poptype").addEventListener("change", () => {
  rebuildSelectors();
  refresh();
});
$("chk-all-z").addEventListener("change", () => {
  highlightRecipes();
  refresh();
});
$("chk-all-ages").addEventListener("change", refresh);
$("sl-age").addEventListener("input", () => {
  updateAge();
  refresh();
});
$("sel-dust").addEventListener("change", refresh);
$("sl-ebv").addEventListener("input", () => {
  $("out-ebv").textContent = Number($("sl-ebv").value).toFixed(2);
  syncRangeFill($("sl-ebv"));
  refresh();
});
$("sl-rv").addEventListener("input", () => {
  $("out-rv").textContent = Number($("sl-rv").value).toFixed(1);
  syncRangeFill($("sl-rv"));
  refresh();
});
$("sl-redshift").addEventListener("input", () => {
  $("out-redshift").textContent = zFromSlider($("sl-redshift").value).toFixed(2);
  syncRangeFill($("sl-redshift"));
  refresh();
});
$("sel-filters").addEventListener("change", refresh);
$("seg-units").addEventListener("change", refresh);
function updateMass() {
  $("out-mass").innerHTML = formatMass(massLog());
  syncRangeFill($("sl-mass"));
}

$("sl-mass").addEventListener("input", () => {
  updateMass();
  refresh();
});
$("seg-format").addEventListener("change", refresh);

$("btn-download").addEventListener("click", () => {
  window.location.href = requestUrl();
});
$("btn-copy").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(requestUrl());
    $("btn-copy").textContent = "Copied";
    setTimeout(() => {
      $("btn-copy").textContent = "Copy URL";
    }, 1500);
  } catch (err) {
    reportError(err);
  }
});

init();
