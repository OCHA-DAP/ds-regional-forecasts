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
3. `uv run python -m src.derive_data_viewer` — packs the two Zenodo NetCDFs into
   grayscale PNG **data tiles** (`docs/data/`, pixel = prob×200, 255 = nodata) +
   manifest + simplified country outline; these drive the site's Data viewer tab
   (canvas render, hover values, and client-side percentile-vs-own-record all read
   values straight off the tiles). Needs `data/tmp/African_States.geojson`
   (from blob raw/acmad/.../geojson/ — kept out of data/raw so upload_blob
   doesn't mirror it to a stray path).
4. `uv run python -m src.upload_blob` — mirrors `data/raw/` to blob at
   `ds-regional-forecasts/raw/...` and all derived `docs/` asset dirs to
   `processed/site-assets/...` (dev account, via ocha-stratus)

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

## Asset serving (since 2026-07-30)

The site serves ALL images and "original" downloads client-side from dev blob via the
team token issuer (`chd-ds-token-issuer`, app id `regional-forecasts`, tiers
`assets` -> `processed/site-assets`, `raw` -> `raw`). The repo carries only
`docs/index.html` + `docs/catalog.json`; `docs/{img,maps,thumbs,geo}` are gitignored
and mirrored to blob by `src/upload_blob.py`. If the issuer is unreachable the site
falls back to repo-relative paths (i.e. images break but the catalog still browses).
Local `data/raw/` is disposable — blob is authoritative; re-download with
`src/run_grab.py` (resumable). RCOF conference decks (~259 files) deliberately not
grabbed — only forum core products (statements/bulletins/maps).

## Data viewer tab (since 2026-07-31)

The only true multi-year gridded stacks in the archive are the two Zenodo NetCDFs
(consensus 2016–2024, objective 2017–2024; JJAS tercile probs, 0.1°, 510×170,
Sahel domain). Everything else machine-readable is either single-issue (LRF
shapefiles/GeoJSONs) or model debris. The viewer's percentile mode uses midrank
percentile of a cell's value within its own record, needing ≥4 finite years
(consensus zone coverage varies by year; 2024's domain is ~2× earlier years).
Tercile colors: PB oranges / PN neutral grays / PA blues, dominant-tercile chips
validated CVD-safe (`#d0842d/#6f6d67/#5190d3`); near-normal deliberately reads
neutral (domain convention: gray = "no signal"). ACMAD LRF polygon shapefiles
(275 .shp, 2018+ patchy) are the candidate next layer — vector overlay, not tiles.
