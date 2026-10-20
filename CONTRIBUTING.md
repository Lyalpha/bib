# Contributing to bib

bib is small and its value is that every number it serves can be traced to a
published prescription. Contributions are welcome under those terms.

## Set-up

```sh
uv sync
podman run -d --name bib-pg -e POSTGRES_USER=bib -e POSTGRES_PASSWORD=bib \
  -e POSTGRES_DB=bib_test -p 5433:5432 postgres:16-alpine   # or docker
uv run ruff check . && uv run ruff format --check .
uv run pytest                 # DB tests skip if PostgreSQL is unreachable
uv run mkdocs build --strict
```

For the real-data science checks: `uv run python scripts/fetch_bpass_subset.py`
then `uv run pytest -m realdata`.

## Rules for scientific changes

1. **Cite before you change numerics.** Any change to a formula, constant,
   coefficient table, integration scheme or default in `src/bib/science/`
   must cite a primary reference from [`docs/references.md`](docs/references.md)
   (add one if needed, with DOI) in the docstring or the PR description, and
   must carry a test that pins the new behaviour against a number from that
   reference or an independent implementation (synphot, `dust_extinction`,
   eazy-py, astropy).
2. **Validity windows are data, not comments.** If a dust law's fitted range
   or R_V range changes, update `DUST_LAWS` in `src/bib/science/dust.py`; if an
   IGM model is added or revised, update `IGM_MODELS` in
   `src/bib/science/igm.py`. The API, UI shading, per-filter status flags,
   export headers and `/api/v1/meta` all read from those tables. Then update
   `docs/science-notes.md` (the "Validity limits and non-goals" section) and
   `docs/api.md`.
3. **No silent extrapolation.** bib does not evaluate a prescription outside
   the range its authors fitted. Outside a window the quantity is left
   unmodified and the result is flagged (`dust_status`, `igm_status`). Keep
   it that way; prefer a flag to a tail.
4. **Pipeline order is fixed**: mass → dust (rest frame) → redshift → IGM
   (observer frame), implemented once in `src/bib/api/v1/pipeline.py`. New
   routes must go through `run_pipeline`, not reimplement the steps.
5. **Real-data checks are the regression suite.** If a change moves the
   measured residuals in `tests/realdata/`, update the table in
   `docs/science-notes.md` and explain why in the PR.
6. **Units.** SEDs are \(L_\odot\,\text{Å}^{-1}\) per \(10^6\,M_\odot\) formed
   (BPASS native); observed fluxes are erg s⁻¹ cm⁻² Å⁻¹; wavelengths are Å.
   Document any unit at the point it changes.

## Everything else

- Keep the public API backwards compatible within a minor version; add fields,
  do not rename them. Record user-visible changes in `CHANGELOG.md`.
- Parsers for BPASS files must cite the manual's column numbers
  (`docs/ingestion.md` lists the shapes).
- Do not commit BPASS data files, filter re-fetches without updating
  `data/filters/filters.yaml` provenance, or anything from `.env`.
- Templates and JavaScript carry no build step; keep them dependency free.
