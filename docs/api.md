# REST API

Everything the interface displays is served from `/api/v1`. Interactive
OpenAPI documentation lives at `/api/docs` (ReDoc at `/api/redoc`). `/api` and
`/api/v1` redirect there. Set `BIB_EXPOSE_DOCS=false` to hide the UI (the JSON
API stays up). The API is deliberately parameter-rich. The in-browser
[request-data page](/request) (`GET /api/v1/export`) is the query builder:
IMF, metallicity and age in, a file with units and a query header out.

`population_id` is the integer `id` of a loaded simple stellar population
(one release × IMF × metallicity × binary/single × α-mix). List them with
`GET /api/v1/populations`. Ages are `log_age` = log₁₀(age/yr) on BPASS's
0.1 dex grid from 6.0 (1 Myr) to 11.0 (100 Gyr). SED fetches default to the
**native** 1 Å science grid.

The in-browser explorer uses a private playback endpoint that is not part of
the public schema.

## Endpoints at a glance

| endpoint | purpose |
|---|---|
| `GET /api/v1/health` | liveness (no database; `{"status":"ok","version":…}`) |
| `GET /api/v1/ready` | readiness (`SELECT 1`; 200 `{"status":"ok"}` or 503 `{"status":"unavailable"}`) |
| `GET /api/v1/meta` | releases, populations (`imf` plus parsed `imf_info`), unique `imfs` with ξ curves, age grid, dust laws |
| `GET /api/v1/populations` | list/filter populations (`release`, `imf`, `z_label`, `pop_type`, `alpha_label`); each row has `id` |
| `GET /api/v1/populations/{id}` | detail incl. provenance and per-age bolometric luminosities |
| `GET /api/v1/populations/{id}/sed` | one native-resolution SED; `log_age`, `mass`, `dust_law`, `ebv`, `rv`, `format=json\|csv` |
| `GET /api/v1/populations/{id}/timeseries` | per-age tables: `colours`, `ionizing`, `starmass`, `sn_rates`, `yields`, `mlratio`, `star_counts` |
| `GET /api/v1/populations/{id}/hrd` | HRD occupation grids (uint8-quantized, base64) for animation |
| `GET /api/v1/filters` | bundled filter metadata |
| `GET /api/v1/filters/{name}/curve` | transmission curve |
| `GET /api/v1/export/options` | products, unit systems and file formats for the request-data page |
| `GET /api/v1/export` | download by IMF / Z / age (`product`, `units`, `format=csv\|json\|ecsv\|ascii`) |
| `GET /api/v1/photometry` | absolute AB magnitudes through bundled filters (`population_id`, `log_age`) |
| `POST /api/v1/photometry/custom` | upload a transmission curve, get its AB magnitude |

## Examples

Replace `{id}` with an `id` from `GET /api/v1/populations` on the instance you
are querying. The Data & API page on a running server fills these in for you.

```sh
# liveness / readiness (ready is 503 when PostgreSQL is down)
curl -s localhost:8000/api/v1/health
curl -s localhost:8000/api/v1/ready

# catalogue of loaded populations (id, release, IMF, Z, binary/single, products)
curl -s localhost:8000/api/v1/populations | jq '.[0]'

# native-resolution rest-frame SED at log10(age/yr)=9.0 (1 Gyr):
# wavelength [Å], flux [Lsun/Å] at 1e6 Msun formed
curl -s "localhost:8000/api/v1/populations/{id}/sed?log_age=9.0"

# same SED as CSV (full precision, two columns)
curl -s "localhost:8000/api/v1/populations/{id}/sed?log_age=9.0&format=csv" -o sed.csv

# a reddened native SED as CSV
curl -s "localhost:8000/api/v1/populations/{id}/sed?log_age=9.0&dust_law=smc&ebv=0.1&format=csv" -o sed.csv

# absolute AB magnitudes through SDSS g and r for that SED (source at 10 pc)
curl -s "localhost:8000/api/v1/photometry?population_id={id}&log_age=9.0&filters=sdss.g,sdss.r" | jq .photometry

# custom filter upload (two-column wavelength [Å], transmission)
curl -s -F "file=@myfilter.txt" -F population_id={id} -F log_age=9.0 \
     localhost:8000/api/v1/photometry/custom | jq .result

# structured download (Fetch data page): solar-Z SED, no population_id
curl -s "localhost:8000/api/v1/export?product=sed&imf=imf135_300&z_label=z020&pop_type=bin&log_age=8.0&format=csv"

# ionizing photons at one age, every loaded Z, physical units (per 1 Msun)
curl -s "localhost:8000/api/v1/export?product=ionizing&imf=imf135_300&pop_type=bin&all_z=true&log_age=7.0&units=physical&format=json"
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
