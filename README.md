# ds-regional-forecasts

Archive and gallery of African regional seasonal forecast products from
**ACMAD** (continental Long-Range Forecasts, ACCOF statements, RCOF outputs) and
**AGRHYMET** (PRESASS and PRESAGG forums), assembled so regional consensus
products can be viewed together and compared with global forecasts such as
ECMWF SEAS5.

**Gallery:** https://ocha-dap.github.io/ds-regional-forecasts/

## Contents

- `src/datasources/` — scrapers: ACMAD THREDDS catalog crawler, AGRHYMET
  WordPress media harvest, Wayback Machine rescues for pre-2023 PDFs, and the
  WAS-NextGen digitized PRESASS dataset from Zenodo
  ([10.5281/zenodo.18936657](https://doi.org/10.5281/zenodo.18936657), CC-BY 4.0)
- `src/run_grab.py` — download everything to `data/raw/` (resumable)
- `src/derive_assets.py` — classify files, render thumbnails, build the site catalog
- `src/upload_blob.py` — mirror the raw archive to Azure blob storage
- `docs/` — the static gallery site (GitHub Pages)

See `CLAUDE.md` for the full source survey and pipeline notes.

## Usage

```
uv sync
uv run python -m src.run_grab
uv run python -m src.derive_assets
```
