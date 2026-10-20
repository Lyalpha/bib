# References

The primary sources that ground bib. Contributors must check the relevant
entry before changing numerics and cite it when extending scope (see
`CONTRIBUTING.md`). Each entry says *why* it anchors bib and *how* it is used.

## Data

| Reference | Why it grounds bib | How it is used |
|---|---|---|
| Eldridge, Stanway et al. (2017), *BPASS v2.0*, PASA 34, e058 — [10.1017/pasa.2017.51](https://doi.org/10.1017/pasa.2017.51) | Population synthesis model, IMF definitions, age grid, stellar-only spectra | Required acknowledgement (landing page, `_acknowledgement.html`); release metadata in manifests |
| Stanway & Eldridge (2018), *Re-evaluating old stellar populations*, MNRAS 479, 75 — [10.1093/mnras/sty1353](https://doi.org/10.1093/mnras/sty1353) | v2.2 release paper; mass-loss and age-grid changes | Required acknowledgement |
| Byrne et al. (2022), *Dependence of stellar population spectra on α-element enhancement*, MNRAS 512, 5329 — [10.1093/mnras/stac807](https://doi.org/10.1093/mnras/stac807) | v2.3 α-enhanced spectral release served alongside v2.2.1 | Acknowledgement for v2.3 products; `alpha_label` semantics |
| BPASS v2.2 manual (Warwick release page; `bpassv2.2_manual`) | Column layouts in `src/bib/ingest/parsers.py`; \(L_\odot = 3.848\times10^{26}\) W; magnitude systems of the `colours` tables (Vega) | Any parser change must cite column numbers; `docs/ingestion.md` lists shapes |
| Stevance, Eldridge & Stanway (2020), *hoki*, JOSS 5, 1987 — [10.21105/joss.01987](https://doi.org/10.21105/joss.01987) | Recommended tool for scripted BPASS work; source of the real-data subset (`scripts/fetch_bpass_subset.py`) | Real-data regression fixture (`tests/realdata/`) |

## Photometry

| Reference | Why it grounds bib | How it is used |
|---|---|---|
| Oke & Gunn (1983), ApJ 266, 713 — [10.1086/160817](https://doi.org/10.1086/160817) | Definition of the AB system (3631 Jy zero point) | `AB_ZERO_FNU` in `src/bib/science/photometry.py` |
| Bessell & Murphy (2012), PASP 124, 140 — [10.1086/664083](https://doi.org/10.1086/664083) | Photon-counting synthetic photometry and zero points | The \(\lambda\)-weighted integral in `ab_magnitude`; changes need a test against synphot |
| Rodrigo, Solano & Bayo (2012); Rodrigo & Solano (2020), *SVO Filter Profile Service* — [10.5479/ADS/bib/2012ivoa.rept.1015R](https://doi.org/10.5479/ADS/bib/2012ivoa.rept.1015R) | Provenance of every curve in `data/filters/*.csv` (`svo_id` recorded) | Re-fetch with `scripts/fetch_filters.py` and record the date in `filters.yaml` |
| Bohlin (2014), AJ 147, 127 — [10.1088/0004-6256/147/6/127](https://doi.org/10.1088/0004-6256/147/6/127) | CALSPEC Vega (`alpha_lyr_stis_011`) used to convert bib's AB magnitudes to Vega in the real-data checks | `tests/realdata/test_bpass_subset.py` |

## Dust

| Reference | Why it grounds bib | How it is used |
|---|---|---|
| Cardelli, Clayton & Mathis (1989), ApJ 345, 245 — [10.1086/167900](https://doi.org/10.1086/167900) | CCM89 law; valid 1000–33333 Å, \(R_V\) 2.0–6.0 | `DUST_LAWS["ccm89"]` window and `rv_range` |
| Fitzpatrick (1999), PASP 111, 63 — [10.1086/316293](https://doi.org/10.1086/316293) | F99 law; same window, free \(R_V\) | `DUST_LAWS["f99"]` |
| Calzetti et al. (2000), ApJ 533, 682 — [10.1086/308692](https://doi.org/10.1086/308692) | Starburst attenuation curve; valid 1200–21978 Å, \(R_V=4.05\) | `DUST_LAWS["calzetti00"]` |
| Gordon et al. (2003), ApJ 594, 279 — [10.1086/376774](https://doi.org/10.1086/376774) | SMC bar average, \(R_V=2.74\) | `DUST_LAWS["smc"]` |
| Gordon (2024), *dust_extinction*, JOSS 9, 7023 — [10.21105/joss.07023](https://doi.org/10.21105/joss.07023) | Reference implementation and the windows bib enforces | Dependency; bib never evaluates a law outside its `x_range` |

## Redshift and IGM

| Reference | Why it grounds bib | How it is used |
|---|---|---|
| Hogg (1999), *Distance measures in cosmology*, [astro-ph/9905116](https://arxiv.org/abs/astro-ph/9905116) | \(D_L\), the \((1+z)\) bandwidth factor | `src/bib/science/redshift.py`; redshift tests |
| Hogg et al. (2002), *The K correction*, [astro-ph/0210394](https://arxiv.org/abs/astro-ph/0210394) | Observer-frame photometry semantics (K-correction included by construction) | Photometry at \(z>0\) |
| Astropy Collaboration (2022), ApJ 935, 167 — [10.3847/1538-4357/ac7c74](https://doi.org/10.3847/1538-4357/ac7c74) | Cosmology implementation (flat ΛCDM, \(H_0=70\), \(\Omega_m=0.3\)) | Dependency |
| Inoue, Shimizu, Iwata & Tanaka (2014), MNRAS 442, 1805 — [10.1093/mnras/stu936](https://doi.org/10.1093/mnras/stu936) | Analytic IGM mean transmission: Lyman series (LAF + DLA, eqs 21–24) and Lyman continuum (eqs 25–29), Table 2 coefficients | `IGM_MODELS["inoue14"]` in `src/bib/science/igm.py`; validated against eazy-py |
| Madau (1995), ApJ 441, 18 — [10.1086/175332](https://doi.org/10.1086/175332) | Classic four-line + Lyman-continuum IGM prescription | `IGM_MODELS["madau95"]` |

## IMF (display only)

| Reference | Why it grounds bib | How it is used |
|---|---|---|
| Kroupa (2001), MNRAS 322, 231 — [10.1046/j.1365-8711.2001.04022.x](https://doi.org/10.1046/j.1365-8711.2001.04022.x) | Broken power-law IMFs shown on the Data page | `src/bib/science/imf.py` |
| Chabrier (2003), PASP 115, 763 — [10.1086/376392](https://doi.org/10.1086/376392) | `imf_chab300` curve | `src/bib/science/imf.py` |
