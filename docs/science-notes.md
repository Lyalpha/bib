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
- **Pipeline order**: every SED-derived quantity (plots, photometry, exports)
  is computed as *mass → dust (rest frame) → redshift → IGM (observer frame)*.
  The order is stated in each payload (`pipeline`) and file header.

## SED handling

Full-resolution SEDs (1 Å sampling, 1–100 000 Å for real data) are stored as
float32 and used for **all** photometry and downloads. Interactive plots use a
precomputed display copy: native sampling is kept wherever it is coarser than
the target logarithmic binning, log-spaced bins elsewhere (~2–4 k points).
Rebinning averages flux density within bins, so broadband shapes and
integrals are preserved; narrow spectral features are visually smoothed at
display resolution only. The explorer SED is clipped at rest-frame 50 Å —
BPASS atmospheres are not a useful model blueward of that — while files and
the API still return the far UV.

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

Outside a curve's published window **no extinction is applied** — the SED is
left unchanged there rather than extrapolated. The window is returned with
every response (`dust.applied_range_a`, rest frame; `applied_range_obs_a`,
observer frame), the explorer shades the unextinguished regions, and every
photometric magnitude carries a `dust_status` saying whether its passband was
fully inside (`applied`), straddling (`partial`) or entirely outside
(`not_applied`) the window. R_V for CCM89 and F99 is accepted over the range
the parameterisations were fitted, 2.0–6.0; other values are rejected (422).

Calzetti et al. (2000) published their curve as a starburst attenuation law.
bib still applies it as a screen, the same multiplication as the other three.

The CCM89/F99/SMC implementations come from the astropy-affiliated
`dust_extinction` package; Calzetti (2000) is implemented inline (validated
against the published polynomial in the test suite).

## IGM attenuation

For \(z>0\) an optional prescription multiplies the **observer-frame**
spectrum by the mean transmission \(\langle e^{-\tau_\mathrm{eff}}\rangle\) of
intervening neutral hydrogen bluewards of Lyα, \(\lambda_\mathrm{obs} <
1215.67(1+z)\) Å (Lyman-series blanketing plus the Lyman continuum):

| key | prescription | notes |
|---|---|---|
| `inoue14` | Inoue, Shimizu, Iwata & Tanaka (2014), eqs. 21–29, Table 2 | default in the UI; separates Lyα-forest and DLA components, 39 Lyman lines |
| `madau95` | Madau (1995), eq. 15 four-line fit + Lyman-continuum approximation | the classic prescription, for comparison with older work |

The implementation agrees with eazy-py's `Inoue14` to machine precision and
with Bagpipes' Lyman-series terms (Bagpipes rounds two Lyman-continuum
coefficients). It is a **sightline average**: no stochastic forest, no
damping wing from a neutral IGM at \(z \gtrsim 6\), no metal lines. The API
default is `igm=none`; the explorer default is on. Photometry rows carry
`igm_status`: `applied`, `not_applied` (passband reaches below Lyα(1+z) but
no model was requested — the magnitude is then brighter than any real
observation would be) or `none` (the IGM has no bearing on that passband or
\(z=0\)). The combined human-readable summary is `attenuation_label`:
*dust-extinguished*, *IGM-attenuated*, both, or *unattenuated*.

## Validity limits and non-goals

bib is a quick-look and teaching tool. Things it deliberately does **not** do:

- **Nebular emission.** SEDs are the pure stellar continua BPASS publishes;
  no nebular continuum or emission lines are added. Ionizing-photon rates and
  the Case B Hα luminosity are tabulated separately.
- **Dust emission or radiative transfer.** Extinction is a foreground screen;
  energy is removed, never re-emitted, and no star–dust geometry is modelled.
- **Extrapolated dust curves.** Nothing is applied outside a law's published
  window (see above). Photometry through passbands outside the window is
  flagged rather than guessed.
- **Stochastic IGM or damping wings.** IGM attenuation is a mean transmission.
- **Composite star-formation histories.** Every SED is a single instantaneous
  burst; summing pinned SSPs in the explorer is a visual aid only.
- **Interpolation between grid points.** Only true grid ages are
  photometered or exported (below).
- **Redshifts above 20** are rejected, and populations older than the
  Universe at a given \(z\) are flagged in the explorer but still served.

## Validation against real BPASS data

`tests/realdata/test_bpass_subset.py` (marker `realdata`) ingests one
fiducial v2.2.1 population — `imf135_300`, \(Z=0.002\), binaries, from the
files `scripts/fetch_bpass_subset.py` downloads — and compares what bib
serves with two independent references. The numbers below were measured
with bib 1.0.0 on that subset and are the values the tests guard.

**Photometry engine vs synphot.** The same stored SED through the same SVO
`sdss.g` curve, AB system: bib − synphot = **+0.07 mmag** at log age 7, 8,
9 and 10 (tolerance 1 mmag). The integral, the photon weighting and the
\(L_\odot\,\text{Å}^{-1}\) → \(f_\lambda\) at 10 pc chain agree.

**bib (Vega) vs BPASS's published `colours`.** bib's AB magnitudes are
converted to Vega with the CALSPEC `alpha_lyr_stis_011` spectrum and
compared with the BPASS table at log age 7, 8, 9, 10. This is *not*
like-for-like: BPASS used its own filter curves and Vega zero-points, so a
constant offset of a few hundredths is the expected SVO-vs-BPASS filter
difference. The diagnostic is the age-to-age scatter: an SED or unit error
would vary with the spectral shape; a zero-point difference does not.

| band (bib filter) | bib(Vega) − BPASS, mean [mag] | scatter over age [mag] | guarded |
|---|---|---|---|
| `sdss.g` | −0.009 | 0.010 | \|Δ\| < 0.05, σ < 0.02 |
| `sdss.i` | −0.015 | 0.001 | \|Δ\| < 0.05, σ < 0.02 |
| `sdss.z` | −0.011 | 0.0005 | \|Δ\| < 0.05, σ < 0.02 |
| `johnson.v` | −0.021 | 0.009 | \|Δ\| < 0.05, σ < 0.02 |
| `hst.f555w` | +0.001 | 0.0006 | \|Δ\| < 0.05, σ < 0.01 |
| `2mass.j` (BPASS J) | −0.047 | 0.001 | \|Δ\| < 0.08, σ < 0.01 |
| `sdss.u`, `sdss.r` | +0.022, −0.010 | 0.005, 0.002 | — |
| `johnson.b` | +0.001 | 0.005 | — |
| `hst.f435w`, `f606w`, `f814w` | +0.025, +0.003, −0.032 | ≤ 0.006 | — |
| `2mass.h`, `2mass.ks` (BPASS H, K) | −0.108, −0.050 | ≤ 0.003 | — |
| `johnson.u` | −0.063 | 0.051 | — |

The flat offsets in the NIR are the 2MASS-vs-Johnson system difference
(BPASS's J/H/K are generic Johnson passbands); `johnson.u` straddles the
Balmer jump, where the SVO generic U curve and BPASS's U differ most, and is
not a useful check of bib. The `sdss.ugriz` columns of the `colours` table
are confirmed to be on the **Vega** system (the +0.0 to −0.02 mag residuals
against a Vega-converted bib would be ≈0.1–0.5 mag if they were AB), as bib
labels them.

**Ionizing photon rate from the SED.** \(N_\mathrm{ion}=\int_{\lambda<912\,\text{Å}}
L_\lambda\,\lambda/(hc)\,d\lambda\) recomputed from the stored SED vs the
BPASS `ionizing` table: **−0.002 to −0.008 dex** at log age 6–9 (tolerance
0.03 dex). This is filter-independent and ties the served SED units to a
number BPASS publishes.

**Bolometric luminosity.** `log_lbol` stored at ingest is finite at all 51
ages and reproduces a trapezoid over the stored SED to < 10⁻⁴ dex.

## Interpolation policy

Animation frames between grid ages are **linear interpolations for visual
smoothness only** and are labelled as such in the UI. Photometry tables,
readouts at grid points, and all downloads are evaluated at true grid points.

## Synthetic demo data

`bib demo-seed` loads blackbody-mixture SEDs and derived product tables
computed through bib's own photometry engine. All rows carry
`is_synthetic = true`, every page shows a warning banner while any are
present, and none of it should ever be used for science.
