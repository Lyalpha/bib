# CHECKPOINT — paused mid-build (safe state)

**App boots fine** (`uv run python -c "from bib.app import create_app; create_app()"`).
Nothing is half-written; `src/bib/db/__init__.py` is an intentionally empty stub.
Plan file: `~/.cursor/plans/bib_alpha_spec_e18ce3c6.plan.md` (do NOT edit it).

## Todo status

| Todo | Status | Notes |
|---|---|---|
| scaffold-repo | **done** | committed in c732912: uv project (py3.13 pinned), FastAPI factory, branding via CSS vars, Typer CLI stubs, Containerfile, compose.yaml, entrypoint wait-loop, CI workflow, vendored plotly 4.1.0 / htmx 2.0.10 / alpine 3.17.2, base.html + main.css design system, placeholder page templates, README, LICENSE (MIT + CC BY-NC data note) |
| db-schema | **in-progress** | Only `src/bib/db/__init__.py` (empty) exists. Remaining: write `db/models.py` (full schema below), `db/session.py` (cached engine/sessionmaker from `bib.config.get_settings().database_url`), `db/bootstrap.py` (`init_database` = alembic upgrade head + load bundled filters if present, tolerate empty filters dir; `print_info` = table counts), alembic setup (`alembic.ini` at root, `src/bib/db/migrations/` env.py + script.py.mako), generate initial migration via autogenerate against dev DB, test `uv run bib init-db` |
| parsers-ingest | pending | |
| synthetic-demo | pending | |
| science-core | pending | |
| api-v1 | pending | |
| sed-page | pending | |
| hr-page | pending | |
| binary-viz | pending | NOTE: this todo exists in the plan frontmatter but was missing from the session todo list — add it (merge:true) when reached |
| content-pages | pending | |
| tests-docs | pending | |

## Exact next actions on resume

1. `podman start bib-pg` (dev Postgres, data persists), confirm `podman exec bib-pg pg_isready -U bib`.
2. Write `src/bib/db/models.py` per the locked schema below; `db/session.py`; `db/bootstrap.py`.
3. Set up alembic (script_location = `src/bib/db/migrations`; env.py reads URL from `bib.config`), autogenerate initial revision against the dev DB, run `uv run bib init-db`, sanity-check tables with psql.
4. Commit "DB schema + alembic + init-db", mark db-schema completed, move to parsers-ingest.
5. Regenerate the BPASS manual text reference if needed (see Environment).

## Locked design decisions (do not re-derive)

- **Stack**: FastAPI + SQLAlchemy 2 (sync, psycopg3) + Alembic + Postgres 16; Jinja2 + htmx + Alpine + vendored Plotly; uv; Typer CLI (`bib init-db|ingest|demo-seed|serve|info`). API-first: UI consumes `/api/v1`.
- **Schema** (tables): `release`, `wavelength_grid` (axis stored once, float64 bytea, populations reference it), `population` (release fk, imf label, z_label+z_value, pop_type sin/bin, alpha_label/alpha_value nullable — unique constraint with `postgresql_nulls_not_distinct=True`, provenance: source_file/sha256/ingested_at, `is_synthetic` bool, JSONB extra), `sed` (PK = population_id + **age_index smallint 0–50**, log_age float, full-res flux float32 bytea + downsampled `flux_ds` float32 bytea, optional log_lbol), per-age typed tables `colours` (21 Vega mag cols per manual), `ionizing`, `starmass`, `sn_rates`, `yields`, `mlratio` (all PK population_id+age_index), `stellar_model` (z, kind single/primary/secondary, m1_init, q_init, logp_init, mrem_init for sneplot_2, filename, curated flag/title/description, final_mass summary col, is_synthetic, provenance), `stellar_model_step` (PK model_id+step; manual cols 1–52 subset: age_yr, log_r1/t1/l1, m1, he/co/one core, surface X/Y/C/N/O/Ne, dm1w/dm2w/dm1a/dm2a/dm1r/dm2r raw code-unit rates, period_yr, log_sep, m2, log_r2/t2/l2), `model_event` (model fk, event_type, step, age_yr, label, note), `hrd_grid` (PK population_id+age_index+diagram TL/TG/TTG+h_class smallint 0/1/2; 100x100 float32 bytea; axes fixed: logT 0.1–10.0 step 0.1 rows, logL/G/TG −2.9–7.0 step 0.1 cols), `filter` (name unique, group, detector_type photon/energy, wavelength+transmission float64 bytea, lambda_eff/min/max, source, citation).
- **SED storage**: float32 bytea decoded with `numpy.frombuffer`; full res (100k pts @1Å for real data) used for photometry/downloads; precomputed downsampled (~2–5k pts, native 1Å below ~350Å then log bins) for plots. String enums as String + CheckConstraint (no PG enums).
- **Physical display of mass-loss**: compute dM/dt by finite difference of mass vs age at serve time; raw DM1W/DM1R... columns kept as flags/relative intensity (their code units are ambiguous — documented).
- **Events at ingest** (`ingest/events.py` heuristics, hand-verified per curated track): ZAMS=step0; TAMS=first he_core>0; core-He exhaustion=first co_core>0; giant branch=first logT<3.7 after TAMS; WR onset=first surface X<0.4 (hot); RLOF episodes=dm1r>0 spans; CEE=sharp log_sep drop during RLOF; thermal pulses=L oscillations with CO core; endpoint=last step. Model files have NO central abundances — say so in docs.
- **Golden subset** (`src/bib/ingest/golden.yaml`, to be written): v2.2.1 imf135_300 sin+bin all 13 Z (SEDs + all per-age products); imf_chab300 + imf100_300 bin at z002+z020; v2.3 imf135_300 bin 5 alphas at z002+z020; ~30 curated tracks at z020+z002 (singles 1,3,8,15,30,60 Msun + interacting binaries + sneplot_2 continuations, extracted from NEWBINMODS tars via tarfile member extraction, no full unpack); hrs isocontours imf135_300 bin z002+z020.
- **Synthetic demo**: generator in `ingest/synthetic.py`, own coarser log wavelength grid (~16k pts) exercising multi-grid path; toy blackbody-mix SEDs vs age; derived tables computed from those SEDs via our own photometry engine; toy tracks (singles 1/15/60 Msun + one RLOF binary + CEE-ish + secondary) run through the SAME event pipeline; `is_synthetic=True` everywhere → site-wide warn banner (already wired in `web/templating.py::has_synthetic_data`, 30s TTL cache, returns False if DB down).
- **Filters**: fetch real curves from SVO FPS once via script (`scripts/fetch_filters.py`, needs full_network), commit CSVs + `filters.yaml` metadata to `data/filters/`; sets: Johnson-Cousins UBVRI, SDSS ugriz, 2MASS JHKs, GALEX FUV/NUV, LSST ugrizy, HST WFC3/ACS wide, JWST NIRCam wide, Gaia G/BP/RP. AB mags at 10 pc; photon vs energy counting per filter metadata; Vega cross-check only against ingested BPASS colours tables.
- **Dust**: dust_extinction CCM89/F99/Calzetti00/Gordon03-SMC; clamp outside each law's valid range at boundary values, expose `applied_range` in API, shade extrapolated region in UI.
- **Playback/viz**: shared rAF clock `playback.js` drives HRD marker, density backdrop, SED frames, readout, `binaryviz.js` (Canvas 2D: true-scale orbit at real period (speed-factored), Eggleton Roche lobes computed server-side per step, blackbody→sRGB Teff colours, wind halo above mdot threshold, RLOF teardrop + stream particles, CEE envelope, single-star mode, compress-separation toggle). Interpolated frames are labelled visual-only; photometry always at true grid ages.

## Environment notes

- Dev Postgres: podman container **`bib-pg`**, host port **5433** (5432 is occupied on this machine by something else), user/db/password all `bib`. After reboot: `podman start bib-pg`. Data persists in the container (no named volume).
- `.env` at repo root (gitignored, intentionally NOT committed) sets `BIB_DATABASE_URL=postgresql+psycopg://bib:bib@localhost:5433/bib`.
- BPASS v2.2 manual text (column definitions etc.) was at `/tmp/bpass_manual.txt` — **lost on reboot**; regenerate:
  `curl -sL -o /tmp/bpass_manual.pdf "https://warwick.ac.uk/fac/sci/physics/research/astro/research/catalogues/bpass/v2p2/bpassv2.2_manual-arial.pdf" && pdftotext -layout /tmp/bpass_manual.pdf /tmp/bpass_manual.txt`
- `/tmp/bib-vendor` (npm tarballs) also lost on reboot — irrelevant, assets already vendored in `src/bib/web/static/vendor/`.

## Gotchas already hit

- Host port 5432 is occupied → dev container maps 5433.
- `uv sync` fails if `README.md` is missing (hatchling readme reference) — README exists now.
- Sandboxed shell hits user-namespace EINVAL errors on this machine → shell commands generally need elevated permissions ("all"); network fetches need full_network.
- The session todo list is missing the `binary-viz` item (plan frontmatter has it) — add via TodoWrite merge when starting that phase.
- Container compose file expects `data/filters/` to exist at build (Containerfile COPYs it) — currently empty; fine, but don't delete the directory. A `.gitkeep` is included so git preserves it.
