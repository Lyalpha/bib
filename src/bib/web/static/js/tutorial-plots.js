import { apiGet } from "/static/js/api.js";
import { PLOT_GRID, logAxisTicks } from "/static/js/plot-axis.js";
import { hoverLabel } from "/static/js/ssp-plots.js?v=16";

const css = (name) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const COLORS = [
  () => css("--brand-primary") || "#5aa9ff",
  () => css("--brand-accent") || "#ffb454",
  () => css("--brand-accent-2") || "#7ee0a3",
  () => css("--brand-warn") || "#ff7b72",
  () => css("--brand-muted") || "#9aa7c7",
];

const FIDUCIAL_CODE = "imf135_300";
const DUST_EBV = 0.3;
const DUST_RV = 3.1;
const DUST_LOG_AGE = 7.0;
const IGM_Z = 3.0;
const IGM_LOG_AGE = 7.0;

function familyKey(imf) {
  return `${imf.form}:${imf.alpha}`;
}

function shortLabel(imf) {
  const form =
    imf.form === "chabrier" ? "Chabrier" : imf.form === "powerlaw" ? "Power-law" : "Broken";
  const slope = imf.alpha != null ? `α=${imf.alpha}` : imf.code;
  const cap = imf.m_max != null ? `${imf.m_max} M☉` : "";
  return [form, slope, cap].filter(Boolean).join(", ");
}

function styleOf(imf, families) {
  return {
    color: COLORS[families.indexOf(familyKey(imf)) % COLORS.length](),
    width: 2.4,
    dash: Number(imf.m_max) >= 300 ? "dash" : "solid",
  };
}

function interpLogLog(mass, y, query) {
  const out = new Array(query.length).fill(null);
  let j = 0;
  for (let i = 0; i < query.length; i++) {
    const x = query[i];
    if (!(x > 0) || x < mass[0] || x > mass[mass.length - 1]) continue;
    while (j < mass.length - 2 && mass[j + 1] < x) j++;
    const x0 = mass[j];
    const x1 = mass[j + 1];
    const y0 = y[j];
    const y1 = y[j + 1];
    if (!(y0 > 0 && y1 > 0 && x0 > 0 && x1 > 0 && x1 !== x0)) continue;
    const t = (Math.log(x) - Math.log(x0)) / (Math.log(x1) - Math.log(x0));
    out[i] = Math.exp(Math.log(y0) + t * (Math.log(y1) - Math.log(y0)));
  }
  return out;
}

function windowed(wl, flux, lo, hi) {
  const x = [];
  const y = [];
  for (let i = 0; i < wl.length; i++) {
    if (wl[i] >= lo && wl[i] <= hi && flux[i] > 0) {
      x.push(wl[i]);
      y.push(flux[i]);
    }
  }
  return { x, y };
}

function outsideLegend() {
  return {
    x: 1.02,
    y: 1,
    xanchor: "left",
    yanchor: "top",
    orientation: "v",
    bgcolor: "rgba(0,0,0,0)",
    borderwidth: 0,
    font: { size: 11 },
    tracegroupgap: 0,
    itemwidth: 28,
  };
}

function baseLayout({ xTitle, yTitle, xLog = true, yLog = true, xSpan = 3, ySpan = 6 }) {
  const text = css("--brand-text") || "#e8ecf8";
  const grid = PLOT_GRID;
  return {
    paper_bgcolor: "rgba(0,0,0,0)",
    plot_bgcolor: "rgba(0,0,0,0)",
    font: { color: text, size: 12 },
    margin: { l: 62, r: 168, t: 8, b: 48 },
    xaxis: {
      type: xLog ? "log" : "linear",
      title: { text: xTitle },
      gridcolor: grid,
      zeroline: false,
      ...(xLog ? logAxisTicks(xSpan) : { tickfont: { size: 11 } }),
    },
    yaxis: {
      type: yLog ? "log" : "linear",
      title: { text: yTitle },
      gridcolor: grid,
      zeroline: false,
      ...(yLog ? logAxisTicks(ySpan) : { tickfont: { size: 11 } }),
    },
    legend: outsideLegend(),
    hovermode: "closest",
    hoverlabel: hoverLabel(),
  };
}

function setNote(id, text) {
  const note = document.getElementById(id);
  if (note) note.textContent = text;
}

function draw(hostId, traces, layout) {
  const host = document.getElementById(hostId);
  if (!host) return;
  window.Plotly.newPlot(host, traces, layout, { displayModeBar: false, responsive: true });
}

function pickFiducialImf(imfs) {
  return (
    imfs.find((imf) => imf.code === FIDUCIAL_CODE) ||
    imfs.find((imf) => imf.form === "broken_powerlaw" && imf.alpha === 1.35 && Number(imf.m_max) >= 300)
  );
}

function pickFiducialPop(pops) {
  const src = pops || [];
  return (
    src.find((p) => p.imf === FIDUCIAL_CODE && p.z_label === "z020" && p.pop_type === "bin" && !p.alpha_label) ||
    src.find((p) => p.imf === FIDUCIAL_CODE && p.pop_type === "bin" && !p.alpha_label) ||
    src.find((p) => p.imf === FIDUCIAL_CODE && p.pop_type === "bin") ||
    src[0] ||
    null
  );
}

function renderImf(imfs) {
  const host = document.getElementById("imf-plot");
  if (!host) return;
  const list = imfs
    .filter((imf) => imf.mass && imf.dndm)
    .sort(
      (a, b) =>
        (a.form || "").localeCompare(b.form || "") ||
        (a.alpha ?? 0) - (b.alpha ?? 0) ||
        (a.m_max ?? 0) - (b.m_max ?? 0),
    );
  if (!list.length) {
    host.replaceChildren();
    setNote("imf-plot-note", "No populations are loaded, so there is nothing to plot.");
    return;
  }
  const families = [];
  for (const imf of list) {
    const key = familyKey(imf);
    if (!families.includes(key)) families.push(key);
  }
  const fiducial = pickFiducialImf(list);
  const showRatio = Boolean(fiducial) && list.length > 1;
  const traces = list.map((imf) => ({
    type: "scatter",
    mode: "lines",
    name: shortLabel(imf),
    legendgroup: shortLabel(imf),
    x: imf.mass,
    y: imf.dndm,
    yaxis: "y",
    line: styleOf(imf, families),
    hovertemplate: `${imf.label}<br>M = %{x:.2f} M☉<br>dN/dM = %{y:.3e}<extra></extra>`,
  }));
  if (showRatio) {
    for (const imf of list) {
      if (imf === fiducial) continue;
      const yInterp = interpLogLog(imf.mass, imf.dndm, fiducial.mass);
      const ratio = yInterp.map((v, i) => {
        const f = fiducial.dndm[i];
        return v > 0 && f > 0 ? v / f : null;
      });
      traces.push({
        type: "scatter",
        mode: "lines",
        name: shortLabel(imf),
        legendgroup: shortLabel(imf),
        showlegend: false,
        x: fiducial.mass,
        y: ratio,
        yaxis: "y2",
        line: styleOf(imf, families),
        hovertemplate: `${imf.label}<br>M = %{x:.2f} M☉<br>ratio = %{y:.3f} × fiducial<extra></extra>`,
      });
    }
  }
  const layout = {
    ...baseLayout({
      xTitle: "M / M☉",
      yTitle: "dN/dM  (stars per M☉, matched at 1 M☉)",
      xSpan: 3,
      ySpan: 8,
    }),
    yaxis: {
      ...baseLayout({
        xTitle: "M / M☉",
        yTitle: "dN/dM  (stars per M☉, matched at 1 M☉)",
        ySpan: 8,
      }).yaxis,
      domain: showRatio ? [0.4, 1] : [0, 1],
    },
    xaxis: {
      ...baseLayout({ xTitle: "M / M☉", yTitle: "" }).xaxis,
      anchor: showRatio ? "y2" : "y",
    },
    shapes: [],
  };
  if (showRatio) {
    layout.yaxis2 = {
      title: { text: `÷ ${shortLabel(fiducial)}` },
      gridcolor: PLOT_GRID,
      zeroline: false,
      domain: [0, 0.32],
      anchor: "x",
      tickfont: { size: 11 },
    };
    layout.shapes.push({
      type: "line",
      xref: "paper",
      x0: 0,
      x1: 1,
      yref: "y2",
      y0: 1,
      y1: 1,
      line: { color: css("--brand-text") || "#e8ecf8", width: 1, dash: "dot" },
    });
    host.classList.add("imf-stack");
  }
  draw("imf-plot", traces, layout);
}

async function renderDust(meta, pop) {
  const host = document.getElementById("dust-plot");
  if (!host) return;
  if (!pop) {
    host.replaceChildren();
    setNote("dust-plot-note", "No population is loaded, so there is nothing to plot.");
    return;
  }
  const laws = meta.dust_laws || [];
  const clean = await apiGet(`/populations/${pop.id}/sed`, {
    log_age: DUST_LOG_AGE,
    resolution: "display",
  });
  const dusty = await Promise.all(
    laws.map(async (law) => {
      const params = {
        log_age: DUST_LOG_AGE,
        resolution: "display",
        dust_law: law.key,
        ebv: DUST_EBV,
      };
      if (law.fixed_rv == null) params.rv = DUST_RV;
      const sed = await apiGet(`/populations/${pop.id}/sed`, params);
      return { law, sed };
    }),
  );
  const windows = dusty.map(({ law, sed }) => {
    const range = sed.dust?.applied_range_a || law.valid_range_a;
    return { lo: range[0], hi: range[1] };
  });
  const unionLo = Math.min(...windows.map((w) => w.lo));
  const unionHi = Math.max(...windows.map((w) => w.hi));
  const traces = [
    {
      type: "scatter",
      mode: "lines",
      name: "no dust",
      ...windowed(clean.wavelength, clean.flux, unionLo, unionHi),
      line: { color: css("--brand-muted") || "#9aa7c7", width: 2.2 },
      hovertemplate: "no dust<br>λ = %{x:.0f} Å<br>F<sub>λ</sub> = %{y:.3g} L☉/Å<extra></extra>",
    },
  ];
  dusty.forEach(({ law, sed }, i) => {
    const range = sed.dust?.applied_range_a || law.valid_range_a;
    const rv = sed.dust?.rv ?? law.fixed_rv ?? DUST_RV;
    const clipped = windowed(sed.wavelength, sed.flux, range[0], range[1]);
    traces.push({
      type: "scatter",
      mode: "lines",
      name: `${(law.label.split("—")[1] || law.label).trim()} (R<sub>V</sub>=${Number(rv).toFixed(2)})`,
      ...clipped,
      line: { color: COLORS[i % COLORS.length](), width: 2.3 },
      hovertemplate:
        `${law.label}<br>λ = %{x:.0f} Å<br>F<sub>λ</sub> = %{y:.3g} L☉/Å<extra></extra>`,
    });
  });
  draw(
    "dust-plot",
    traces,
    baseLayout({
      xTitle: "rest wavelength (Å)",
      yTitle: "F<sub>λ</sub> (L<sub>☉</sub> / Å)",
      xSpan: 1.6,
      ySpan: 4,
    }),
  );
}

async function renderIgm(meta, pop) {
  const host = document.getElementById("igm-plot");
  if (!host) return;
  if (!pop) {
    host.replaceChildren();
    setNote("igm-plot-note", "No population is loaded, so there is nothing to plot.");
    return;
  }
  const models = meta.igm_models || [];
  const none = await apiGet(`/populations/${pop.id}/sed`, {
    log_age: IGM_LOG_AGE,
    resolution: "display",
    redshift: IGM_Z,
    igm: "none",
  });
  const withIgm = await Promise.all(
    models.map(async (model) => {
      const sed = await apiGet(`/populations/${pop.id}/sed`, {
        log_age: IGM_LOG_AGE,
        resolution: "display",
        redshift: IGM_Z,
        igm: model.key,
      });
      return { model, sed };
    }),
  );
  const lya = (meta.lyman_alpha_a || 1215.67) * (1 + IGM_Z);
  const lo = 2000;
  const hi = lya * 1.25;
  const traces = [
    {
      type: "scatter",
      mode: "lines",
      name: "no IGM",
      ...windowed(none.wavelength, none.flux, lo, hi),
      line: { color: css("--brand-muted") || "#9aa7c7", width: 2.2 },
      hovertemplate: "no IGM<br>λ<sub>obs</sub> = %{x:.0f} Å<br>f<sub>λ</sub> = %{y:.3g}<extra></extra>",
    },
  ];
  withIgm.forEach(({ model, sed }, i) => {
    traces.push({
      type: "scatter",
      mode: "lines",
      name: model.label,
      ...windowed(sed.wavelength, sed.flux, lo, hi),
      line: { color: COLORS[i % COLORS.length](), width: 2.3 },
      hovertemplate: `${model.label}<br>λ<sub>obs</sub> = %{x:.0f} Å<br>f<sub>λ</sub> = %{y:.3g}<extra></extra>`,
    });
  });
  const layout = baseLayout({
    xTitle: "observed wavelength (Å)",
    yTitle: "observed f<sub>λ</sub>",
    xSpan: 0.7,
    ySpan: 4,
  });
  layout.shapes = [
    {
      type: "line",
      xref: "x",
      yref: "paper",
      x0: lya,
      x1: lya,
      y0: 0,
      y1: 1,
      line: { color: css("--brand-primary") || "#5aa9ff", width: 1, dash: "dot" },
    },
  ];
  layout.annotations = [
    {
      x: lya,
      y: 1,
      yref: "paper",
      yanchor: "bottom",
      text: "Lyα (1+z)",
      showarrow: false,
      font: { size: 11, color: css("--brand-muted") || "#9aa7c7" },
    },
  ];
  draw("igm-plot", traces, layout);
}

const imfHost = document.getElementById("imf-plot");
const dustHost = document.getElementById("dust-plot");
const igmHost = document.getElementById("igm-plot");
if (imfHost || dustHost || igmHost) {
  apiGet("/meta")
    .then(async (meta) => {
      if (imfHost) renderImf(meta.imfs || []);
      const pop = pickFiducialPop(meta.populations || []);
      if (dustHost) {
        try {
          await renderDust(meta, pop);
        } catch {
          dustHost.replaceChildren();
          setNote("dust-plot-note", "Could not load a dusty SED from the API.");
        }
      }
      if (igmHost) {
        try {
          await renderIgm(meta, pop);
        } catch {
          igmHost.replaceChildren();
          setNote("igm-plot-note", "Could not load a redshifted SED from the API.");
        }
      }
    })
    .catch(() => {
      if (imfHost) {
        imfHost.replaceChildren();
        setNote("imf-plot-note", "Could not load IMF curves from the API.");
      }
    });
}
