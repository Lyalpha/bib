/** Shared Plotly axis styling: quiet decade grids, no 2–9 mesh. */

export const PLOT_GRID = "rgba(154, 167, 199, 0.16)";

/** Space labelled decades so 10ⁿ ticks do not collide on a short axis. */
export function logTickStep(spanDecades) {
  const span = Math.abs(Number(spanDecades)) || 0;
  if (span > 18) return 4;
  if (span > 12) return 3;
  if (span > 6.5) return 2;
  return 1;
}

export function logAxisTicks(spanDecades) {
  return {
    tickmode: "linear",
    dtick: logTickStep(spanDecades),
    tick0: 0,
    gridwidth: 1,
    tickfont: { size: 11 },
    minor: { showgrid: false, ticks: "" },
  };
}
