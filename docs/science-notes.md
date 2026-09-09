# Science notes

Conventions, assumptions and honest caveats. When in doubt, the BPASS
[v2.2 manual](https://warwick.ac.uk/fac/sci/physics/research/astro/research/catalogues/bpass/v2p2/bpassv2.2_manual-arial.pdf)
is authoritative.

## Units and conventions

- **SED flux**: \(L_\odot\,\text{Å}^{-1}\) for \(10^6\,M_\odot\) formed in an
  instantaneous burst, with \(L_\odot = 3.848\times10^{26}\,\mathrm{W}\)
  (manual convention). Wavelengths in Å.
- **Age grid**: \(\log_{10}(\mathrm{age/yr}) = 6.0 \ldots 11.0\) in 0.1 dex
  steps (51 bins). Where a bin width matters (SN rates), bin \(n\) spans
  \(10^{(\log a - 0.05)}\)–\(10^{(\log a + 0.05)}\) yr.
- **Metallicity**: initial metal mass fraction Z; BPASS adopts
  \(Z_\odot = 0.020\). Labels: `zem5` … `z040`.
- **Magnitudes computed by bib**: AB system, *absolute* (source at 10 pc):
  \[
  m_\mathrm{AB} = -2.5\,\log_{10}
  \frac{\int f_\lambda(\lambda)\,T(\lambda)\,\lambda\,d\lambda}
       {\int f_\lambda^{3631\,\mathrm{Jy}}(\lambda)\,T(\lambda)\,\lambda\,d\lambda}
  \]
  for photon-counting detectors; the \(\lambda\) weight is dropped for
  energy-counting detectors (per filter metadata from the SVO Filter Profile
  Service). BPASS's own `colours` tables are Vega magnitudes for the classic
  bands — bib serves those tables verbatim and does not convert between
  systems.
- **Filter coverage**: when an SED only partially covers a filter's support,
  the AB magnitude is still computed on the overlap and the response includes
  a `coverage` fraction; a filter with no overlap returns `null`.

## SED handling

Full-resolution SEDs (1 Å sampling, 1–100 000 Å for real data) are stored as
float32 and used for **all** photometry and downloads. Interactive plots use a
precomputed display copy: native sampling is kept wherever it is coarser than
the target logarithmic binning, log-spaced bins elsewhere (~2–4 k points).
Rebinning averages flux density within bins, so broadband shapes and
integrals are preserved; narrow spectral features are visually smoothed at
display resolution only.

## Dust

Four laws, applied as \(F' = F\,10^{-0.4\,A_\lambda}\) with
\(A_\lambda = (A_\lambda/A_V)\,R_V\,E(B-V)\):

| key | law | R_V | valid range |
|---|---|---|---|
| `ccm89` | Cardelli, Clayton & Mathis (1989), MW extinction | free (default 3.1) | 0.1–3.33 µm |
| `f99` | Fitzpatrick (1999), MW extinction | free (default 3.1) | 0.1–3.33 µm |
| `calzetti00` | Calzetti et al. (2000), starburst **attenuation** | fixed 4.05 | 0.12–2.2 µm |
| `smc` | Gordon et al. (2003) SMC bar average | fixed 2.74 | 0.1–3.33 µm |

Outside a law's validated window the curve is **clamped at its boundary value**
(flat extrapolation). The applied window is returned by the API and the UI
shades extrapolated regions. Extinction (line-of-sight) and attenuation
(geometry-averaged) are physically different quantities — the Calzetti law is
the only attenuation law in the set and is the usual choice for star-forming
galaxies as a whole.

The CCM89/F99/SMC implementations come from the astropy-affiliated
`dust_extinction` package; Calzetti (2000) is implemented inline (validated
against the published polynomial in the test suite).

## Stellar tracks and mass-loss rates

`sneplot` model files tabulate masses, radii, temperatures, luminosities, core
masses, surface abundances and binary geometry per timestep. Two caveats:

- The raw mass-transfer/wind rate columns (`DM1W`, `DM1R`, …) are in internal
  code units of ambiguous normalisation; bib uses them **only as activity
  flags** (e.g. "RLOF is happening"). The mass-loss rate displayed in the UI
  (`mdot1`) is derived by finite differences of mass against age, which is
  robust but smooths sub-timestep bursts.
- Roche-lobe radii are computed with the Eggleton (1983) approximation from
  the tabulated separation and masses.

## Event heuristics

BPASS model files carry **no central abundances**, so evolutionary phases are
inferred:

| event | criterion |
|---|---|
| ZAMS | first timestep |
| Core H exhaustion (TAMS) | He-core mass rises above zero |
| Core He exhaustion | CO-core mass rises above zero |
| Carbon burning | ONe-core mass rises above zero |
| Giant branch | first \(\log T_\mathrm{eff} < 3.70\) after TAMS |
| Wolf–Rayet | surface X < 0.4 while \(\log T_\mathrm{eff} > 4.45\) (manual criterion) |
| RLOF start/end | spans where the DM1R flag is positive |
| Common envelope | \(\log a\) drops by > 0.15 in one step during RLOF |
| Thermal pulses | ≥ 3 luminosity oscillation cycles on the cool CO-core branch |
| Endpoint | last timestep, with a core-mass-based hint (SN candidate / WD progenitor) |

These guide the eye; they are not a substitute for reading the models. Each
curated golden-subset track is checked by hand.

## Interpolation policy

Animation frames between grid ages or timesteps are **linear interpolations
for visual smoothness only** and are labelled as such in the UI. Photometry
tables, readouts at grid points, and all downloads are evaluated at true grid
points. Track interpolation is linear in the model's own (irregular)
timesteps.

## Synthetic demo data

`bib demo-seed` loads blackbody-mixture SEDs, derived product tables computed
through bib's own photometry engine, toy HRD grids and hand-built toy tracks
designed to trigger every event heuristic. All rows carry
`is_synthetic = true`, every page shows a warning banner while any are
present, and none of it should ever be used for science.
