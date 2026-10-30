# Changelog

All notable changes to bib are recorded here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); versions follow
[Semantic Versioning](https://semver.org/).

## [Unreleased]

### Fixed

- SSP explorer: the IGM band label no longer doubles its parentheses
  ("Inoue et al. (2014)" was wrapped in another pair).
- SSP explorer: a zoomed or panned SED view now follows the spectrum when
  the redshift or formed-mass slider moves, instead of being left behind.
- SSP explorer: Plotly's "home" button restored the ranges of the very first
  draw (z = 0), which was then recorded as a user zoom and could leave the
  SED permanently off-screen. Replaced by "Recentre axes on the current SED".
- SSP explorer: dust/IGM marks belong to each SED (ghost line without IGM,
  live-only fills over the attenuated region). Photometry *Correction
  applied* is pills only (Dust / IGM / None, amber when a requested
  correction could not be fully applied). Crossed photometry markers removed.
- SSP explorer: at most three vertical edge lines on the live SED (dust
  window + Lyα); hover labels restyled for contrast and no extra strip.
- SSP explorer: optional **sync redshifts** for pinned SEDs; passband
  colours paled so they don't clash with SED traces; photometry pill
  *No IGM* renamed *IGM ignored*.
- Tutorial IMF plot: same slope shares a colour, M_max=300 is dashed;
  legend is a single column to the right of the axes so it no longer
  sits on the curves.

## [1.0.0] — 2026-10-27

First public release, served at <https://bib.warwick.ac.uk>.

### Added
- SSP Explorer: native-resolution BPASS SEDs (v2.2.1 and the v2.3
  α-enhancement extension) with age playback, mass scaling, screen dust,
  redshift and synthetic AB photometry through bundled SVO filter curves or an
  uploaded curve.
- IGM attenuation as an explorer option and `igm` API parameter
  (`inoue14` default in the UI, `madau95` alternative; API default `none`),
  applied in the observer frame after redshifting. `GET
  /api/v1/populations/{id}/igm_transmission` returns the transmission on the
  display grid.
- Per-filter attenuation flags on every photometry payload and export:
  `dust_status` (none / applied / partial / not_applied), `igm_status`
  (none / applied / not_applied) and a human-readable `attenuation_label`
  ("dust-extinguished", "IGM-attenuated", both, or "unattenuated"). Flagged
  passbands are marked in the UI table, marker symbols and filter overlays.
- Fetch-data page and `GET /api/v1/export` for CSV / ECSV / ASCII / JSON
  tables with full provenance headers (pipeline order, effective R_V, dust
  validity window, IGM model).
- Real-data validation suite (`pytest -m realdata`) against a fetched BPASS
  v2.2.1 subset: synphot agreement < 1 mmag, Vega-converted magnitudes vs the
  published `colours` table, N_ion recomputed from the SED vs the `ionizing`
  table. Residuals recorded in `docs/science-notes.md`.
- Operator console, Sentry/GlitchTip hook, in-process rate limiting, privacy
  preserving visit counts, container and bare-metal deployment recipes.
- Release metadata: `CITATION.cff`, `.zenodo.json`, `docs/references.md`,
  `CONTRIBUTING.md`.
- Production deployment on `bib.warwick.ac.uk` (the VM hostname redirects to
  it; HSTS); staging stays on the previous host. Topology recorded in
  `docs/operations.md`.

### Changed
- Dust laws are **no longer extrapolated** outside their fitted wavelength
  window (CCM89 / F99 / Gordon03-SMC: 1000–33333 Å; Calzetti00:
  1200–21978 Å). Outside the window the SED is left unextinguished and the
  affected photometry is flagged; the explorer shades those regions.
- `R_V` outside 2.0–6.0 (CCM89 / F99) is rejected with HTTP 422 on every
  route instead of being silently clamped.
- Export responses are streamed row by row; `/api/v1/export` is rate limited
  like the other expensive routes.
- The operator session cookie stores a SHA-256 digest of the token rather than
  the token itself.
- Ingest persists the count of negative SED flux values clamped to zero as
  `n_negative_clamped` on each population.

### Removed
- The parked Star Explorer (HR diagrams, individual stellar models) and its
  `/star`, `/hr` routes. The code lives on the `star-explorer` branch; the
  database schema and migrations are unchanged.
