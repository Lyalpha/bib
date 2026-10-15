import { apiGet } from "/static/js/api.js";
import { PLOT_GRID, logAxisTicks } from "/static/js/plot-axis.js";

const css = (name) =>
  getComputedStyle(document.documentElement).getPropertyValue(name).trim();

const COLORS = [
  () => css("--brand-primary") || "#5aa9ff",
  () => css("--brand-accent") || "#ffb454",
  () => css("--brand-accent-2") || "#7ee0a3",
  () => css("--brand-warn") || "#ff7b72",
  () => css("--brand-muted") || "#9aa7c7",
];

const host = document.getElementById("imf-plot");
if (host) {
  apiGet("/meta")
    .then((meta) => {
      const imfs = (meta.imfs || []).filter((imf) => imf.mass && imf.dndm);
      const note = document.getElementById("imf-plot-note");
      if (!imfs.length) {
        host.replaceChildren();
        if (note) note.textContent = "No populations are loaded, so there is nothing to plot.";
        return;
      }
      const text = css("--brand-text") || "#e8ecf8";
      const grid = PLOT_GRID;
      const traces = imfs.map((imf, i) => ({
        type: "scatter",
        mode: "lines",
        name: imf.label,
        x: imf.mass,
        y: imf.dndm,
        line: {
          color: COLORS[i % COLORS.length](),
          width: 2.4,
          dash: imf.form === "chabrier" ? "dash" : "solid",
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
          margin: { l: 58, r: 16, t: 8, b: 48 },
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
          legend: { orientation: "h", y: 1.12, font: { size: 11 } },
          hovermode: "closest",
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
