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

/** Log–log interpolation of y(x) onto query masses; null outside the source range. */
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

function pickFiducial(imfs) {
  return (
    imfs.find((imf) => imf.code === FIDUCIAL_CODE) ||
    imfs.find((imf) => imf.form === "broken_powerlaw" && imf.alpha === 1.35 && Number(imf.m_max) >= 300)
  );
}

const host = document.getElementById("imf-plot");
if (host) {
  apiGet("/meta")
    .then((meta) => {
      const imfs = (meta.imfs || [])
        .filter((imf) => imf.mass && imf.dndm)
        .sort(
          (a, b) =>
            (a.form || "").localeCompare(b.form || "") ||
            (a.alpha ?? 0) - (b.alpha ?? 0) ||
            (a.m_max ?? 0) - (b.m_max ?? 0),
        );
      const note = document.getElementById("imf-plot-note");
      if (!imfs.length) {
        host.replaceChildren();
        if (note) note.textContent = "No populations are loaded, so there is nothing to plot.";
        return;
      }
      const families = [];
      for (const imf of imfs) {
        const key = familyKey(imf);
        if (!families.includes(key)) families.push(key);
      }
      const fiducial = pickFiducial(imfs);
      const showRatio = Boolean(fiducial) && imfs.length > 1;
      const text = css("--brand-text") || "#e8ecf8";
      const grid = PLOT_GRID;

      const traces = imfs.map((imf) => ({
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
        for (const imf of imfs) {
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
            hovertemplate:
              `${imf.label}<br>M = %{x:.2f} M☉<br>ratio = %{y:.3f} × fiducial<extra></extra>`,
          });
        }
      }

      const layout = {
        paper_bgcolor: "rgba(0,0,0,0)",
        plot_bgcolor: "rgba(0,0,0,0)",
        font: { color: text, size: 12 },
        margin: { l: 62, r: 168, t: 8, b: 48 },
        xaxis: {
          type: "log",
          title: { text: "M / M☉" },
          gridcolor: grid,
          zeroline: false,
          anchor: showRatio ? "y2" : "y",
          ...logAxisTicks(3),
        },
        yaxis: {
          type: "log",
          title: { text: "dN/dM  (stars per M☉, matched at 1 M☉)" },
          gridcolor: grid,
          zeroline: false,
          domain: showRatio ? [0.4, 1] : [0, 1],
          ...logAxisTicks(8),
        },
        legend: {
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
        },
        hovermode: "closest",
        hoverlabel: hoverLabel(),
        shapes: [],
      };

      if (showRatio) {
        layout.yaxis2 = {
          title: { text: `÷ ${shortLabel(fiducial)}` },
          gridcolor: grid,
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
          line: { color: text, width: 1, dash: "dot" },
        });
        host.classList.add("imf-stack");
      }

      window.Plotly.newPlot(host, traces, layout, { displayModeBar: false, responsive: true });
    })
    .catch(() => {
      host.replaceChildren();
      const note = document.getElementById("imf-plot-note");
      if (note) note.textContent = "Could not load IMF curves from the API.";
    });
}
