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
      const text = css("--brand-text") || "#e8ecf8";
      const grid = PLOT_GRID;
      const traces = imfs.map((imf) => ({
        type: "scatter",
        mode: "lines",
        name: shortLabel(imf),
        x: imf.mass,
        y: imf.dndm,
        line: {
          color: COLORS[families.indexOf(familyKey(imf)) % COLORS.length](),
          width: 2.4,
          // Same slope + shape share a colour; M_max=300 is dashed so it doesn't
          // sit on top of the M_max=100 curve over the shared mass range.
          dash: Number(imf.m_max) >= 300 ? "dash" : "solid",
        },
        hovertemplate: `${imf.label}<br>M = %{x:.2f} M☉<br>dN/dM = %{y:.3e}<extra></extra>`,
      }));
      window.Plotly.newPlot(
        host,
        traces,
        {
          paper_bgcolor: "rgba(0,0,0,0)",
          plot_bgcolor: "rgba(0,0,0,0)",
          font: { color: text, size: 12 },
          margin: { l: 58, r: 168, t: 8, b: 48 },
          xaxis: {
            type: "log",
            title: { text: "M / M☉" },
            gridcolor: grid,
            zeroline: false,
            ...logAxisTicks(3),
          },
          yaxis: {
            type: "log",
            title: { text: "dN/dM  (stars per M☉, matched at 1 M☉)" },
            gridcolor: grid,
            zeroline: false,
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
        },
        { displayModeBar: false, responsive: true },
      );
    })
    .catch(() => {
      host.replaceChildren();
      const note = document.getElementById("imf-plot-note");
      if (note) note.textContent = "Could not load IMF curves from the API.";
    });
}
