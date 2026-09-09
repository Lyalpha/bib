# Ingesting BPASS data

bib never redistributes BPASS files: you download the release archives
yourself, and the ingest CLI parses them into PostgreSQL with provenance
(source filename + SHA-256) on every row.

## Getting the data

- [BPASS v2.2.1 release page](https://warwick.ac.uk/fac/sci/physics/research/astro/research/catalogues/bpass/v2p2/)
  — the primary release: population synthesis products and stellar models.
- [BPASS v2.3 release page](https://warwick.ac.uk/fac/sci/physics/research/astro/research/catalogues/bpass/bpassv2p3/)
  — alpha-enhanced spectral synthesis extension.
- [bpass.auckland.ac.nz](https://bpass.auckland.ac.nz) — project home.

The full releases are large (hundreds of GB when individual stellar models are
included). You only need the files named in your manifest; tarballs of stellar
models can stay **packed** — curated models are extracted member-by-member.

## Running an ingest

```sh
# everything the bundled golden manifest asks for
uv run bib ingest --source /path/to/bpass_downloads

# with your own manifest
uv run bib ingest --source /path/to/bpass_downloads --manifest my_subset.yaml

# force re-ingestion of items that already exist
uv run bib ingest --source /path/to/bpass_downloads --replace
```

`--source` may contain the files at any depth; they are located by name. Files
may be gzipped. Re-runs are idempotent: existing populations/models are
skipped unless `--replace` is given.

## The manifest

The bundled `src/bib/ingest/golden.yaml` defines the curated "golden subset":
all 13 metallicities of `imf135_300` (single and binary), IMF variants at two
metallicities, the v2.3 alpha grids, HRD isocontour files, and ~30 hand-picked
stellar models with titles and descriptions for the HR Explorer. Copy it and
edit to taste. Structure:

```yaml
releases:
  - version: "2.2.1"
    name: BPASS v2.2.1
    citation: "Stanway & Eldridge (2018)"
    url: https://...

populations:
  - release: "2.2.1"
    imf: imf135_300
    z: z020
    pop_type: bin          # sin | bin
    products: [spectra, colours, ionizing, starmass, supernova, yields, mlratio]

hrd_grids:
  - release: "2.2.1"
    imf: imf135_300
    z: [z020, z002]
    pop_type: bin

stellar_models:
  - z: z020
    kind: primary          # single | primary | secondary
    m1: 15
    q: 0.6
    logp: 1.0
    title: "15+9 Msun close binary"
    description: "Roche-lobe overflow strips the primary to a helium star."
```

## File formats understood

| product | filename pattern | shape check |
|---|---|---|
| SEDs | `spectra-<opt>-<imf>.<z>.dat[.gz]` | wavelength + 51 age columns |
| colours | `colours-…` | 51 × 22 |
| ionizing | `ionizing-…` | 51 × 5 |
| star mass | `starmass-…` | 51 × 2 (sin) or × 3 (bin) |
| SN rates | `supernova-…` | 51 × 18 |
| yields | `yields-…` | 51 × 9 |
| M/L | `mlratio-…` | 51 × 3 |
| HRD isocontours | `hrs-…` | 3 diagrams × 3 classes × 51 ages × 100 × 100 |
| stellar models | `sneplot-<z>-<M1>[-<q>-<logP>]`, `sneplot_2-…` | ≥ 16 columns, monotonic age |

Malformed files raise a `ParseError` naming the file and the violated
expectation; the age column of every per-age table is validated against the
canonical 6.0–11.0 grid.

## After ingesting

- `uv run bib info` — row counts per table.
- The **Data & API** page shows what is loaded, with per-row demo badges.
- The demo banner disappears once no synthetic rows remain (demo rows can be
  deleted or simply never seeded in production).
