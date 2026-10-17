# Science notes

Conventions, assumptions and honest caveats. When in doubt, the BPASS
[v2.2 manual](https://warwick.ac.uk/fac/sci/physics/research/astro/research/catalogues/bpass/v2p2/bpassv2.2_manual-arial.pdf)
is authoritative.

## Units and conventions

- **SED flux**: \(L_\odot\,\text{Å}^{-1}\) for \(10^6\,M_\odot\) formed in an
  instantaneous burst, with \(L_\odot = 3.848\times10^{26}\,\mathrm{W}\)
  (manual convention). Wavelengths in Å.
- **Age grid**: \(\log_{10}(\mathrm{age/yr}) = 6.0 \ldots 11.0\) in 0.1 dex
  steps (51 bins). The explorer’s playback and property plots stop at 10.13,
  about the age of the Universe. Fetch data and the API still return every
  bin out to 11.0. Where a bin width matters (SN rates), bin \(n\) spans
  \(10^{(\log a - 0.05)}\)–\(10^{(\log a + 0.05)}\) yr.
- **Metallicity**: initial metal mass fraction Z; BPASS adopts
  \(Z_\odot = 0.020\). Labels: `zem5` … `z040`.
- **Magnitudes computed by bib**: AB system, *absolute* at D_L = 10 pc
  (or apparent at the chosen redshift):
  \[
  m_\mathrm{AB} = -2.5\,\log_{10}
  \frac{\int f_\lambda(\lambda)\,T(\lambda)\,\lambda\,d\lambda}
       {\int f_\lambda^{3631\,\mathrm{Jy}}(\lambda)\,T(\lambda)\,\lambda\,d\lambda}
  \]
  The extra factor of \(\lambda\) is the photon weight. It is applied to every
  filter, including Johnson–Cousins curves that the SVO tags as energy
  detectors. That is the convention in synphot and in CCD and infrared
  survey photometry. BPASS's own `colours` tables are Vega magnitudes for the classic
  bands — bib serves those tables verbatim and does not convert between
  systems.
- **Redshift**: observer-frame wavelengths are \(\lambda_\mathrm{obs}=\lambda_\mathrm{rest}(1+z)\).
  Observed \(f_\lambda\) is \(L_\lambda\,L_\odot\big/\big(4\pi D_L^2(1+z)\big)\) with
  \(D_L\) from flat ΛCDM (\(H_0=70\,\mathrm{km\,s^{-1}\,Mpc^{-1}}\), \(\Omega_m=0.3\)).
  The SED plot shows that flux in the same \(L_\odot\,\text{Å}^{-1}\) units as \(z=0\)
  by multiplying by \((10\,\mathrm{pc}/D_L)^2\), so raising \(z\) drops the curve by
  many orders of magnitude (the distance modulus). Apparent AB magnitudes use the
  same transform. \(z=0\) remains the 10 pc absolute frame.
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

## Dust extinction

Choosing a curve and \(E(B-V)\) extinguishes the plotted SED. Every wavelength
is multiplied by \(10^{-0.4 A_\lambda}\), with
\(A_\lambda = (A_\lambda/A_V)\,R_V\,E(B-V)\). That is a foreground screen on the
stellar spectrum. It is not attenuation through a mixture of stars and dust,
and the light removed is not reprocessed into the infrared.

| key | curve | R_V | valid range |
|---|---|---|---|
| `ccm89` | Cardelli, Clayton & Mathis (1989), Milky Way | free (default 3.1) | 0.1–3.33 µm |
| `f99` | Fitzpatrick (1999), Milky Way | free (default 3.1) | 0.1–3.33 µm |
| `calzetti00` | Calzetti et al. (2000), starburst curve, applied as a screen | fixed 4.05 | 0.12–2.2 µm |
| `smc` | Gordon et al. (2003) SMC bar average | fixed 2.74 | 0.1–3.33 µm |

Outside a curve's validated window the value is **clamped at its boundary**
(flat extrapolation). The applied window is returned by the API and the UI
shades extrapolated regions.

Calzetti et al. (2000) published their curve as a starburst attenuation law.
bib still applies it as a screen, the same multiplication as the other three.

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
