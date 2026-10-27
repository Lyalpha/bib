# REST API

Everything the interface displays is served from `/api/v1`. Interactive
OpenAPI documentation lives at `/api/docs` (ReDoc at `/api/redoc`). `/api` and
`/api/v1` redirect there. Set `BIB_EXPOSE_DOCS=false` to hide the UI (the JSON
API stays up). The API is deliberately parameter-rich. The in-browser
[Fetch data page](/request) (`GET /api/v1/export`) is the query builder:
IMF, metallicity and age in, a file with units and a query header out.

`population_id` is the integer `id` of a loaded simple stellar population
(one release × IMF × metallicity × binary/single × α-mix). List them with
`GET /api/v1/populations`. Ages are `log_age` = log₁₀(age/yr) on BPASS's
0.1 dex grid from 6.0 (1 Myr) to 11.0 (100 Gyr). SED fetches default to the
**native** 1 Å science grid.

The in-browser explorer uses an internal playback endpoint that is omitted
from the public schema.

## Endpoints at a glance

| endpoint | purpose |
|---|---|
| `GET /api/v1/health` | liveness (no database; `{"status":"ok","version":…}`) |
| `GET /api/v1/ready` | readiness (`SELECT 1`; 200 `{"status":"ok"}` or 503 `{"status":"unavailable"}`) |
| `GET /api/v1/meta` | releases, populations (`imf` plus parsed `imf_info`), unique `imfs` with ξ curves, age grid, dust laws (with validity windows and R_V ranges), IGM models |
| `GET /api/v1/populations` | list/filter populations (`release`, `imf`, `z_label`, `pop_type`, `alpha_label`); each row has `id` |
| `GET /api/v1/populations/{id}` | detail incl. provenance and per-age bolometric luminosities |
| `GET /api/v1/populations/{id}/sed` | one native-resolution SED; `log_age`, `mass`, `dust_law`, `ebv`, `rv`, `redshift`, `igm`, `format=json\|csv` |
| `GET /api/v1/igm_transmission` | mean IGM transmission on a population's display grid (`population_id`, `redshift`, `model`) |
| `GET /api/v1/populations/{id}/timeseries` | per-age tables: `colours`, `ionizing`, `starmass`, `sn_rates`, `yields`, `mlratio`, `star_counts` |
| `GET /api/v1/filters` | bundled filter metadata |
| `GET /api/v1/filters/{name}/curve` | transmission curve |
| `GET /api/v1/export/options` | products, unit systems and file formats for the Fetch data page |
| `GET /api/v1/export` | download by IMF / Z / age (`product`, `units`, `format=csv\|json\|ecsv\|ascii`) |
| `GET /api/v1/photometry` | AB magnitudes through bundled filters (`population_id`, `log_age`, optional `redshift`, `dust_law`, `ebv`, `rv`, `igm`) |
| `POST /api/v1/photometry/custom` | upload a transmission curve, get its AB magnitude |

## Examples

Replace `{id}` with an `id` from `GET /api/v1/populations` on the instance you
are querying. The Data & API page on a running server fills these in for you.
The examples use `localhost:8000` (a local checkout); against the public
instance substitute `https://bib.warwick.ac.uk`.

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

# apparent magnitudes at z=6 with Inoue+14 IGM attenuation; each row says what was applied
curl -s "localhost:8000/api/v1/photometry?population_id={id}&log_age=7.0&redshift=6&igm=inoue14&filters=jwst.f090w,jwst.f200w" \
  | jq '.photometry[] | {filter, ab_mag, dust_status, igm_status, attenuation_label}'

# custom filter upload (two-column wavelength [Å], transmission)
curl -s -F "file=@myfilter.txt" -F population_id={id} -F log_age=9.0 \
     localhost:8000/api/v1/photometry/custom | jq .result

# structured download (Fetch data page): solar-Z SED, no population_id
curl -s "localhost:8000/api/v1/export?product=sed&imf=imf135_300&z_label=z020&pop_type=bin&log_age=8.0&format=csv"

# ionizing photons at one age, every loaded Z, physical units (per 1 Msun)
curl -s "localhost:8000/api/v1/export?product=ionizing&imf=imf135_300&pop_type=bin&all_z=true&log_age=7.0&units=physical&format=json"
```

## Attenuation parameters

`sed`, `photometry`, `photometry/custom` and `export` share one pipeline,
applied in this order: `mass` → dust (rest frame) → `redshift` → IGM
(observer frame).

| parameter | values | notes |
|---|---|---|
| `dust_law` | `ccm89`, `f99`, `calzetti00`, `smc` | foreground screen; applied **only inside** the law's validity window, never extrapolated |
| `ebv` | 0–5 | E(B−V); 0 disables dust |
| `rv` | 2.0–6.0 | CCM89/F99 only (ignored for fixed-R_V laws); outside the range → 422 |
| `redshift` | 0–20 | 0 = rest frame / absolute magnitudes at 10 pc |
| `igm` | `none` (default), `inoue14`, `madau95` | mean IGM transmission for λ_obs < Lyα(1+z); no effect at z = 0 |

Responses carry `dust` (law, E(B−V), effective `rv`, `a_v`, `applied_range_a`
rest / `applied_range_obs_a` observed, `extrapolated: false`), `igm`
(`model`, `label`, `lyman_alpha_obs_a`) or `null`, and a `pipeline` list.

### Per-filter status vocabulary

Every photometry entry (API, custom upload, export columns) includes:

| field | values | meaning |
|---|---|---|
| `dust_status` | `none` · `applied` · `partial` · `not_applied` | no dust requested · passband (rest frame) fully inside the law's window · straddles an edge · entirely outside, so the requested extinction was not applied |
| `igm_status` | `none` · `applied` · `not_applied` | IGM irrelevant (z = 0 or passband redward of Lyα(1+z)) · model applied · passband reaches below Lyα(1+z) but `igm=none` |
| `attenuation_label` | `dust-extinguished` · `IGM-attenuated` · `dust-extinguished, IGM-attenuated` · `unattenuated` | human-readable summary (a `partial` dust window still counts as dust-extinguished) |

## Payload conventions

- Numbers in JSON spectra are rounded to display precision (4 significant
  digits for flux); request **CSV** for full precision.
- AB magnitudes are absolute (source at 10 pc) unless `redshift>0`, and
  rounded to 4 decimals; each entry carries `lambda_eff`, a `coverage`
  fraction and the status fields above, and `ab_mag` is `null` when the
  filter misses the SED entirely.
