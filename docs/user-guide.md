# User guide

The in-app [tutorial](/tutorial) covers the astronomy background; this page is
the operator's view of the two explorers.

## SED Explorer (`/sed`)

1. **Select a population** — release, single/binary, IMF, metallicity, and (for
   v2.3 populations) the alpha-enhancement mix. Selectors cascade: only
   combinations that exist in the database are offered.
2. **Age** — slider over the 51-point grid, log(age/yr) = 6.0–11.0 in 0.1 dex
   steps. The **play** button animates through the grid; the speed slider sets
   decades of log-age per second; intermediate frames are interpolated in
   log-flux for smoothness and labelled as display-only.
3. **Mass** — rescales from the native normalisation of \(10^6\,M_\odot\)
   formed. Pure vertical shift.
4. **Dust** — law + E(B−V) (+ R_V where the law allows). Regions where the law
   is extrapolated (clamped at its boundary) are shaded in the plot.
5. **Keep this SED** — pins the current curve as a persistent trace with a
   management chip (recolour / remove). Pinned traces survive selector changes;
   use them to compare populations.
6. **Filters** — overlay bundled transmission curves; the photometry table
   lists absolute AB magnitudes (source at 10 pc) for the live SED and every
   pinned SED. **Upload custom filter** accepts two-column ASCII
   (wavelength [Å], transmission).
7. **Export** — PNG of the plot; CSV/JSON of the spectrum at full native
   resolution (display plots use a rebinned copy, downloads never do).

## HR Explorer (`/hr`)

1. **Pick a model** — filter by metallicity and kind (single / binary primary /
   secondary), then choose from the curated list; the description card explains
   why each track is interesting.
2. **Playback bar** — play/pause, rewind, scrub, speed. Playback advances
   through the model's own timesteps, so wall-clock speed adapts to how fast
   the star is evolving. The readout shows the true interpolated age.
3. **Readout panel** — age, mass, log T_eff, log L, radius, wind/strip mass-loss
   rate, He/CO core masses, surface X/Y/CNO, and for binaries: companion mass,
   orbital period, separation, Roche-lobe filling factor and interaction state.
4. **Event chips** — detected evolutionary milestones (ZAMS, core H/He
   exhaustion, giant branch, Wolf–Rayet stripping, Roche-lobe overflow episodes,
   common-envelope plunges, thermal pulses, endpoint). Click to jump the clock.
   These are heuristics — see the [science notes](science-notes.md#event-heuristics).
5. **Population backdrop** — optional HRD occupation-density heatmap of a
   population at the matching age, animated by the same clock.
6. **Binary visualizer** — the system drawn to a common physical scale beside
   the HRD:
     - colour ⇒ effective temperature (blackbody palette),
     - radius ⇒ stellar radius, separation ⇒ orbital separation
       (a scale bar shows R☉; orbit speed is compressed for display),
     - soft halo ⇒ strong wind (scales with the mass-loss rate),
     - teardrop + particle stream ⇒ Roche-lobe overflow onto the companion,
     - translucent envelope ⇒ common-envelope evolution,
     - "strict true scale" toggle: keep radii honest even when stars become
       sub-pixel; otherwise a minimum draw size is applied.

## Synthetic demo banner

While any synthetic population or model is present, every page carries a
warning banner. The demo data exercise every feature of the interface but are
**toy shapes, not science**. Ingest real BPASS products and remove the demo
rows to clear the banner.
