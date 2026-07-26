# ds-regional-forecasts

Archive + gallery of African regional seasonal forecast products (ACMAD, AGRHYMET),
built to show what regional consensus products exist alongside global forecasts
(ECMWF SEAS5). Output: GitHub Pages gallery from `docs/`.

## Pipeline

1. `uv run python -m src.run_grab` — downloads all sources to `data/raw/` (resumable;
   skips existing files) and writes `data/catalog_raw.json`
2. `uv run python -m src.derive_assets` — classifies files, renders PDF page-1
   thumbnails to `docs/thumbs/`, resizes map images to `docs/img/`, copies small
   GeoJSONs to `docs/geo/`, writes `docs/catalog.json`
3. `uv run python -m src.upload_blob` — mirrors `data/raw/` to blob at
   `ds-regional-forecasts/raw/...` (dev account, via ocha-stratus)

`data/` is gitignored; the site carries only derived assets.

## Sources (surveyed 2026-07-25)

- **ACMAD THREDDS** (`sgbd.acmad.org`): the master archive. TLS cert on 443 is
  expired — use `http://sgbd.acmad.org:8080`. Enumerate via per-folder `catalog.xml`;
  NEVER construct filenames (hand-authored: spaces, typos "Breif"/"Verifcation",
  inconsistent month codes, `%` chars). Trees in `src/constants.py`. LRF forecast
  polygons exist as shapefiles (2018+, patchy) and 2022 GeoJSONs.
- **AGRHYMET** (`agrhymet.cilss.int`): PDFs only, enumerated via open WP REST API
  (`/wp-json/wp/v2/media?search=...`). Site has been through 3+ redesigns; each broke
  all old PDF URLs — expect current URLs to rot too (raw archive in blob is the hedge).
- **Wayback**: hardcoded verified list of pre-2023 PRESASS/PRESAGG PDFs (dead on the
  live sites) in `src/datasources/wayback.py`.
- **Zenodo 10.5281/zenodo.18936657**: WAS-NextGen digitized PRESASS consensus
  forecasts 2016–2024 as NetCDF (CC-BY 4.0, by AGRHYMET's own Houngnibo et al.).
  The only public machine-readable historical record. The 1.3 GB obs zip is
  deliberately excluded.

## Context worth keeping

- RCOF = Regional Climate Outlook Forum: consensus tercile maps negotiated at
  pre-season workshops — the product is literally a map image, which is why raw data
  mostly doesn't exist. PRESASS (Sahel JJAS, forum late April), PRESAGG (Gulf of
  Guinea MAMJ, forum late Feb), both AGRHYMET-led with ACMAD. ACMAD also issues a
  monthly continental Long-Range Forecast and hosts other forums' outputs
  (PRESAC, MEDCOF, SWIOCOF).
- West Africa is switching from consensus maps to the objective **WASS2S** system —
  future forecasts should increasingly be reproducible NetCDF.
- ICPAC (IGAD/East Africa, GHACOF) is the planned next addition: their geoportal
  already serves outlook polygons as shapefiles back to 1998
  (`geoportal.icpac.net`, GeoNode API).
- Longer digitized records (PRESAO/PRESASS 1998–2024) exist but are unpublished:
  Pirret et al. 2020 (UK Met Office), Rauch et al. 2025 (Univ. Augsburg) — author
  contact required.
