# Ingesting BPASS data

bib never redistributes BPASS files: you download the release archives
yourself, and the ingest CLI parses them into PostgreSQL with provenance
(source filename + SHA-256) on every row.

End users of a running server do not need this page — the public Data & API
view is a catalogue of what is loaded, not an ingest tutorial. This guide is
for whoever (re)loads the database. The README is the short version.

## Getting the data

- [BPASS v2.2.1 release page](https://warwick.ac.uk/fac/sci/physics/research/astro/research/catalogues/bpass/v2p2/)
  — the primary release: population synthesis products and stellar models.
- [BPASS v2.3 release page](https://warwick.ac.uk/fac/sci/physics/research/astro/research/catalogues/bpass/bpassv2p3/)
  — alpha-enhanced spectral synthesis extension.
- [bpass.auckland.ac.nz](https://bpass.auckland.ac.nz) — project home.

The full releases are large (hundreds of GB when individual stellar models are
included). You only need the files named in your manifest. Official IMF
tarballs (`bpass_v2.2.1_imf*.tar.gz`) and stellar-model tarballs can stay
**packed** — ingest opens only the archives whose names contain an IMF the
manifest asked for, and extracts matching members into
`<source>/.bib-extract/`.

## This project's usual load: 100 M☉ SED grid

The pedagogical SSP Explorer load is **v2.2.1 only**, **100 M☉ IMF cap
only**, two IMFs, every metallicity, binary and single:

| IMF | Meaning |
|---|---|
| `imf135_100` | Fiducial BPASS broken power-law (upper slope −1.35), \(M_\mathrm{up}=100\,M_\odot\) |
| `imf_chab100` | Chabrier (2003) turnover at low mass, same \(100\,M_\odot\) cap |

Manifest: `src/bib/ingest/sed-100.yaml`. Required tarballs in `--source`:

```
bpass_v2.2.1_imf135_100.tar.gz
bpass_v2.2.1_imf_chab100.tar.gz
```

Leave the `*_300`, `imf100_*`, `imf170_*`, and `imf135all_*` archives in the
same folder if you have them — they are ignored.

```sh
uv run bib ingest \
  --source "/path/to/BPASS v2.2.1 full release" \
  --manifest src/bib/ingest/sed-100.yaml
```

That is 2 IMFs × 2 population types × 13 metallicities = 52 populations.
Spectra dominate the time (tens of minutes on a laptop + local Postgres).
Re-runs skip populations that already exist and fill any products the
manifest lists that are not yet in the database (for example `numbers`
after a schema upgrade). Add `--replace` to rebuild a population from scratch.

## v2.3 limited spectral release

Official v2.3 is a **spectral-synthesis** extension of v2.2.1, not a second
full population-synthesis grid. One IMF (`imf135_300` — no Chabrier, no
100 M☉ cap), five α/Fe packs, binary and single, every metallicity. Members
are named `product-{bin|sin}-imf135_300.{alpha}.{z}.dat` with no atmosphere
tag. Spectra match the v2.2.1 SED format (52 columns, 10⁵ rows, 1–100 000 Å).

Manifest: `src/bib/ingest/sed-v23.yaml`. Required tarballs in `--source`:

```
bpass_v2.3.a-02.tar.gz
bpass_v2.3.a+00.tar.gz
bpass_v2.3.a+02.tar.gz
bpass_v2.3.a+04.tar.gz
bpass_v2.3.a+06.tar.gz
```

bib loads spectra, colours, and ionizing. Lick indices and UV-index files in
the same archives are left on disk (no parsers). Missing packs are skipped
with a warning, so a single `a+00` tarball still loads that α grid.

```sh
uv run bib ingest \
  --source /path/to/BPASS_v2.3_release \
  --manifest src/bib/ingest/sed-v23.yaml
```

That is 1 IMF × 2 population types × 13 metallicities × 5 α grids = 130
populations. On the public VM, source `~/.config/bib/env` first so the CLI
uses `bib_app` rather than the default `bib` role. Restart gunicorn afterwards.

Afterward:

```sh
uv run bib info
```

The Data & API page lists every loaded population. Restart `bib serve` if it
was already running so the UI picks up new rows (or just reload — population
lists are read from the database per request).

## Other manifests

```sh
# curated "golden subset" (300 M☉ fiducial + extras + stellar models)
uv run bib ingest --source /path/to/bpass_downloads

# your own YAML
uv run bib ingest --source /path/to/bpass_downloads --manifest my_subset.yaml

# force re-ingestion of items that already exist
uv run bib ingest --source /path/to/bpass_downloads --replace
```

`--source` may contain files at any depth. Unpacked `.dat` / `.dat.gz` files
win over tarball members of the same name.

## The manifest

Copy `src/bib/ingest/sed-100.yaml`, `src/bib/ingest/sed-v23.yaml`, or
`src/bib/ingest/golden.yaml` and edit.
Structure (matches those files):

```yaml
releases:
  "2.2.1":
    name: Tuatara
    citation: "Eldridge, Stanway et al. (2017); Stanway & Eldridge (2018)"
    url: https://bpass.auckland.ac.nz

populations:
  - release: "2.2.1"
    imf: imf135_100
    pop_types: [bin, sin]
    metallicities: [zem5, zem4, z001, z002, z003, z004, z006, z008, z010, z014, z020, z030, z040]
    products: [spectra, colours, ionizing, starmass, supernova, yields, mlratio, numbers]

hrs:
  - release: "2.2.1"
    imf: imf135_100
    pop_types: [bin]
    metallicities: [z020]
    diagrams: [TL]

models:
  - z: z020
    kind: primary
    select: { m1: [15], q: [0.6], logp: [0.6] }
    curated: true
    title: "15 Msun close binary"
```

`golden.yaml` is the larger curated set: all 13 metallicities of
`imf135_300` (single and binary), a few 300 M☉ IMF variants, the v2.3 alpha
grids, HRD isocontours, and ~30 hand-picked stellar models.

## File formats understood

| product | filename pattern | shape check |
|---|---|---|
| SEDs | `spectra-<opt>-<imf>.<z>.dat[.gz]` | wavelength + 51 age columns |
| SEDs (v2.3) | `spectra-<opt>-<imf>.<alpha>.<z>.dat` | same grid; both Z/α orders accepted |
| colours | `colours-…` | 51 × ≥22 (first 22 columns kept; official files have 26) |
| ionizing | `ionizing-…` | 51 × 5 |
| star mass | `starmass-…` | 51 × 2 (sin) or × 3 (bin) |
| SN rates | `supernova-…` | 51 × 18 |
| yields | `yields-…` | 51 × 9 |
| M/L | `mlratio-…` | 51 × 3 (leading `log(age)` header is skipped) |
| star counts | `numbers-…` | 51 × 21 (10 spectral types × 2 luminosity bins) |
| HRD isocontours | `hrs-…` | 3 diagrams × 3 classes × 51 ages × 100 × 100 |
| stellar models | `sneplot-<z>-<M1>[-<q>-<logP>]`, `sneplot_2-…` | ≥ 16 columns, monotonic age |

Malformed files raise a `ParseError` naming the file and the violated
expectation; the age column of every per-age table is validated against the
canonical 6.0–11.0 grid. A missing or unreadable optional product is a
warning, not a failed ingest; a missing `spectra` file skips that population.

## After ingesting

- `uv run bib info` — row counts per table.
- The **Data & API** page shows what is loaded, with per-row demo badges.
- The demo banner disappears once no synthetic rows remain (demo rows can be
  deleted or simply never seeded in production).
