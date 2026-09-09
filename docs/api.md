# REST API

Everything the interface displays is served from `/api/v1`. Interactive
OpenAPI documentation lives at `/api/docs` (ReDoc at `/api/redoc`). The API is
deliberately parameter-rich — it is the foundation for a future generic query
builder.

## Endpoints at a glance

| endpoint | purpose |
|---|---|
| `GET /api/v1/health` | liveness |
| `GET /api/v1/meta` | releases, populations, age grid, dust laws, counts — everything selectors need |
| `GET /api/v1/populations` | list/filter populations (`release`, `imf`, `z_label`, `pop_type`, `alpha_label`) |
| `GET /api/v1/populations/{id}` | detail incl. provenance and per-age bolometric luminosities |
| `GET /api/v1/populations/{id}/sed` | one SED; `age_index`, `resolution=display|native`, `mass`, `dust_law`, `ebv`, `rv`, `format=json|csv` |
| `GET /api/v1/populations/{id}/sed_frames` | all 51 display-resolution SEDs for playback |
| `GET /api/v1/populations/{id}/timeseries` | per-age tables: `colours`, `ionizing`, `starmass`, `sn_rates`, `yields`, `mlratio` |
| `GET /api/v1/populations/{id}/hrd` | HRD occupation grids (uint8-quantized, base64) for animation |
| `GET /api/v1/filters` | bundled filter metadata |
| `GET /api/v1/filters/{name}/curve` | transmission curve |
| `GET /api/v1/photometry` | absolute AB magnitudes through bundled filters |
| `POST /api/v1/photometry/custom` | upload a transmission curve, get its AB magnitude |
| `GET /api/v1/models` | stellar-model search (`kind`, `z_label`, `m1_min`, `m1_max`, `curated`) |
| `GET /api/v1/models/{id}` | model detail + events |
| `GET /api/v1/models/{id}/track` | decimated, event-preserving track arrays + derived binary geometry |

## Examples

```sh
# what's loaded
curl -s localhost:8000/api/v1/meta | jq .releases

# a reddened SED as CSV at full resolution
curl -s "localhost:8000/api/v1/populations/1/sed?age_index=30&dust_law=smc&ebv=0.1&format=csv" -o sed.csv

# AB magnitudes
curl -s "localhost:8000/api/v1/photometry?population_id=1&age_index=30&filters=sdss.g,sdss.r" | jq .photometry

# custom filter upload
curl -s -F "file=@myfilter.txt" -F population_id=1 -F age_index=30 \
     localhost:8000/api/v1/photometry/custom | jq .result

# binary primaries between 10 and 20 Msun
curl -s "localhost:8000/api/v1/models?kind=primary&m1_min=10&m1_max=20" | jq length
```

## Payload conventions

- Numbers in JSON spectra are rounded to display precision (4 significant
  digits for flux); request **CSV** for full precision.
- AB magnitudes are absolute (source at 10 pc) and rounded to 4 decimals; each
  entry carries `lambda_eff` and a `coverage` fraction, and `ab_mag` is `null`
  when the filter misses the SED entirely.
- HRD grids are quantized to uint8 on a log scale for compactness:
  `value = 10^(lo + q/255·(hi−lo))` for `q > 0`, `q = 0` means empty; `lo`/`hi`
  are in the `scale` object.
- Track arrays are decimated to `max_points` (default 1500) while always
  preserving event timesteps; `mdot1` is a finite-difference rate (see the
  [science notes](science-notes.md#stellar-tracks-and-mass-loss-rates)).
