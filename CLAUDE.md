# ds-regional-forecasts

Archive + gallery of African regional seasonal forecast products (ACMAD, AGRHYMET,
SADC CSC), built to show what regional consensus products exist alongside global
forecasts (ECMWF SEAS5). Output: GitHub Pages gallery from `docs/`.

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

## SADC / SARCOF (surveyed 2026-08-24)

- **www.sadc.int** (Secretariat, Drupal): document library at
  `/documents?title=<term>` (title search only) holds SARCOF statements; more
  hide behind `/latest-news` nodes and hand-verified `/sites/default/files/`
  URLs (`EXTRA_LIVE` in `sadc_web.py`).
- **csc.sadc.int** (Climate Services Centre, Gaborone): HTTPS times out — HTTP
  only, same disease as ACMAD. Drupal-10 relaunch ~2025 killed all old Joomla
  `/images/...` URLs; only SARCOF-30+ live there now. Its
  `/climate-prediction` page is the gem: a custom module embeds the complete
  objective-forecast image space as drupalSettings JSON and the site builds
  image URLs client-side — `sadc_osf.py` re-reads that JSON each run
  (self-updating) and probes the constructible URLs (404s expected: a target
  season is published to ~4 months lead). Seasonal issues exist 2023-Jun on.
- **Wayback**: three generations of dead hosting rescued in `sadc_wayback.py`
  (dmc.co.zw = SADC Drought Monitoring Centre Harare ~2002-2006; old sadc.int
  CMS `/files/<hash>/`; Joomla csc.sadc.int). `STATEMENT_SARCOF.pdf` (2010) is
  SARCOF-14 — identified via its XMP title.
- **Known-lost**: SARCOF-11/12/13 statements (2007–2009, DMC site barely
  archived) and the SARCOF-22 / SARCOF-26 main statements (only their
  mid-season review/updates survive). No digitized machine-readable SARCOF
  record exists anywhere (checked Zenodo — the WAS-NextGen equivalent for
  Southern Africa hasn't been made).
- Session→year: SARCOF-1 = 1997, annual through SARCOF-27 (2023); from
  SARCOF-28 (Jan 2024) there are two forums per year (Jan/Feb mid-season +
  Aug/Sep main) — `session_year()` in `sadc_web.py` encodes this.
- Scope kept to core products: statements/summaries/updates/forecast bulletins
  + press releases carrying the outlook; OSF images limited to tercile
  probabilities (MME01 all variables, single systems PRCP only). Conference
  logistics (announcements, programmes, speeches) excluded. `cscgeo.sadc.int`
  (geoserver) was unreachable during the survey — worth re-probing someday for
  outlook polygons.
- `src/grab_sadc.py` runs only the three SADC modules and merges into
  `data/catalog_raw.json` (full `run_grab` re-crawls ACMAD THREDDS for hours).
- The CSC's own production pipeline is public at **github.com/sadccsc/osf**
  (PyCPT; inputs from IRI DL + C3S) but only the rendered maps are synced to
  the website — the forecast NetCDFs stay on their internal box. If exact
  grids are ever needed, rerun their pipeline with their committed config
  (dictionaries/) rather than digitizing.

## Digitized OSF data (since 2026-08-24)

`src/digitize_osf.py` inverts all 742 OSF map images back into data — the
rendering recipe in sadccsc/osf `functions_plot.py` (known colormaps, level
breaks, cartopy layout at dpi 300) makes them losslessly reversible to the
plotted classes. Georeferencing was fitted once against the CSC's own
`sadc_continental.geojson` (boundary-overlap 0.74; constant across all
image types) with per-image sub-pixel phase refinement; the grid is 0.25°,
centers at .125 offsets, 169×182 cells. Recovered per cell: dominant tercile
(1/2/3) + probability class lower bound {40,50,60,70} ({40,50,70} for
normal). NOT recoverable: continuous probs, the 33–40 class of any tercile
(renders white ≈ masked/no-data — all collapse to code 0), sub-dominant
terciles, and ~1.6% of cells under the in-axes CSC logo (open ocean; code
-1, as are border-overprinted cells, <1%). Output: one NetCDF per
(system, predictor, masked/unmasked) in `data/processed/osf-digitized/`
(mirrored to blob `processed/osf-digitized/`), dims (variable, issued,
lead 0–4, lat, lon) + season labels. Validated: reconstructions visually
match originals across all three palette families; DJF 2023-24 El Niño
drought (solid below-normal Zambia/Zimbabwe) and SON 2023 Tanzania wet
signal reproduce; MME↔SEAS51 dominant-tercile agreement 86%; masked files
show less signal than unmasked as expected. Palette gotcha for future eyes:
`Rx5day`'s category is "max_daily_rainfall", NOT "rainfall", so it (with CDD,
TG) uses the RdYlBu ramps — only PRCP gets teal/brown BrBG; onsetD gets BrBG
reversed.

SARCOF consensus record (2026-08-26): `src/digitize_sarcof_statements.py`
digitizes the 4-class consensus maps from every archived statement PDF —
vintages 2017/18, 19/20, 20/21, 21/22, 23/24, 24/25, 25/26 (2018/19 +
2022/23 statements lost; JFM only where drawn) — and merges the SARCOF-33
photos into `processed/sarcof-consensus/sarcof_consensus.nc` + country
stats/dry-ranks. Per-page candidate rasters (full render + each embedded
map image; best exterior-outline fit wins, MIN_FIT 0.70 gate), pages whose
first 1000 chars mention LONG-TERM/CLIMATOLOG are skipped (climatology
figures caption their months and previously produced a false JFM). All 27
fits 0.96–1.00; recons in `processed/sarcof-consensus/recons/` for QA.
Legend probability triplets are constant across statements (A/N/B:
40/35/25, 35/40/25, 25/40/35, 25/35/40) and recorded in the NetCDF attrs.
KEY FINDING: 2026/27 is the driest consensus vintage on the 8-vintage
record for BWA/LSO/NAM/SWZ/ZAF/ZWE/MOZ/ZMB in essentially every trimester,
and the FIRST to use the Below-Normal class at scale — earlier vintages
almost never drew brown. TZA wettest-ranked.

SARCOF-33 official deck (2026-08-27): `src/digitize_sarcof_deck.py`
digitizes the official CSC presentation ("SADC Regional Seasonal Outlook
for the 2026/27 season", presented 26 Aug 2026, archived at
`data/raw/sadc/sarcof/2026/SARCOF-33_Regional_Seasonal_Outlook_2026-27_presentation.pdf`,
NOT in the public catalog — pre-release until the statement is published)
and SUPERSEDES the photo digitization below. The four merged-forecast maps
are the largest embedded image on each "Seasonal Outlook for <season>"
page (the smaller map-sized image is a CHIRPS climatology panel).
Georeferencing does NOT reuse the statement fitter: its edge-mask score
locks onto the confidence-hatch texture (classified all of OND as
Below-Normal at fit 0.83), and the maps carry no graticule lines — instead
`fit_map` scores coastline point pairs (offshore must hit the flat ocean
fill (171,210,225), inland must not; coast-ness decided against the
all-Africa union, simplified BEFORE unioning or shapely eats GBs).
Slide-layout crops (NDJ/DJF/JFM cut at ~11.5°E) strand the fit at score 0
— white-padding the image first fixes it. Outputs in
`processed/sarcof33/`: `sarcof33_official_digitized.nc`, country stats,
`maps/` (extracted originals), `recons/` (QA). Photo-vs-official cell
agreement 94–97% per season; the confidence layer is now reliable
(validated: OND hatched across the whole south + clean DRC; JFM clean
eastern ZAF). Consensus record + encrypted page now use the official
version; headline unchanged (driest vintage on the 8-vintage record for
BWA/LSO/NAM/SWZ/ZAF/ZMB/ZWE/MOZ; TZA wettest; official OND ranks COD/MWI
wettest).

The deck's GPC-outlook pages also embed the CSC's own MME
tercile-PROBABILITY maps (OND + NDJ 2026 issued Aug 2026, skill-masked
variant only; DJF/JFM not included) — csc.sadc.int has NOT published OSF
issues past 2026-Apr (drupalSettings and constructed URLs both probed), so
these are the only record. `python -m src.digitize_sarcof_deck osf`
extracts them (the only square embedded image on "Global Producing
Centre" pages), upscales the slide-downscaled renders back to 1500×1500
and runs them through digitize_osf's calibration. Natives live at
`raw/sadc/sarcof/2026/osf-from-deck/` (deliberately NOT under
raw/sadc/osf-seasonal/, so a future grab of the real files is not
blocked), digitization in `processed/sarcof33/sarcof33_mme_osf.nc` +
country stats (NOT merged into the canonical osf-digitized stacks). The
encrypted page shows the two maps and plots their wet-lean as the 2026
MME dot in OND/NDJ facets. Result: BWA/LSO/SWZ/ZAF/ZWE driest vs the
skill-masked MME record (0% of record drier), TZA wettest (-67). When
CSC publishes, re-run grab_sadc -> digitize_osf -> osf_country_stats ->
compare_osf_seas5 -> derive_assets/derive_data_viewer -> upload_blob as
usual (public catalog/viewer/timeseries were deliberately NOT updated
from the deck — pre-release).

SARCOF-33 photo digitization (2026-08-26, SUPERSEDED by the official deck
above — kept for provenance): `src/digitize_sarcof_photos.py`
recovers the Aug-2026 forum's 4-class consensus zones (OND/NDJ/DJF 2026/27,
JFM 2027) from cell-phone slide photos in `raw/sadc/sarcof33-photos/` —
homographies fitted against the SADC exterior outline (FFT-seeded +
landmark fallback, matrices frozen in-module), hue-rule classification,
seam-fill + speckle-clean; confidence-hatch detection experimental. Outputs
in `processed/sarcof33/`. Headline: driest consensus outlook in our archive
(BWA/NAM/ZAF/LSO/ZWE Below-Normal all trimesters), corroborated by SEAS5
2026-08 bottom-decile percentiles; TZA wet. Note SEAS5 issued Aug cannot
cover JFM (needs lead 7).

Downstream of the digitized stacks (all since 2026-08-24):
- **Data viewer**: `derive_data_viewer.py` packs the two MME01 PRCP stacks as
  data-tile products (`sadc-mme`, `sadc-mme-full`). These carry a `groups`
  axis (target season per slice); the viewer compares percentiles and pin
  histories within same-season slices only. Dominant-only encoding: the
  dominant tercile's channel holds prob_lb×2, the other two hold 0; all-zero
  = no signal (skipped in dominant mode); sea (outside the SADC land mask) =
  255 nodata.
- **`src/osf_country_stats.py`**: per-country area fractions by dominant
  tercile + signed dryness score per (system, masked, issued, season), with
  midrank percentile of each issue within its same-target-season record —
  re-run after each grab+digitize to rank a NEW issue against history (the
  SEAS5-style "how extreme is this one" question, using the official regional
  product). Prints the latest MME01 issue's ranking.
- **`src/compare_osf_seas5.py`**: joins each country-slice to raw SEAS5 adm0
  seasonal means (prod DB `public.seas5`, PGSSLMODE=require) ranked against
  1993–2022 same-issue-month climatology, computes per-(country, issue
  month, lead) SEAS5 Spearman skill vs ERA5 obs (`public.era5`), and exports
  the site's `seas5_ref.json` (country-panel SEAS5 RP + skill column) and
  `timeseries.json` (Time-series tab: SEAS5 percentile history 1993+ and
  all six digitized products' country dryness as a 0–100 wet-lean index). Headline (2023-06→2026-04, 910
  unmasked slices): the CSC MME leans above-normal in ~76% of slices vs
  SEAS5's ~29% — a strong wet lean relative to raw SEAS5 for identical
  periods; when the MME does say below-normal there is real signal (SEAS5
  mean at the ~37–39th percentile); Spearman(dryness, SEAS5 pct) ≈ −0.25.
  Outputs + 2 charts in blob `processed/osf-digitized/` (charts/ dir).

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
